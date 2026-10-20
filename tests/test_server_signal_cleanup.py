"""HTTP CLI signal ownership without process signals or a live transport."""

from pathlib import Path
import signal
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest

import flow_of_work_mcp.server as server
from flow_of_work_mcp import profiles, runtime_ownership
from flow_of_work_mcp.core.domain import JobStatus
from flow_of_work_mcp.mcp_runtime import build_runtime
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError, acquire_runtime_ownership


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Replace CLI edges, preserving observable ownership and cleanup order."""
    def prior(signum, frame):
        pytest.fail("the prior disposition must not receive an owned TERM")

    state = SimpleNamespace(
        events=[], hooks={}, prior=prior, current=prior,
        config=SimpleNamespace(
            runtime=SimpleNamespace(database_path=tmp_path / "ledger.sqlite3"),
            logging=object(),
        ),
    )

    def step(name):
        state.events.append(name)
        action = state.hooks.get(name)
        if action is not None:
            return action()

    def term():
        assert callable(state.current)
        state.current(signal.SIGTERM, None)

    def getsignal(signum):
        assert signum == signal.SIGTERM
        step("getsignal")
        return state.current

    def install(signum, handler):
        assert signum == signal.SIGTERM
        previous = state.current
        state.current = handler
        step("restore" if handler is state.prior else "install")
        return previous

    def info(message, *args):
        if message.startswith("MCP server ready"):
            step("ready")
        elif message == "MCP server stopped":
            step("stopped")

    def error(message, *args):
        state.events.append(message)
        step("error")

    def summary():
        step("summary")
        return dict.fromkeys(
            ("schema_version", "config_path", "database_path", "import_root",
             "logs_path", "model_backend", "implementation_provider_enabled",
             "bootstrap_provider_enabled"),
            "test",
        )

    state.config.safe_summary = summary
    state.ownership = SimpleNamespace(close=lambda: step("ownership.close"))
    state.runtime = SimpleNamespace(close=lambda: step("runtime.close"))
    state.manager = SimpleNamespace(
        setup=lambda config: step("setup"), close=lambda: step("manager.close"),
    )
    state.logger = SimpleNamespace(info=info, error=error)
    state.app = SimpleNamespace(run=lambda **kwargs: step("run"))

    def build(config, *, ownership):
        assert config is state.config and ownership is state.ownership
        step("build")
        return state.runtime

    def app(runtime, **kwargs):
        assert runtime is state.runtime
        step("app")
        return state.app

    monkeypatch.setattr(server.signal, "getsignal", getsignal)
    monkeypatch.setattr(server.signal, "signal", install)
    monkeypatch.setattr(profiles, "prepare_profile", lambda *args: step("profile") or "test.yaml")
    monkeypatch.setattr(server, "load_config", lambda path: step("config") or state.config)
    monkeypatch.setattr(runtime_ownership, "acquire_runtime_ownership", lambda path: step("lease") or state.ownership)
    monkeypatch.setattr(server, "LoggerManager", lambda: step("manager") or state.manager)
    monkeypatch.setattr(server, "get_logger", lambda *args, **kwargs: step("logger") or state.logger)
    monkeypatch.setattr(server, "log_bootstrap_error", lambda message: step("bootstrap.error"))
    monkeypatch.setattr(server, "build_runtime_from_config", build)
    monkeypatch.setattr(server, "create_app", app)
    state.step, state.term = step, term
    state.main = lambda transport="streamable-http": server.main(["--transport", transport])
    return state


def _raise(error):
    raise error


def _cleanup_events(cli):
    return [event for event in cli.events if event in {
        "runtime.close", "ownership.close", "stopped", "manager.close", "restore",
    }]


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN, signal.SIG_DFL])
@pytest.mark.parametrize("stage", ["app", "ready", "run"])
def test_first_term_cleans_once_and_restores_exact_disposition(cli, prior, stage):
    if prior != "custom":
        cli.prior = cli.current = prior
    def building():
        assert cli.current is cli.prior

    def stopping():
        assert cli.current is not cli.prior
        cli.term()

    cli.hooks["build"] = building
    cli.hooks[stage] = stopping
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert cli.current is cli.prior
    assert _cleanup_events(cli) == [
        "runtime.close", "ownership.close", "stopped", "manager.close", "restore",
    ]


@pytest.mark.parametrize("cause", [None, KeyboardInterrupt(), SystemExit(17), RuntimeError("serving failed")])
def test_term_during_cleanup_preserves_original_exit(cli, cause):
    if cause is not None:
        cli.hooks["run"] = lambda: _raise(cause)
    for stage in ("runtime.close", "ownership.close", "stopped", "manager.close"):
        cli.hooks[stage] = lambda: (cli.term(), cli.term())
    if cause is None:
        cli.main()
    else:
        with pytest.raises(type(cause)) as error:
            cli.main()
        assert error.value is cause
    assert cli.current is cli.prior
    assert _cleanup_events(cli) == [
        "runtime.close", "ownership.close", "stopped", "manager.close", "restore",
    ]


@pytest.mark.parametrize("failure", [RuntimeError("failed"), server.RuntimeCompositionCleanupError("incomplete")])
def test_term_inside_error_logging_cannot_replace_failure_with_success(cli, failure):
    cli.hooks["app"] = lambda: _raise(failure)
    cli.hooks["error"] = cli.term
    with pytest.raises(type(failure)) as error:
        cli.main()
    assert error.value is failure
    assert cli.current is cli.prior
    assert _cleanup_events(cli)[-1] == "restore"


def test_term_inside_sdk_caught_exception_still_stops(cli):
    def serving():
        try:
            raise ValueError("benign SDK recovery")
        except ValueError:
            cli.term()

    cli.hooks["run"] = serving
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert cli.current is cli.prior
    assert "stopped" in cli.events


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
@pytest.mark.parametrize("failure", ["term", RuntimeError("install failed")])
def test_interrupted_install_restores_prior_and_closes_assigned_runtime(cli, failure, prior):
    if prior != "custom":
        cli.prior = cli.current = prior
    cli.hooks["install"] = cli.term if failure == "term" else lambda: _raise(failure)
    with pytest.raises(SystemExit if failure == "term" else RuntimeError) as error:
        cli.main()
    if failure == "term":
        assert error.value.code == 0
    else:
        assert error.value is failure
    assert "app" not in cli.events
    assert cli.current is cli.prior
    assert _cleanup_events(cli) == [
        "runtime.close", "ownership.close", "stopped", "manager.close", "restore",
    ]


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
@pytest.mark.parametrize("stage", ["setup", "logger", "summary", "build", "app", "ready", "run"])
def test_startup_and_runtime_errors_preserve_failure_and_disposition(cli, stage, prior):
    if prior != "custom":
        cli.prior = cli.current = prior
    failure = RuntimeError(stage)
    cli.hooks[stage] = lambda: _raise(failure)
    with pytest.raises(RuntimeError) as error:
        cli.main()
    assert error.value is failure
    assert cli.current is cli.prior
    installed = stage in {"app", "ready", "run"}
    assert cli.events.count("install") == int(installed)
    assert cli.events.count("restore") == int(installed)
    assert cli.events.count("runtime.close") == int(installed)
    assert cli.events.count("ownership.close") == 1
    assert cli.events.count("manager.close") == 1


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
@pytest.mark.parametrize("stage", ["profile", "config", "lease"])
def test_early_failure_never_replaces_prior_handler(cli, stage, prior):
    if prior != "custom":
        cli.prior = cli.current = prior
    failure = OSError(stage) if stage != "lease" else RuntimeOwnershipError("test", "lease failed")
    cli.hooks[stage] = lambda: _raise(failure)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert cli.current is cli.prior
    assert not {"install", "restore", "manager", "build"}.intersection(cli.events)


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
def test_incomplete_composition_keeps_ownership_without_install_or_false_stop(cli, prior):
    if prior != "custom":
        cli.prior = cli.current = prior
    failure = server.RuntimeCompositionCleanupError("worker cleanup failed")
    cli.hooks["build"] = lambda: _raise(failure)
    with pytest.raises(server.RuntimeCompositionCleanupError) as error:
        cli.main()
    assert error.value is failure
    assert cli.current is cli.prior
    assert _cleanup_events(cli) == ["manager.close"]
    assert "server composition cleanup incomplete; runtime ownership retained" in cli.events


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
@pytest.mark.parametrize("stage", ["runtime.close", "ownership.close", "manager.close"])
def test_cleanup_failure_stays_nonzero_and_always_restores(cli, stage, prior):
    if prior != "custom":
        cli.prior = cli.current = prior
    failure = RuntimeError(stage)
    cli.hooks["run"] = cli.term
    cli.hooks[stage] = lambda: (cli.term(), _raise(failure))
    with pytest.raises(RuntimeError) as error:
        cli.main()
    assert error.value is failure
    assert cli.current is cli.prior
    assert cli.events[-1] == "restore"
    assert ("stopped" in cli.events) == (stage == "manager.close")
    assert ("ownership.close" in cli.events) == (stage != "runtime.close")


@pytest.mark.parametrize("prior", ["custom", signal.SIG_IGN])
def test_restores_actual_disposition_after_composition_changes_it(cli, prior):
    def replacement(signum, frame):
        pytest.fail("the replacement prior must not receive owned TERM")

    replacement = replacement if prior == "custom" else prior
    initial_prior = cli.prior

    def building():
        assert cli.current is initial_prior
        cli.prior = cli.current = replacement

    cli.hooks["build"] = building
    cli.hooks["run"] = cli.term
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert cli.current is replacement
    assert cli.events[-1] == "restore"


def test_unrestorable_disposition_after_composition_closes_without_install(cli):
    def building():
        cli.current = None

    cli.hooks["build"] = building
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert cli.current is None
    assert "install" not in cli.events
    assert _cleanup_events(cli) == ["runtime.close", "ownership.close", "stopped", "manager.close"]


@pytest.mark.parametrize("preflight", ["off_thread", "unrestorable"])
def test_http_preflight_refuses_before_profile_or_other_effects(cli, preflight):
    if preflight == "unrestorable":
        cli.current = cli.prior = None
        with pytest.raises(SystemExit) as error:
            cli.main()
    else:
        failures = []

        def invoke():
            try:
                cli.main()
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=invoke)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert len(failures) == 1
        error = SimpleNamespace(value=failures[0])
    assert isinstance(error.value, SystemExit)
    assert error.value.code == 2
    assert cli.events == (["getsignal"] if preflight == "unrestorable" else [])


def test_stdio_off_thread_does_not_inspect_or_replace_signal_disposition(cli):
    cli.current = cli.prior = None
    failures = []

    def invoke():
        try:
            cli.main("stdio")
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=invoke)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert failures == []
    assert not {"getsignal", "install", "restore"}.intersection(cli.events)
    assert _cleanup_events(cli) == ["runtime.close", "ownership.close", "stopped", "manager.close"]


@pytest.mark.parametrize("join_fails", [False, True])
def test_term_real_runtime_waits_for_owned_job_or_retains_lease_on_join_failure(cli, tmp_path: Path, monkeypatch, join_fails):
    """Real job/executor/runtime cleanup; no HTTP, process signals or providers."""
    database = tmp_path / "owned" / "ledger.sqlite3"
    lease = acquire_runtime_ownership(database)
    runtime = build_runtime(database_path=database, import_root=tmp_path, runtime_ownership=lease)
    runtime.requirements.create_project("signal", "Signal cleanup", actor="test")
    started, finish, joining = Event(), Event(), Event()
    workers, helper_errors = [], []
    original_close = runtime.close
    original_lease_close = lease.close

    def operation():
        workers.append(current_thread())
        started.set()
        assert finish.wait(10)
        cli.events.append("job.finished")
        return {"completed": True}

    def lease_close():
        cli.events.append("lease.release")
        assert not workers[0].is_alive()
        original_lease_close()

    def runtime_close():
        cli.step("runtime.close")
        original_close()

    monkeypatch.setattr(lease, "close", lease_close)
    monkeypatch.setattr(runtime, "close", runtime_close)
    cli.runtime = runtime
    cli.ownership = lease
    cli.config.runtime.database_path = database
    cli.hooks["run"] = cli.term
    job = runtime.jobs.submit(
        project_id="signal", kind="signal_cleanup", actor="test",
        request_id="owned-job", operation=operation,
    )
    helper = None
    original_join = None
    try:
        assert started.wait(10)
        worker = workers[0]
        original_join = worker.join

        def join(timeout=None):
            cli.events.append("job.join")
            assert worker.is_alive()
            assert runtime.jobs.get("signal", job.job_id).status == JobStatus.RUNNING
            with pytest.raises(RuntimeOwnershipError):
                acquire_runtime_ownership(database)
            # The handler runs on the main thread, as real Python signals do.
            cli.term()
            cli.term()
            if join_fails:
                raise RuntimeError("owned worker join failed")
            joining.set()
            original_join(timeout)
            assert not worker.is_alive()
            cli.events.append("job.joined")

        monkeypatch.setattr(worker, "join", join)

        def release_after_join_started():
            try:
                assert joining.wait(10)
                assert "lease.release" not in cli.events
                assert "stopped" not in cli.events
                finish.set()
            except BaseException as error:
                helper_errors.append(error)
                finish.set()

        if not join_fails:
            helper = Thread(target=release_after_join_started)
            helper.start()
        with pytest.raises(RuntimeError if join_fails else SystemExit) as error:
            cli.main()
        assert cli.current is cli.prior
        assert cli.events.count("runtime.close") == 1
        if join_fails:
            assert str(error.value) == "owned worker join failed"
            assert worker.is_alive()
            assert "lease.release" not in cli.events
            assert "stopped" not in cli.events
            with pytest.raises(RuntimeOwnershipError):
                acquire_runtime_ownership(database)
        else:
            assert error.value.code == 0
            assert runtime.jobs.get("signal", job.job_id).status == JobStatus.COMPLETED
            ordered = ["job.join", "job.finished", "job.joined", "lease.release", "stopped", "manager.close", "restore"]
            positions = [cli.events.index(event) for event in ordered]
            assert positions == sorted(positions)
            assert not worker.is_alive()
            with acquire_runtime_ownership(database):
                pass
    finally:
        finish.set()
        if original_join is not None:
            monkeypatch.setattr(workers[0], "join", original_join)
        original_close()
        if helper is not None:
            helper.join(timeout=10)
            assert not helper.is_alive()
    assert helper_errors == []
