"""Qualify selected installed client entries through isolated CLI and public MCP."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from smoke_mcp import StdioServerParameters, qualify_parameters


PLATFORMS = ("antigravity", "gemini-cli", "opencode")
IDENTITY_SCRIPT = """
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import flow_of_work_mcp
package = Path(flow_of_work_mcp.__file__).resolve()
assert package.is_relative_to(Path(sys.prefix).resolve()), 'Flower must be installed inside the selected environment'
print(json.dumps({'distribution': 'flow-of-work-mcp', 'version': version('flow-of-work-mcp'),
                  'package': str(package), 'executable': sys.executable,
                  'prefix': sys.prefix, 'python': platform.python_version(),
                  'platform': sys.platform}))
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def snapshot(root: Path) -> dict:
    """Detect writes and path creation, including identical-byte rewrites."""
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        require(not path.is_symlink(), "Qualification state contains an unexpected symlink")
        record = {"mode": stat.S_IMODE(info.st_mode), "mtime_ns": info.st_mtime_ns}
        if path.is_file():
            record.update(size=info.st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            require(path.is_dir(), "Qualification state contains a nonregular path")
            record["directory"] = True
        result[path.relative_to(root).as_posix()] = record
    return result


def snapshot_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "Expected a JSON object in isolated qualification state")
    return value


class InstalledCLI:
    def __init__(self, python: Path, cwd: Path, environment: dict[str, str]):
        self.python = python
        self.cwd = cwd
        self.environment = environment
        self.receipts: list[dict] = []

    def execute(self, arguments: list[str], *, identity: bool = False) -> dict:
        command = [str(self.python), *(["-c", IDENTITY_SCRIPT] if identity else ["-m", "flow_of_work_mcp.cli", *arguments])]
        completed = subprocess.run(command, cwd=self.cwd, env=self.environment, capture_output=True,
                                   text=True, encoding="utf-8", timeout=30, check=False)
        receipt = {"arguments": arguments, "returncode": completed.returncode, "stderr": completed.stderr}
        self.receipts.append(receipt)
        require(completed.returncode == 0, "Installed Flower CLI failed: " + completed.stderr.strip())
        value = json.loads(completed.stdout)
        require(isinstance(value, dict), "Installed Flower CLI did not return a JSON object")
        receipt["result"] = value
        return value

    def no_write(self, root: Path, arguments: list[str]) -> dict:
        before = snapshot(root)
        result = self.execute(arguments)
        after = snapshot(root)
        require(after == before, "Read, dry-run or replay operation changed isolated files: " + arguments[0])
        self.receipts[-1]["no_write"] = True
        self.receipts[-1]["state_sha256"] = snapshot_hash(after)
        return result


async def qualify_platform(python: Path, platform: str, root: Path, environment: dict[str, str], result: dict) -> None:
    root.mkdir()
    config = root / "selected-client.json"
    profile_root = root / "profiles"
    original = {
        "ui": {"theme": "synthetic-dark"},
        "mcp": {"allowed": ["foreign"], "excluded": ["blocked-fixture"]},
        "mcpServers": {"foreign": {"command": "synthetic-foreign-do-not-execute", "args": ["--fixture"]}},
    }
    if platform == "opencode":
        original = {"instructions": ["existing.md"], "mcp": {
            "timeout": {"startup": 30000}, "servers": {
                "foreign": {"type": "local", "command": ["synthetic-foreign-do-not-execute"], "disabled": True}}}}
    config.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    cli = InstalledCLI(python, root, environment)
    result.update(platform=platform, status="running", cli_receipts=cli.receipts)
    location = ["--platform", platform, "--client-config", str(config),
                "--profile", "client-smoke", "--profile-root", str(profile_root)]

    dry_install = cli.no_write(root, ["install", *location, "--dry-run"])
    require(dry_install["dry_run"] is True and dry_install["changed"] is False,
            "Dry-run registration reported a write")
    require(not profile_root.exists(), "Dry-run registration created a profile")

    installed = cli.execute(["install", *location])
    require(installed["state"] == "registered" and installed["changed"] is True,
            "Fresh selected-file registration did not install")
    document = read_json(config)
    servers = document["mcp"]["servers"] if platform == "opencode" else document["mcpServers"]
    entry = servers.pop("flower")
    require(document == original, "Registration changed foreign settings, server or policy")
    if platform == "opencode":
        require(set(entry) == {"type", "command", "disabled", "codemode"}
                and entry["type"] == "local" and entry["disabled"] is False and entry["codemode"] is False,
                "OpenCode V2 must retain direct local tools")
        command = entry["command"]
        require(isinstance(command, list) and len(command) > 1 and all(isinstance(value, str) for value in command),
                "OpenCode command must be a string array")
    else:
        require(isinstance(entry, dict) and set(entry) == {"command", "args"},
                "Google registration must contain only the generated command and arguments")
        require(isinstance(entry["args"], list) and all(isinstance(value, str) for value in entry["args"]),
                "Generated command arguments must be strings")
        command = [entry["command"], *entry["args"]]
    require(isinstance(command[0], str) and Path(command[0]).is_absolute(),
            "Generated interpreter must be absolute")
    require(os.path.normcase(command[0]) == os.path.normcase(str(python)),
            "Registration did not preserve the selected installed interpreter")
    ownership_path = Path(installed["receipt_path"])
    require(ownership_path.is_relative_to(profile_root), "Ownership receipt escaped the isolated profile root")
    ownership = read_json(ownership_path)
    require(ownership["state"] == "installed" and ownership["platform"] == platform
            and ownership["managed_entry"] == entry, "Persisted ownership does not describe the installed entry")

    diagnosis = cli.no_write(root, ["doctor", *location])
    require(diagnosis["profile_present"] is True and diagnosis["runtime_probed"] is False
            and diagnosis["internal_inference_enabled"] is False
            and diagnosis["registration"]["state"] == "registered",
            "Doctor did not truthfully describe the isolated core registration")
    profile = Path(diagnosis["profile_config"])
    ledger = Path(diagnosis["database_path"])
    require(profile.is_relative_to(profile_root) and ledger.is_relative_to(profile.parent),
            "Generated runtime paths escaped the isolated profile")
    require(not ledger.exists(), "Registration or doctor created a lifecycle ledger")
    require(command[1:] == ["-m", "flow_of_work_mcp.cli", "serve", "--config", str(profile),
                              "--transport", "stdio"], "Generated entry differs from the canonical stdio CLI")
    replay = cli.no_write(root, ["install", *location])
    require(replay["state"] == "registered" and replay["changed"] is False,
            "Repeated installation did not report an unchanged owned registration")

    # Execute exactly the persisted entry, without substituting a console path,
    # synthesized server arguments or direct calls to Flower's Python services.
    parameters = StdioServerParameters(command=command[0], args=command[1:],
                                       cwd=str(root), env=environment)
    result["generated_entry"] = entry
    result["public_mcp"] = await asyncio.wait_for(qualify_parameters(parameters), timeout=120)
    require(result["public_mcp"]["status"] == "passed" and result["public_mcp"]["restart"] == "passed",
            "Generated entry did not pass the public MCP restart fixture")
    require(ledger.is_file() and ledger.stat().st_size > 0, "Public MCP did not create the dedicated ledger")

    retained = snapshot(profile.parent)
    dry_remove = cli.no_write(root, ["uninstall", *location, "--dry-run"])
    require(dry_remove["dry_run"] is True and dry_remove["changed"] is False,
            "Dry-run removal reported a write")
    removed = cli.execute(["uninstall", *location])
    require(removed["state"] == "absent" and removed["changed"] is True,
            "Owned removal did not remove the selected registration")
    require(read_json(config) == original, "Removal changed foreign settings, server or policy")
    require(snapshot(profile.parent) == retained, "Removal changed the retained profile, ledger or evidence")
    require(read_json(ownership_path)["state"] == "removed", "Ownership receipt did not record removal")
    diagnosis = cli.no_write(root, ["doctor", *location])
    require(diagnosis["profile_present"] is True and diagnosis["registration"]["state"] == "absent",
            "Doctor did not describe retained profile and removed registration")
    replay = cli.no_write(root, ["uninstall", *location])
    require(replay["state"] == "absent" and replay["changed"] is False,
            "Repeated removal did not report an unchanged absence")
    result.update(status="passed", foreign_settings_and_policy="preserved", ownership="removed",
                  profile_ledger_evidence="retained", retained_state_sha256=snapshot_hash(retained))


async def qualify(python: Path, result: dict, platforms: list[str]) -> None:
    require(python.is_absolute() and python.is_file(), "--python must name an absolute installed interpreter")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "FLOWER_HOME"}}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="flower-installed-clients-") as directory:
        root = Path(directory).resolve()
        result["installed"] = InstalledCLI(python, root, environment).execute([], identity=True)
        for platform in platforms:
            record: dict = {}
            result["platforms"].append(record)
            await qualify_platform(python, platform, root / platform, environment, record)
    result["temporary_state"] = "removed"
    result["status"] = "passed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path, help="absolute interpreter containing the installed Flower wheel")
    parser.add_argument("--output", required=True, type=Path, help="retained JSON qualification receipt")
    parser.add_argument("--platform", action="append", choices=PLATFORMS,
                        help="qualify only selected clients; default: all supported smoke clients")
    args = parser.parse_args()
    result: dict = {"contract": "flower.installed-client-qualification.v1", "status": "running", "platforms": [],
                    "scope": "Synthetic selected-file installation and generated stdio MCP mechanics; native client trust, precedence, usability and acceptance are not qualified"}
    failure = None
    try:
        asyncio.run(qualify(args.python, result, args.platform or list(PLATFORMS)))
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        failure = exc
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "platforms"}, ensure_ascii=False))
    if failure is not None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
