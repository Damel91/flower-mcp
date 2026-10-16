#!/usr/bin/env python3
"""Build the versioned packages, installers and checksums for a public release."""
from __future__ import annotations

import argparse
import ast
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile


# Unmodified https://www.apache.org/licenses/LICENSE-2.0.txt, including LF bytes.
APACHE_LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
STABLE_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
INSTALLERS = {"install.sh", "install.ps1", "install_flower.py"}
BOOTSTRAP_RESOURCE = "src/flow_of_work_mcp/resources/agent-bootstrap.md"
PRESENTATION_SUFFIXES = {".md", ".html", ".json", ".css", ".js", ".png", ".txt", ".py"}
CONTAINER_SOURCES = {"Dockerfile", ".dockerignore", "glama.json"}
RUNTIME_URL = (
    "https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/"
    "runtime_llama-0.5.0-py3-none-any.whl#sha256="
    "dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13"
)
ASSET_SOURCES = {"install.sh": "tools/install.sh", "install.ps1": "tools/install.ps1",
                 "install_flower.py": "tools/install_flower.py",
                 "BOOTSTRAP.md": BOOTSTRAP_RESOURCE}


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def is_runtime_requirement(requirement: str) -> bool:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return match is not None and normalized_name(match[1]) == "runtime-llama"


def exact_runtime_requirement(requirement: str, *, inference_marker: bool = False) -> bool:
    match = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*([^\s;]+)\s*(?:;\s*(.+))?\s*", requirement)
    if match is None or normalized_name(match[1]) != "runtime-llama" or match[2] != RUNTIME_URL:
        return False
    marker = match[3]
    if not inference_marker:
        return marker is None
    if marker is None:
        return False
    marker = marker.strip()
    while marker.startswith("(") and marker.endswith(")"):
        marker = marker[1:-1].strip()
    return re.fullmatch(r'''(?:extra\s*==\s*(["'])inference\1|(["'])inference\2\s*==\s*extra)''', marker) is not None


def forbidden_runtime_member(name: str) -> bool:
    return name.lower().endswith(".whl") or any(
        normalized_name(part) == "third-party" or part.lower() in {"vendor", "_vendor"}
        or re.match(r"runtime[-_.]+llama(?:$|[-_.])", part, re.IGNORECASE)
        for part in name.replace("\\", "/").split("/")
    )


def validate_project(root: Path, requested_version: str | None = None) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not isinstance(version, str) or STABLE_VERSION.fullmatch(version) is None:
        raise ValueError("public releases require a stable MAJOR.MINOR.PATCH version in pyproject.toml")
    if requested_version is not None and (
        STABLE_VERSION.fullmatch(requested_version) is None or requested_version != version
    ):
        raise ValueError("release version must be MAJOR.MINOR.PATCH without v and equal pyproject.toml")
    if project.get("license") != "Apache-2.0" or sorted(project.get("license-files", [])) != ["LICENSE", "NOTICE"]:
        raise ValueError("project must declare Apache-2.0 and exactly LICENSE and NOTICE")
    if hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest() != APACHE_LICENSE_SHA256:
        raise ValueError("LICENSE differs from the official Apache License 2.0 text")
    notice = (root / "NOTICE").read_text(encoding="utf-8")
    if "Flower MCP" not in notice or "Davide Mele" not in notice:
        raise ValueError("NOTICE must retain the Flower MCP and Davide Mele attribution")
    frontend = (root / "tools/install.sh").read_text(encoding="utf-8")
    defaults = re.findall(r'^FLOWER_VERSION=([\'"])([0-9.]+)\1(?:[ \t]+#.*)?$', frontend, flags=re.MULTILINE)
    if len(defaults) != 1 or defaults[0][1] != version:
        raise ValueError("shell installer default release version differs from pyproject.toml")
    powershell = (root / "tools/install.ps1").read_text(encoding="utf-8")
    defaults = re.findall(r"^\s*\[string\]\$Version = '([0-9.]+)',\s*$", powershell, flags=re.MULTILINE)
    if len(defaults) != 1 or defaults[0] != version:
        raise ValueError("PowerShell installer default release version differs from pyproject.toml")
    backend = ast.parse((root / "tools/install_flower.py").read_text(encoding="utf-8"))
    defaults = [node.value for node in backend.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "DEFAULT_VERSION" for target in node.targets)]
    if len(defaults) != 1 or not isinstance(defaults[0], ast.Constant) or defaults[0].value != version:
        raise ValueError("Python installer default release version differs from pyproject.toml")
    extras = project.get("optional-dependencies", {})
    inference = extras.get("inference", [])
    if len(inference) != 1 or not exact_runtime_requirement(inference[0]):
        raise ValueError("inference extra must name only the exact public runtime URL and SHA-256")
    if any(is_runtime_requirement(item) for item in project.get("dependencies", [])) or any(
        is_runtime_requirement(item) for extra, requirements in extras.items() if extra != "inference"
        for item in requirements
    ):
        raise ValueError("runtime dependency must remain confined to the inference extra")
    return project


def asset_names(project: dict) -> set[str]:
    normalized_name = re.sub(r"[-_.]+", "_", project["name"])
    version = project["version"]
    return {f"{normalized_name}-{version}-py3-none-any.whl",
            f"{normalized_name}-{version}.tar.gz"} | set(ASSET_SOURCES)


def release_documentation(project: dict) -> set[str]:
    return {"docs/INSTALLATION.md", "docs/UPGRADING.md", "docs/glama-build-spec.example.json",
            f"docs/RELEASE-NOTES-{project['version']}.md"}


def check_inventory(dist: Path, project: dict, *, require_copied_assets: bool = True) -> None:
    expected = asset_names(project)
    actual = {path.name for path in dist.iterdir()}
    required = expected if require_copied_assets else expected - set(ASSET_SOURCES)
    if actual - expected - {"SHA256SUMS"} or required - actual:
        raise ValueError("dist must contain exactly the Flower wheel, sdist, three installers, BOOTSTRAP.md and optional SHA256SUMS")
    if any(path.is_symlink() or not path.is_file() for path in dist.iterdir()):
        raise ValueError("release assets must be regular files")


def release_assets(root: Path, dist: Path, project: dict) -> list[Path]:
    check_inventory(dist, project)
    files = [dist / name for name in sorted(asset_names(project))]
    for name, source_path in ASSET_SOURCES.items():
        if (dist / name).read_bytes() != (root / source_path).read_bytes():
            subject = "installer" if name in INSTALLERS else name
            raise ValueError(f"release {subject} differs from the checked source")
    return files


def check_metadata(payload: bytes, project: dict) -> None:
    metadata = BytesParser().parsebytes(payload)
    if metadata["Name"] != project["name"] or metadata["Version"] != project["version"]:
        raise ValueError("built package identity differs from pyproject.toml")
    if metadata["License-Expression"] != "Apache-2.0" or sorted(metadata.get_all("License-File") or []) != ["LICENSE", "NOTICE"]:
        raise ValueError("built package license metadata differs from the public license")
    if metadata["Requires-Python"] != project["requires-python"]:
        raise ValueError("built Python requirement differs from pyproject.toml")
    requirements = metadata.get_all("Requires-Dist") or []
    runtime_requirements = [item for item in requirements if is_runtime_requirement(item)]
    advertised_extras = [normalized_name(extra) for extra in metadata.get_all("Provides-Extra") or []]
    if advertised_extras.count("inference") != 1 or len(runtime_requirements) != 1 or not exact_runtime_requirement(runtime_requirements[0], inference_marker=True):
        raise ValueError("built package must keep the exact runtime dependency confined to the inference extra")


def check_packages(root: Path, files: list[Path], project: dict) -> None:
    normalized_name = re.sub(r"[-_.]+", "_", project["name"])
    wheel_name = f"{normalized_name}-{project['version']}-py3-none-any.whl"
    wheel = next(path for path in files if path.name == wheel_name)
    with zipfile.ZipFile(wheel) as archive:
        if any(forbidden_runtime_member(name) for name in archive.namelist()):
            raise ValueError("Flower core wheel must not contain the optional runtime artifact or package")
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain one package metadata file")
        metadata_name = metadata_names[0]
        check_metadata(archive.read(metadata_name), project)
        distinfo = metadata_name.rsplit("/", 1)[0]
        for name in ("LICENSE", "NOTICE"):
            if archive.read(f"{distinfo}/licenses/{name}") != (root / name).read_bytes():
                raise ValueError(f"wheel {name} differs from the public source")
        if archive.read(BOOTSTRAP_RESOURCE.removeprefix("src/")) != (root / BOOTSTRAP_RESOURCE).read_bytes():
            raise ValueError("wheel agent bootstrap differs from the canonical source")
    sdist = next(path for path in files if path.name.endswith(".tar.gz"))
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        roots = {member.name.split("/", 1)[0] for member in members}
        if len(roots) != 1:
            raise ValueError("source distribution must have one root")
        prefix = roots.pop() + "/"
        if any(forbidden_runtime_member(member.name.removeprefix(prefix)) for member in members):
            raise ValueError("Flower source distribution must not contain the optional runtime artifact or package")
        presentation = sorted(
            path.relative_to(root).as_posix()
            for path in (root / "docs/presentation").rglob("*")
            if path.is_file() and path.suffix in PRESENTATION_SUFFIXES
        )
        for name in ("PKG-INFO", "LICENSE", "NOTICE", *ASSET_SOURCES.values(),
                     *sorted(CONTAINER_SOURCES),
                     *sorted(release_documentation(project)), *presentation):
            try:
                member = archive.getmember(prefix + name)
            except KeyError as exc:
                raise ValueError(f"source distribution omits required source {name}") from exc
            if not member.isfile():
                raise ValueError("source distribution metadata, licenses and copied asset sources must be regular files")
            payload = archive.extractfile(member).read()
            if name == "PKG-INFO":
                check_metadata(payload, project)
            elif payload != (root / name).read_bytes():
                raise ValueError(f"source distribution {name} differs from the public source")


def prepare(root: Path, dist: Path, requested_version: str | None = None,
            *, verify_checksums: bool = False, notes: Path | None = None) -> dict:
    root, dist = root.resolve(), dist.resolve()
    project = validate_project(root, requested_version)
    if not verify_checksums:
        check_inventory(dist, project, require_copied_assets=False)
        for source_path in ASSET_SOURCES.values():
            source = root / source_path
            if source.is_symlink() or not source.is_file():
                raise ValueError("copied release asset source must be a regular file")
        for name, source_path in ASSET_SOURCES.items():
            shutil.copyfile(root / source_path, dist / name)
    files = release_assets(root, dist, project)
    check_packages(root, files, project)
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files)
    checksum_path = dist / "SHA256SUMS"
    if verify_checksums:
        if not checksum_path.is_file() or checksum_path.read_text(encoding="utf-8") != checksums:
            raise ValueError("SHA256SUMS does not match the exact release asset inventory and bytes")
    else:
        checksum_path.write_text(checksums, encoding="utf-8")
    if notes is not None:
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(
            f"Flower MCP {project['version']}\n\n"
            "Python 3.11 or newer. Apache-2.0; LICENSE and NOTICE are included inside both packages.\n\n"
            "Seven versioned assets: Flower Python wheel, source distribution, "
            "install.sh, install.ps1, install_flower.py, BOOTSTRAP.md and SHA256SUMS.\n"
            "The Python distribution remains flow-of-work-mcp; the primary command is flower-mcp.\n\n"
            "The immutable published Flower 0.4.1 release and its eight historical assets, including runtime 0.4.0, remain unchanged. "
            f"This build uses version {project['version']} and does not replace those historical assets. "
            "Its inference extra instead acquires the independently released public runtime-llama 0.5.0 wheel. "
            "The Flower build and core installers do not download inference.\n\n"
            "Compared with published Flower 0.5.1, this patch corrects repeated authority hydration and "
            "shared-predecessor PVP computation in complete project recovery. "
            "Reuse is confined to one coherent read or projection invocation; writes and fresh requests receive fresh authority. "
            "Complete snapshots, PVP fingerprints, gates, evidence provenance and the existing deadlines are retained. "
            "On the declared isolated test fixture, complete public recovery took approximately 1.7 seconds; "
            "the independent Noxi adapter took approximately 2 seconds with its original 10-second deadline. "
            "These are bounded measurements, not a universal latency guarantee or a production deployment claim. "
            "The same 37 tools and 445 input parameters retain their callable contracts. "
            "The tool-definition improvements informed by Glama feedback remain from 0.5.1; "
            "no new Glama score or account build is claimed for 0.5.2. "
            "Published 0.5.0 and 0.5.1 assets remain immutable.\n\n"
            f"Upgrading published 0.5.1 to this {project['version']} build requires no new SQLite migration: "
            "schema 55 and the same local ledger are retained. "
            f"For this version's complete upgrade commands, read [the versioned release guide](https://github.com/Damel91/flower-mcp/blob/v{project['version']}/docs/RELEASE-NOTES-{project['version']}.md).\n\n"
            "This build includes explicit PVP capability discovery and deferred-only verification declarations, "
            "canonical verbose provider receipts, coherent author receipts and immutable replay, "
            "read-only external-work recovery, provider delta synchronization without START, "
            "and bounded provider RPC deadlines with exact UNKNOWN recovery and cancellation cleanup. "
            "Glama uv startup uses the core dependency path; hosted Glama qualification remains separate. "
            "Managed-writer observation and its deferred U6 integration are excluded.\n\n"
            "This build retains complete SRS rejection diagnostics for initial imports and baseline revisions when several findings share a code. "
            "Rejected documents remain rejected; all detailed findings and anchors are retained, without materializing baseline authority. "
            "It retains durable architecture authority, explicit executor selection, negotiated PVP handoff and continuous external-agent recovery from 0.4.0. "
            "The existing 37 public MCP tool names are retained. "
            "Relative to published 0.4.1, the fow_packet_advance schema adds optional mode=sync_only alongside the default mode=advance; "
            "author receipts and recovery responses also expose the corrected current-authority and replay information. "
            f"Upgrading published 0.4.1 to this {project['version']} build requires no new SQLite migration: "
            "schema 55 and the same local ledger are retained. "
            "Upgrading an older 0.3.1 installation still applies the existing additive SQLite migrations 52 to 55 on first server start. "
            "Use the planned, backed-up upgrade route for installer-owned environments to retain the existing profile and client registration. "
            "Optional runtime-llama is independently upgraded only when explicitly installed; core and host execution need no model endpoint. "
            "Real paired provider qualification and human acceptance remain separate. Flower remains in testing.\n\n"
            "Install the checked wheel in a new isolated environment. "
            "For an existing installer-owned environment, use the reviewed upgrade route below so its ownership receipt remains coherent:\n\n"
            f"```sh\npython -m pip install ./flow_of_work_mcp-{project['version']}-py3-none-any.whl\n```\n\n"
            "For optional internal inference in that manual environment, install the extra from this same checked wheel, "
            "then configure an authorized endpoint. In an installer-owned environment, complete the normal core upgrade first "
            "and use the exact Flower wheel and SHA256 recorded by its installation receipt; "
            "a same-version source checkout or rebuilt wheel is not a substitute:\n\n"
            f"```sh\npython -m pip install './flow_of_work_mcp-{project['version']}-py3-none-any.whl[inference]'\n```\n\n"
            f"Pinned upstream dependency: `runtime-llama @ {RUNTIME_URL}`. "
            "Its SHA-256 belongs to llama-runtime's release, not Flower's SHA256SUMS. "
            "For verified offline acquisition and explicit runtime upgrades, see docs/INFERENCE.md from this source. "
            "See docs/ADVANCED-CONFIGURATION.md for supported semantic roles, authorized provider routes and portable association receipts.\n\n"
            "The version-pinned commands below require the corresponding published assets. "
            "During release preparation, use the checked local wheel in a new environment, or the "
            "[immutable published v0.4.1 release](https://github.com/Damel91/flower-mcp/releases/tag/v0.4.1). "
            "The installer chooses your coding client in the terminal:\n\n"
            f"```sh\ncurl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v{project['version']}/install.sh | bash\n```\n\n"
            "The installer prepares the Python environment and checks downloaded backend and wheel hashes.\n"
            "Already installed? Stop all Flower processes and clients sharing its environment before updating. "
            "Use the same environment, profile and profile root. An owned upgrade defaults to no registration, "
            "requires the existing profile, and creates a consistent SQLite backup plus the exact profile YAML before package changes.\n\n"
            f"```sh\ncurl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v{project['version']}/install.sh | bash -s -- --upgrade --dry-run\n```\n\n"
            "Inspect the returned plan, then repeat without --dry-run to perform the upgrade. "
            "Supply the original --venv, --profile and --profile-root options for a custom installation. "
            "Do not pass --platform or --client-config during an upgrade. "
            "The installer does not stop clients, restore data automatically or promise atomic pip rollback. "
            f"See [safe upgrades and manual installations](https://github.com/Damel91/flower-mcp/blob/v{project['version']}/docs/UPGRADING.md).\n\n"
            "The ordinary installer installs only Flower core. Use the explicit wheel-extra command above "
            "for optional inference; core and host execution need no model endpoint.\n\n"
            "Windows: obtain the version-pinned Windows PowerShell launcher, install.ps1, from the matching version's published assets. "
            "Run the download and execution commands separately, inspecting the script before execution:\n\n"
            f"```powershell\nInvoke-WebRequest -UseBasicParsing -Uri \"https://github.com/Damel91/flower-mcp/releases/download/v{project['version']}/install.ps1\" -OutFile \".\\install.ps1\"\n```\n\n"
            f"```powershell\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 -Version '{project['version']}' -Platform codex\n```\n\n"
            "Use -Platform claude-code, -Platform cursor, -Platform antigravity, -Platform gemini-cli or -NoRegister instead. The execution-policy setting applies only to this process.\n"
            "For an existing owned installation, use -Upgrade -DryRun without -Platform, inspect the plan, then repeat without -DryRun. "
            "Keep the original -Venv, -Profile and -ProfileRoot values.\n"
            "Windows requires PowerShell 5.1 or newer; see the installation guide for prerequisites. "
            "Windows installation and coding-client usability require separate platform verification.\n"
            f"Full version notes: https://github.com/Damel91/flower-mcp/blob/v{project['version']}/docs/RELEASE-NOTES-{project['version']}.md\n\n"
            "Run `flower-mcp bootstrap` and give its output to your coding agent to start a Flower-guided project.\n"
            "BOOTSTRAP.md is the same model instruction text bundled with the installed package.\n"
            "The source archive includes the bilingual presentation and its offline HTML readers under docs/presentation; "
            "extract the archive and open docs/presentation/index.html without starting a server.\n"
            "See docs/INSTALLATION.md in this source for current manual installation and configuration.\n",
            encoding="utf-8",
        )
    return {"version": project["version"], "assets": [path.name for path in files] + ["SHA256SUMS"]}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", help="Stable MAJOR.MINOR.PATCH, exactly matching pyproject.toml")
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--check-version", action="store_true", help="Check metadata only; do not build")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing assets and checksums without rebuilding")
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args(argv)
    project = validate_project(args.root, args.version)
    if args.check_version:
        print(json.dumps({"version": project["version"]}, indent=2))
        return
    if not args.verify_only:
        if args.output.exists() and any(args.output.iterdir()):
            parser.error("build output must be a fresh empty directory")
        subprocess.run([sys.executable, "-m", "build", "--outdir", str(args.output.resolve())],
                       cwd=args.root, check=True)
    print(json.dumps(prepare(args.root, args.output, args.version,
                             verify_checksums=args.verify_only, notes=args.notes), indent=2))


if __name__ == "__main__":
    main()
