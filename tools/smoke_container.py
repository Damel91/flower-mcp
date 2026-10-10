"""Qualify an already-built Flower image through owned, network-disabled containers."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from mcp import StdioServerParameters

from smoke_mcp import public_session, qualify_sessions


LABEL = "flower.qualifier"
SERVER_COMMAND = ["flower-mcp", "serve", "--profile", "default", "--profile-root", "/data", "--transport", "stdio"]

IMAGE_AUDIT = r'''
import importlib.metadata as metadata
from importlib.resources import files
import json, os
from pathlib import Path
import yaml

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(os.getuid() == 10001 and os.getgid() == 10001, "image must run as UID/GID10001")
require(os.environ.get("FLOWER_HOME") == "/data", "FLOWER_HOME must be /data")
require(os.access("/data", os.W_OK), "/data must be writable without ownership repair")
distribution = metadata.distribution("flow-of-work-mcp")
package = distribution.locate_file("flow_of_work_mcp").resolve()
require("site-packages" in package.parts, "server must use the installed package")
resources = files("flow_of_work_mcp.resources")
config = yaml.safe_load(resources.joinpath("standalone.yaml").read_text(encoding="utf-8"))
bootstrap = resources.joinpath("agent-bootstrap.md").read_text(encoding="utf-8")
require(config["model"]["enabled"] is False and config["providers"] == {}, "core profile must disable inference/providers")
require(config["logging"]["enable_console"] is False, "core profile must keep diagnostics off stdout")
require("Flower" in bootstrap and "fow_" in bootstrap, "installed bootstrap resource must be reachable")
for optional_distribution in ("lmstudio-agent-runtime", "runtime-llama"):
    try:
        metadata.distribution(optional_distribution)
    except metadata.PackageNotFoundError:
        pass
    else:
        raise RuntimeError("optional inference dependency must not be installed: " + optional_distribution)
private_paths = ["/build", "/src", "/app", "/authorities", "/qualification", "/work", "/config"]
require(not any(Path(path).exists() for path in private_paths), "image contains source or private development inputs")
require(not any(part in {"tests", "authorities", "qualification"} for item in distribution.files or [] for part in item.parts), "installed package contains private inputs")
print(json.dumps({"version": distribution.version, "package_path": str(package), "uid": os.getuid(), "gid": os.getgid(),
                  "resources": ["standalone.yaml", "agent-bootstrap.md"], "inference": "absent", "providers": "disabled"}))
'''

PROFILE_AUDIT = r'''
import json
from pathlib import Path
import yaml

root = Path("/data/profiles/default")
for name in ("flower.yaml", "ledger.sqlite3", "ledger.sqlite3.runtime.lock"):
    if not (root / name).is_file():
        raise RuntimeError("canonical persisted profile file missing: " + name)
for name in ("imports", "logs"):
    if not (root / name).is_dir():
        raise RuntimeError("canonical persisted profile directory missing: " + name)
config = yaml.safe_load((root / "flower.yaml").read_text(encoding="utf-8"))
if config["runtime"]["database_path"] != str(root / "ledger.sqlite3") or config["runtime"]["import_root"] != str(root / "imports"):
    raise RuntimeError("profile storage escaped canonical /data root")
if config["logging"]["logs_path"] != str(root / "logs") or config["model"]["enabled"] is not False or config["providers"] != {}:
    raise RuntimeError("persisted profile changed the core configuration")
print(json.dumps({"root": str(root), "files": sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())}))
'''


class Engine:
    def __init__(self, command: str):
        executable = shutil.which(command)
        if not executable:
            raise RuntimeError(f"Container engine executable is unavailable: {command}")
        self.command = str(Path(executable).resolve())

    def execute(self, arguments: list[str], *, timeout: int = 45) -> str:
        result = subprocess.run([self.command, *arguments], capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError(f"Container engine operation failed ({result.returncode}): {' '.join(arguments[:3])}\n{result.stderr.strip()}")
        return result.stdout.strip()


class OwnedContainers:
    """No caller-supplied state mounts; cleanup requires an exact generated owner label."""

    def __init__(self, engine: Engine, image: str):
        self.engine = engine
        self.image = image
        self.owner = uuid.uuid4().hex
        self.volume = f"flower-smoke-{self.owner}"
        self.volume_attempted = False
        self.containers: list[str] = []

    def _inspect(self, kind: str, name: str) -> dict:
        records = json.loads(self.engine.execute([kind, "inspect", name]))
        if not isinstance(records, list) or len(records) != 1:
            raise RuntimeError(f"Cannot prove {kind} identity: {name}")
        record = records[0]
        labels = record.get("Labels") if kind == "volume" else record.get("Config", {}).get("Labels")
        if (labels or {}).get(LABEL) != self.owner:
            raise RuntimeError(f"Refusing to use or remove an unowned {kind}: {name}")
        return record

    def prepare(self) -> dict:
        self.engine.execute(["info", "--format", "json"])
        images = json.loads(self.engine.execute(["image", "inspect", self.image]))
        if not isinstance(images, list) or len(images) != 1:
            raise RuntimeError("Cannot identify the already-built image")
        image = images[0]
        config = image["Config"]
        if config.get("Cmd") != SERVER_COMMAND or config.get("Entrypoint"):
            raise RuntimeError("Image must launch the canonical Flower stdio command without an entrypoint override")
        self.volume_attempted = True
        name = self.engine.execute(["volume", "create", "--label", f"{LABEL}={self.owner}", self.volume])
        if name != self.volume:
            raise RuntimeError("Engine did not return the generated volume identity")
        self._inspect("volume", self.volume)
        return {"image_id": image.get("Id"), "architecture": image.get("Architecture"), "os": image.get("Os"), "command": config["Cmd"]}

    def run_arguments(self, command: list[str] | None = None) -> tuple[str, list[str]]:
        name = f"flower-smoke-{self.owner}-{len(self.containers) + 1}"
        self.containers.append(name)
        arguments = ["run", "-i", "--pull=never", "--name", name, "--label", f"{LABEL}={self.owner}",
                     "--network", "none", "--mount", f"type=volume,src={self.volume},dst=/data", self.image]
        return name, arguments + (command or [])

    def wait(self, name: str):
        result = self.engine.execute(["container", "wait", name], timeout=20)
        if result != "0":
            raise RuntimeError(f"Container did not exit successfully: {name}, exit={result}")

    def remove_container(self, name: str):
        names = self.engine.execute(["container", "ls", "--all", "--filter", f"label={LABEL}={self.owner}", "--format", "{{.Names}}"])
        if name in names.splitlines():
            self._inspect("container", name)
            self.engine.execute(["container", "rm", "--force", name])

    def remove_after(self, name: str, failure: BaseException | None):
        try:
            self.remove_container(name)
        except Exception as cleanup_error:
            if failure is not None:
                raise RuntimeError(f"{failure}; Container cleanup failed: {cleanup_error}") from failure
            raise

    def audit(self, script: str) -> dict:
        name, arguments = self.run_arguments(["python", "-c", script])
        failure = None
        try:
            result = json.loads(self.engine.execute(arguments))
            self.wait(name)
            return result
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self.remove_after(name, failure)

    def close(self):
        failures = []
        for name in reversed(self.containers):
            try:
                self.remove_container(name)
            except Exception as exc:
                failures.append(str(exc))
        if self.volume_attempted:
            try:
                names = self.engine.execute(["volume", "ls", "--format", "{{.Name}}"])
                if self.volume in names.splitlines():
                    self._inspect("volume", self.volume)
                    self.engine.execute(["volume", "rm", self.volume])
                self.volume_attempted = False
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("Owned qualification resource cleanup failed: " + "; ".join(failures))


async def qualify(engine: Engine, image: str) -> dict:
    resources = OwnedContainers(engine, image)
    failure = None
    try:
        image_metadata = resources.prepare()
        installed = resources.audit(IMAGE_AUDIT)
        with tempfile.TemporaryDirectory(prefix="flower-container-client-") as directory:
            @asynccontextmanager
            async def session_factory():
                name, arguments = resources.run_arguments()
                failure = None
                parameters = StdioServerParameters(command=engine.command, args=arguments, cwd=directory,
                    env={key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "FLOWER_HOME"}})
                try:
                    async with public_session(parameters, strict=True) as session:
                        yield session
                    await asyncio.to_thread(resources.wait, name)
                except BaseException as exc:
                    failure = exc
                    raise
                finally:
                    await asyncio.to_thread(resources.remove_after, name, failure)

            public = await asyncio.wait_for(qualify_sessions(session_factory), timeout=120)
        profile = resources.audit(PROFILE_AUDIT)
        result = {**public, "image": image_metadata, "installed": installed, "profile": profile,
                  "container_recreation": "passed", "network": "none",
                  "scope": "Synthetic built-image public mechanics on the reported platform; not Glama deployment, model usability or acceptance"}
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            resources.close()
        except Exception as cleanup_error:
            if failure is not None:
                raise RuntimeError(f"{failure}; {cleanup_error}") from failure
            raise
    return {**result, "cleanup": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, help="Docker or Podman executable; its daemon must already be running")
    parser.add_argument("--image", required=True, help="already-built local image; no registry publication or implicit pull")
    parser.add_argument("--output", type=Path, help="optional retained image and public MCP receipts")
    args = parser.parse_args()
    try:
        result = asyncio.run(qualify(Engine(args.engine), args.image))
    except Exception as exc:
        result = {"status": "failed", "reason": str(exc), "scope": "Container qualification did not pass"}
        exit_status = 1
    else:
        exit_status = 0
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "receipts"}))
    raise SystemExit(exit_status)


if __name__ == "__main__":
    main()
