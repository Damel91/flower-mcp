"""Print agent bootstrap, manage client integration, or launch Flower."""
from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path
import sys

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
    parser = argparse.ArgumentParser(prog="flower-mcp", description="Flower MCP installation and standalone lifecycle plane")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("bootstrap", help="print instructions for an agent to update its project's AGENTS.md")
    serve = commands.add_parser("serve", help="start the MCP server (stdio by default)")
    _location_options(serve, config=True)
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    for operation in ("install", "doctor", "uninstall"):
        command = commands.add_parser(operation)
        _location_options(command)
        command.add_argument("--platform", choices=("codex", "claude-code", "cursor"), required=operation != "doctor")
        command.add_argument("--client-config", type=Path)
        if operation != "doctor":
            command.add_argument("--dry-run", action="store_true")
        if operation == "install":
            command.add_argument("--import-root", type=Path)
            command.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values[0].startswith("-") and values[0] not in {"--help", "-h"}:
        values.insert(0, "serve")
    parser = build_cli_parser()
    args = parser.parse_args(values)
    try:
        if args.operation == "bootstrap":
            print(files("flow_of_work_mcp").joinpath("resources/agent-bootstrap.md").read_text(encoding="utf-8"), end="")
            return
        if args.operation == "serve":
            if not 1 <= args.port <= 65535:
                raise ProfileError("--port must be in the range 1..65535")
            if args.config is not None and args.profile_root is not None:
                raise ProfileError("--config and --profile-root cannot be combined")
            config_path = args.config if args.config is not None else prepare_profile(args.profile_root, args.profile or "default")
            from flow_of_work_mcp.server import main as serve_main
            serve_main(["--config", str(config_path), "--transport", args.transport, "--host", args.host, "--port", str(args.port)])
            return
        from flow_of_work_mcp.client_registration import (
            default_client_config, inspect_client_registration,
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
            result = {"contract": "flower.installation-diagnosis.v1", "profile_config": str(config_path),
                "profile_present": config_path.is_file(), "runtime_probed": False,
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
