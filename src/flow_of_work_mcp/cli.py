"""Print agent bootstrap, manage client integration, or launch Flower."""
from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path
import sys

from flow_of_work_mcp.client_registration import PLATFORMS
from flow_of_work_mcp.config import load_config
from flow_of_work_mcp.profiles import ProfileError, prepare_profile, profile_config_path, profile_root
from flow_of_work_mcp.runtime_ownership import RuntimeOwnershipError


def _location_options(parser: argparse.ArgumentParser, *, config: bool = False) -> None:
    if config:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--config", type=Path)
        group.add_argument("--profile")
    else:
        parser.add_argument("--profile", default="default")
    parser.add_argument("--profile-root", type=Path)


def build_cli_parser() -> argparse.ArgumentParser:
    from flow_of_work_mcp.dashboard_https_listener import add_dashboard_https_arguments

    parser = argparse.ArgumentParser(prog="flower-mcp", description="Flower MCP installation and standalone lifecycle plane")
    commands = parser.add_subparsers(dest="operation", required=True)
    serve = commands.add_parser("serve", help="start the MCP server (stdio by default)")
    _location_options(serve, config=True)
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    add_dashboard_https_arguments(serve)
    service = commands.add_parser("service", help="optional per-user HTTP startup; install never starts Flower")
    service.add_argument("service_operation", choices=("plan", "install", "enable", "disable", "start", "stop", "status", "remove", "run",
                                                        "enroll-upgrade", "upgrade", "upgrade-status"))
    _location_options(service, config=True)
    service.add_argument("--host", default="127.0.0.1")
    service.add_argument("--port", type=int, default=8010)
    service.add_argument("--version", help="exact stable target for service upgrade")
    settings = commands.add_parser("settings", help="apply a retained profile settings draft while Flower is stopped")
    settings.add_argument("settings_operation", choices=("apply",))
    _location_options(settings, config=True)
    settings.add_argument("--draft-id", required=True)
    upgrade = commands.add_parser("upgrade", help="upgrade this official installation after stopping Flower")
    _location_options(upgrade)
    upgrade.add_argument("--version", required=True, help="exact newer official version, without v")
    upgrade.add_argument("--dry-run", action="store_true", help="inspect the upgrade without changing the installation")
    upgrade.add_argument("--backup-root", type=Path, help="select an absolute directory for the installer backup")
    data = commands.add_parser("data", help="back up, export and restore lifecycle data")
    data_actions = data.add_subparsers(dest="data_operation", required=True)
    for operation in ("backup", "export"):
        command = data_actions.add_parser(operation, help="create an archive while the selected Flower profile is stopped")
        _location_options(command, config=True)
        command.add_argument("--output", type=Path, required=True)
        if operation == "export":
            command.add_argument("--project-id", required=True)
    for operation in ("inspect", "restore"):
        command = data_actions.add_parser(operation, help="verify an archive" if operation == "inspect" else
                                          "verify and restore an archive to a new local directory")
        command.add_argument("--archive", type=Path, required=True)
        if operation == "restore":
            command.add_argument("--restore-dir", type=Path, required=True)
    commands.add_parser("bootstrap", help="print the provider-neutral Flower agent bootstrap")
    commands.add_parser("probe", add_help=False, help="inspect an explicit HTTP MCP endpoint; use probe --help")
    purge = commands.add_parser("project-purge", help="native user control: prepare/inspect/delete/reconcile an owned project; never a model tool")
    purge.add_argument("purge_operation", choices=("prepare", "inspect", "delete", "reconcile"))
    _location_options(purge, config=True)
    purge.add_argument("--project-id", required=True)
    purge.add_argument("--deletion-id", required=True)
    purge.add_argument("--expected-fingerprint", default="")
    purge.add_argument("--confirm-project-id", default="")
    purge.add_argument("--host-quiescence-ref", default="")
    purge.add_argument("--host-stopped-run-id", action="append", default=[])
    purge.add_argument("--acknowledge-host-cleanup", action="store_true")
    for operation in ("install", "doctor", "uninstall"):
        command = commands.add_parser(operation)
        _location_options(command)
        command.add_argument("--platform", choices=PLATFORMS, required=operation != "doctor")
        command.add_argument("--client-config", type=Path)
        if operation != "doctor":
            command.add_argument("--dry-run", action="store_true")
        if operation == "install":
            command.add_argument("--import-root", type=Path)
            command.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == "probe":
        from flow_of_work_mcp.mcp_probe import main as probe_main
        probe_main(values[1:])
        return
    if not values or values[0].startswith("-") and values[0] not in {"--help", "-h"}:
        values.insert(0, "serve")
    parser = build_cli_parser()
    args = parser.parse_args(values)
    if args.operation == "project-purge":
        from flow_of_work_mcp.native_project_purge import run_project_purge
        result, exit_code = run_project_purge(args)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        if exit_code:
            raise SystemExit(exit_code)
        return
    try:
        if args.operation == "bootstrap":
            print(files("flow_of_work_mcp").joinpath("resources/agent-bootstrap.md").read_text(encoding="utf-8"), end="")
            return
        if args.operation == "upgrade":
            from flow_of_work_mcp.release_upgrade import run_release_upgrade
            status = run_release_upgrade(version=args.version, profile=args.profile,
                profile_root=args.profile_root, backup_root=args.backup_root, dry_run=args.dry_run)
            if status:
                raise SystemExit(status)
            return
        if args.operation == "data":
            from flow_of_work_mcp.ledger_recovery import backup_profile, inspect_or_restore
            if args.data_operation in {"backup", "export"}:
                if args.config is not None and args.profile_root is not None:
                    raise ProfileError("--config and --profile-root cannot be combined")
                config_path = (args.config if args.config is not None else
                               profile_config_path(args.profile_root, args.profile or "default"))
                result = backup_profile(config_path, args.output, project_id=getattr(args, "project_id", None))
            else:
                result = inspect_or_restore(args.archive, restore_dir=getattr(args, "restore_dir", None))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.operation == "settings":
            if args.config is not None and args.profile_root is not None:
                raise ProfileError("--config and --profile-root cannot be combined")
            config_path = (args.config if args.config is not None else
                           profile_config_path(args.profile_root, args.profile or "default"))
            from flow_of_work_mcp.profile_settings import apply_profile_settings
            result = apply_profile_settings(config_path, args.draft_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.operation == "service":
            if args.config is not None and args.profile_root is not None:
                raise ProfileError("--config and --profile-root cannot be combined")
            config_path = (args.config if args.config is not None else
                           profile_config_path(args.profile_root, args.profile or "default"))
            if (args.service_operation == "upgrade") != (args.version is not None):
                raise ProfileError("service upgrade requires --version; other service commands do not accept it")
            if args.service_operation in {"enroll-upgrade", "upgrade", "upgrade-status"}:
                from flow_of_work_mcp.managed_upgrade import native_operation
                result = native_operation(args.service_operation, config_path, args.host, args.port, args.version)
            else:
                from flow_of_work_mcp.managed_service import run_service
                result = run_service(args.service_operation, config_path, host=args.host, port=args.port)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.operation == "serve":
            if not 1 <= args.port <= 65535:
                raise ProfileError("--port must be in the range 1..65535")
            if args.config is not None and args.profile_root is not None:
                raise ProfileError("--config and --profile-root cannot be combined")
            location = ["--config", str(args.config)] if args.config is not None else ["--profile", args.profile or "default"]
            if args.profile_root is not None:
                location.extend(("--profile-root", str(args.profile_root)))
            from flow_of_work_mcp.dashboard_https_listener import dashboard_https_arguments
            from flow_of_work_mcp.server import main as serve_main
            serve_main([*location, "--transport", args.transport, "--host", args.host, "--port", str(args.port),
                        *dashboard_https_arguments(args)])
            return
        from flow_of_work_mcp.client_registration import (
            check_implicit_client_config, default_client_config, inspect_client_registration,
            register_client, registration_receipt_path, unregister_client,
        )
        root = profile_root(args.profile_root)
        config_path = profile_config_path(root, args.profile)
        if args.client_config is not None and args.platform is None:
            raise ProfileError("--client-config requires --platform")
        if args.platform is not None:
            client_path = args.client_config if args.client_config is not None else default_client_config(args.platform)
            receipt = registration_receipt_path(root, args.platform, client_path)
        if args.operation == "install":
            if args.client_config is None:
                check_implicit_client_config(args.platform, client_path)
            # Preflight both documents before creating a profile. All dry-run
            # validation uses prospective absolute paths without writes.
            prepare_profile(root, args.profile, import_root=args.import_root, dry_run=True)
            preflight = register_client(platform=args.platform, client_config=client_path, profile_config=config_path,
                receipt_path=receipt, python_executable=Path(sys.executable), replace=args.replace, dry_run=True)
            if args.dry_run:
                result = preflight
            else:
                prepare_profile(root, args.profile, import_root=args.import_root)
                result = register_client(platform=args.platform, client_config=client_path, profile_config=config_path,
                    receipt_path=receipt, python_executable=Path(sys.executable), replace=args.replace)
            result["message"] = "Flower registration prepared; the client may require reload and trust approval. No lifecycle project was created."
        elif args.operation == "uninstall":
            result = unregister_client(platform=args.platform, client_config=client_path, receipt_path=receipt, dry_run=args.dry_run)
            result["message"] = "Only owned client registration is removed; profiles, ledgers and evidence are retained."
        else:
            from flow_of_work_mcp.installation_identity import installed_distribution_identity
            result = {"contract": "flower.installation-diagnosis.v1", "profile_config": str(config_path),
                "profile_present": config_path.is_file(), "runtime_probed": False,
                "distribution": installed_distribution_identity(),
                "message": "Diagnosis inspects selected files only; client trust, precedence and connection require separate verification."}
            if config_path.exists() or config_path.is_symlink():
                prepare_profile(root, args.profile, dry_run=True)
                config = load_config(config_path)
                result.update(database_path=str(config.runtime.database_path), import_root=str(config.runtime.import_root),
                    internal_inference_enabled=config.model.enabled, packet_mode=config.packet_provider.mode,
                    test_mode=config.test_provider.mode)
            if args.platform is not None:
                result["registration"] = inspect_client_registration(platform=args.platform, client_config=client_path, receipt_path=receipt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, RuntimeOwnershipError) as exc:
        # Installation domain errors carry safe messages, without settings or
        # parser excerpts. Preserve their code for repeatable diagnosis.
        code = getattr(exc, "code", None)
        parser.error(f"{code}: {exc}" if code else str(exc))


if __name__ == "__main__":
    main()
