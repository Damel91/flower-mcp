"""Container qualifier boundary tests; fake engine, no daemon or domain services."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import smoke_container as smoke
import smoke_mcp


class FakeEngine:
    command = "/fake/engine"

    def __init__(self):
        self.calls = []
        self.volumes = {}
        self.containers = {}
        self.create_failure = False
        self.wrong_owner = False
        self.remove_failure = False
        self.list_failure = False
        self.volume_list_failure = False
        self.exit_code = "0"
        self.image_command = smoke.SERVER_COMMAND

    def execute(self, arguments, *, timeout=45):
        self.calls.append(arguments)
        operation = arguments[:2]
        if operation == ["info", "--format"]:
            return "{}"
        if operation == ["image", "inspect"]:
            return json.dumps([{"Id": "sha256:fixture", "Architecture": "amd64", "Os": "linux",
                                "Config": {"Cmd": self.image_command, "Entrypoint": None}}])
        if operation == ["volume", "create"]:
            if self.create_failure:
                raise RuntimeError("volume creation failed")
            owner = arguments[arguments.index("--label") + 1].split("=", 1)[1]
            self.volumes[arguments[-1]] = "unrelated-owner" if self.wrong_owner else owner
            return arguments[-1]
        if operation == ["volume", "inspect"]:
            return json.dumps([{"Labels": {smoke.LABEL: self.volumes[arguments[-1]]}}])
        if operation == ["volume", "ls"]:
            if self.volume_list_failure:
                raise RuntimeError("cannot prove volume cleanup state")
            return "\n".join(self.volumes)
        if operation == ["volume", "rm"]:
            if any(item["volume"] == arguments[-1] for item in self.containers.values()):
                raise RuntimeError("volume is busy")
            del self.volumes[arguments[-1]]
            return arguments[-1]
        if arguments[0] == "run":
            name = arguments[arguments.index("--name") + 1]
            owner = arguments[arguments.index("--label") + 1].split("=", 1)[1]
            mount = arguments[arguments.index("--mount") + 1]
            volume = next(part.removeprefix("src=") for part in mount.split(",") if part.startswith("src="))
            self.containers[name] = {"owner": owner, "volume": volume}
            if arguments[-1] == smoke.IMAGE_AUDIT:
                return json.dumps({"uid": 10001, "gid": 10001, "inference": "absent", "version": "fixture"})
            if arguments[-1] == smoke.PROFILE_AUDIT:
                return json.dumps({"root": "/data/profiles/default", "files": ["flower.yaml", "ledger.sqlite3"]})
            return ""
        if operation == ["container", "wait"]:
            if arguments[-1] not in self.containers:
                raise RuntimeError("missing container")
            return self.exit_code
        if operation == ["container", "ls"]:
            if self.list_failure:
                raise RuntimeError("engine listing failed")
            owner = arguments[arguments.index("--filter") + 1].removeprefix(f"label={smoke.LABEL}=")
            return "\n".join(name for name, item in self.containers.items() if item["owner"] == owner)
        if operation == ["container", "inspect"]:
            return json.dumps([{"Config": {"Labels": {smoke.LABEL: self.containers[arguments[-1]]["owner"]}}}])
        if operation == ["container", "rm"]:
            if self.remove_failure:
                raise RuntimeError("container removal failed")
            del self.containers[arguments[-1]]
            return arguments[-1]
        raise AssertionError(f"Unexpected fake engine operation: {arguments}")


class ContainerSmokeTests(unittest.TestCase):
    def run_qualifier(self, engine, *, protocol_failure=False):
        sessions = []

        @asynccontextmanager
        async def public_session(parameters, *, strict=False):
            self.assertTrue(strict)
            engine.execute(parameters.args)
            sessions.append(parameters)
            yield object()

        async def fixture(factory):
            for _ in range(2):
                async with factory():
                    if protocol_failure:
                        raise RuntimeError("public protocol failed")
            return {"status": "passed", "restart": "passed", "public_calls": 19, "receipts": []}

        with patch.object(smoke, "public_session", public_session), patch.object(smoke, "qualify_sessions", fixture):
            result = asyncio.run(smoke.qualify(engine, "flower:fixture"))
        return result, sessions

    def test_distinct_containers_share_only_a_fresh_owned_volume(self):
        engine = FakeEngine()
        result, sessions = self.run_qualifier(engine)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["cleanup"], "passed")
        self.assertEqual(result["container_recreation"], "passed")
        self.assertEqual(len(sessions), 2)
        names = [item.args[item.args.index("--name") + 1] for item in sessions]
        self.assertEqual(len(set(names)), 2)
        mounts = [item.args[item.args.index("--mount") + 1] for item in sessions]
        self.assertEqual(len(set(mounts)), 1)
        self.assertRegex(mounts[0], r"^type=volume,src=flower-smoke-[a-f0-9]{32},dst=/data$")
        for item in sessions:
            self.assertIn("-i", item.args)
            self.assertNotIn("-t", item.args)
            self.assertIn("--pull=never", item.args)
            self.assertEqual(item.args[item.args.index("--network") + 1], "none")
            self.assertEqual(item.args[-1], "flower:fixture")
        self.assertEqual(engine.volumes, {})
        self.assertEqual(engine.containers, {})

    def test_protocol_failure_cleans_its_resources_without_passing(self):
        engine = FakeEngine()
        with self.assertRaisesRegex(RuntimeError, "public protocol failed"):
            self.run_qualifier(engine, protocol_failure=True)
        self.assertEqual(engine.volumes, {})
        self.assertEqual(engine.containers, {})

    def test_initial_volume_failure_does_not_remove_any_volume(self):
        engine = FakeEngine()
        engine.create_failure = True
        with self.assertRaisesRegex(RuntimeError, "volume creation failed"):
            self.run_qualifier(engine)
        self.assertFalse(any(call[:2] == ["volume", "rm"] for call in engine.calls))

    def test_volume_creation_with_lost_response_reconciles_its_owned_effect(self):
        engine = FakeEngine()
        original = engine.execute

        def lost_response(arguments, **keywords):
            result = original(arguments, **keywords)
            if arguments[:2] == ["volume", "create"]:
                raise RuntimeError("volume creation response lost")
            return result

        engine.execute = lost_response
        with self.assertRaisesRegex(RuntimeError, "volume creation response lost"):
            self.run_qualifier(engine)
        self.assertEqual(engine.volumes, {})
        self.assertTrue(any(call[:2] == ["volume", "rm"] for call in engine.calls))

    def test_uncertain_creation_and_unknown_cleanup_never_passes_or_removes(self):
        engine = FakeEngine()
        engine.create_failure = True
        engine.volume_list_failure = True
        with self.assertRaisesRegex(RuntimeError, "volume creation failed; Owned qualification resource cleanup failed: cannot prove volume cleanup state"):
            self.run_qualifier(engine)
        self.assertFalse(any(call[:2] == ["volume", "rm"] for call in engine.calls))

    def test_wrong_ownership_prevents_use_and_removal(self):
        engine = FakeEngine()
        engine.wrong_owner = True
        with self.assertRaisesRegex(RuntimeError, "unowned volume"):
            self.run_qualifier(engine)
        self.assertFalse(any(call[:2] == ["volume", "rm"] or call[0] == "run" for call in engine.calls))
        self.assertEqual(list(engine.volumes.values()), ["unrelated-owner"])

    def test_cleanup_failure_cannot_be_reported_as_passed(self):
        engine = FakeEngine()
        engine.remove_failure = True
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.run_qualifier(engine)
        self.assertTrue(engine.containers)
        self.assertTrue(engine.volumes)

    def test_primary_and_cleanup_failures_remain_visible(self):
        engine = FakeEngine()
        original = engine.execute

        def failing(arguments, **keywords):
            if arguments[0] == "run":
                result = original(arguments, **keywords)
                engine.remove_failure = True
                raise RuntimeError("image audit failed")
            return original(arguments, **keywords)

        engine.execute = failing
        with self.assertRaisesRegex(RuntimeError, "image audit failed; Container cleanup failed:.*Owned qualification resource cleanup failed"):
            self.run_qualifier(engine)

    def test_engine_listing_failure_is_not_assumed_to_mean_absence(self):
        engine = FakeEngine()
        engine.list_failure = True
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.run_qualifier(engine)
        self.assertTrue(engine.containers)

    def test_nonzero_container_exit_cannot_be_reported_as_passed(self):
        engine = FakeEngine()
        engine.exit_code = "23"
        with self.assertRaisesRegex(RuntimeError, "exit=23"):
            self.run_qualifier(engine)
        self.assertEqual(engine.volumes, {})
        self.assertEqual(engine.containers, {})

    def test_incompatible_default_command_creates_no_state(self):
        engine = FakeEngine()
        engine.image_command = ["another-server"]
        with self.assertRaisesRegex(RuntimeError, "canonical Flower"):
            self.run_qualifier(engine)
        self.assertFalse(any(call[:2] == ["volume", "create"] for call in engine.calls))

    def test_cleanup_never_selects_unregistered_or_unowned_containers(self):
        engine = FakeEngine()
        resources = smoke.OwnedContainers(engine, "flower:fixture")
        resources.containers = ["generated-name"]
        engine.containers["generated-name"] = {"owner": "someone-else", "volume": "their-volume"}
        engine.containers["another-container"] = {"owner": resources.owner, "volume": "another-volume"}
        resources.close()
        self.assertEqual(set(engine.containers), {"generated-name", "another-container"})

    def test_local_fixture_retains_its_isolated_command_and_profile(self):
        captured = {}

        async def parameters(parameters):
            captured["parameters"] = parameters
            captured["cwd_exists"] = Path(parameters.cwd).is_dir()
            return {"status": "passed"}

        with patch.object(smoke_mcp, "qualify_parameters", parameters):
            result = asyncio.run(smoke_mcp.qualify("/installed/flower-mcp"))
        self.assertEqual(result, {"status": "passed"})
        parameters = captured["parameters"]
        self.assertTrue(captured["cwd_exists"])
        self.assertFalse(Path(parameters.cwd).exists())
        self.assertEqual(parameters.command, "/installed/flower-mcp")
        self.assertEqual(parameters.args[:3], ["serve", "--profile", "smoke"])
        self.assertEqual(parameters.args[-2:], ["--transport", "stdio"])
        self.assertEqual(parameters.env["FLOWER_HOME"], parameters.args[4])
        self.assertNotIn("PYTHONPATH", parameters.env)

    def test_container_session_rejects_malformed_stdout_even_if_calls_could_succeed(self):
        @asynccontextmanager
        async def transport(parameters):
            yield None, None

        class Session:
            def __init__(self, *streams, message_handler):
                self.handler = message_handler

            async def __aenter__(self):
                await self.handler(ValueError("non-JSON diagnostic on stdout"))
                return self

            async def __aexit__(self, *arguments):
                return False

            async def initialize(self):
                pass

        async def operation():
            async with smoke_mcp.public_session(None, strict=True):
                pass

        with patch.object(smoke_mcp, "stdio_client", transport), patch.object(smoke_mcp, "ClientSession", Session):
            with self.assertRaisesRegex(RuntimeError, "Invalid MCP stdout: non-JSON diagnostic on stdout"):
                asyncio.run(operation())


if __name__ == "__main__":
    unittest.main()
