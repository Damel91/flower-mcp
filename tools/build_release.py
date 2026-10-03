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
ASSET_SOURCES = {"install.sh": "tools/install.sh", "install.ps1": "tools/install.ps1",
                 "install_flower.py": "tools/install_flower.py",
                 "BOOTSTRAP.md": BOOTSTRAP_RESOURCE}


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
    return project


def asset_names(project: dict) -> set[str]:
    normalized_name = re.sub(r"[-_.]+", "_", project["name"])
    version = project["version"]
    return {f"{normalized_name}-{version}-py3-none-any.whl",
            f"{normalized_name}-{version}.tar.gz"} | set(ASSET_SOURCES)


def check_inventory(dist: Path, project: dict, *, require_copied_assets: bool = True) -> None:
    expected = asset_names(project)
    actual = {path.name for path in dist.iterdir()}
    required = expected if require_copied_assets else expected - set(ASSET_SOURCES)
    if actual - expected - {"SHA256SUMS"} or required - actual:
        raise ValueError("dist must contain exactly the current wheel, sdist, installers, BOOTSTRAP.md and optional SHA256SUMS")
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


def check_packages(root: Path, files: list[Path], project: dict) -> None:
    wheel = next(path for path in files if path.suffix == ".whl")
    with zipfile.ZipFile(wheel) as archive:
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
        presentation = sorted(
            path.relative_to(root).as_posix()
            for path in (root / "docs/presentation").rglob("*")
            if path.is_file() and path.suffix in PRESENTATION_SUFFIXES
        )
        for name in ("PKG-INFO", "LICENSE", "NOTICE", *ASSET_SOURCES.values(), *presentation):
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
            "Assets: Python wheel, source distribution, install.sh, install.ps1, install_flower.py, BOOTSTRAP.md and SHA256SUMS.\n"
            "The Python distribution remains flow-of-work-mcp; the primary command is flower-mcp.\n\n"
            "This release includes the version-pinned Windows PowerShell launcher and the bilingual offline presentation. "
            "It remains in testing; this installation/documentation update does not change the public MCP interface.\n\n"
            "Install this release and choose your coding client in the terminal:\n\n"
            f"```sh\ncurl -fsSL https://github.com/Damel91/flower-mcp/releases/download/v{project['version']}/install.sh | bash\n```\n\n"
            "The installer prepares the Python environment and checks downloaded backend and wheel hashes.\n"
            "Windows: obtain the included install.ps1 from this release's assets. "
            "Run the download and execution commands separately, inspecting the script before execution:\n\n"
            f"```powershell\nInvoke-WebRequest -UseBasicParsing -Uri \"https://github.com/Damel91/flower-mcp/releases/download/v{project['version']}/install.ps1\" -OutFile \".\\install.ps1\"\n```\n\n"
            f"```powershell\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 -Version '{project['version']}' -Platform codex\n```\n\n"
            "Use -Platform claude-code, -Platform cursor or -NoRegister instead. The execution-policy setting applies only to this process.\n"
            "Windows requires PowerShell 5.1 or newer; see the installation guide for prerequisites. "
            "Windows installation and coding-client usability require separate platform verification.\n"
            f"Full version notes: https://github.com/Damel91/flower-mcp/blob/v{project['version']}/docs/RELEASE-NOTES-{project['version']}.md\n\n"
            "Run `flower-mcp bootstrap` and give its output to your coding agent to start a Flower-guided project.\n"
            "BOOTSTRAP.md is the same model instruction text bundled with the installed package.\n"
            "The source archive includes the bilingual presentation and its offline HTML readers under docs/presentation; "
            "extract the archive and open docs/presentation/index.html without starting a server.\n"
            "See docs/INSTALLATION.md in the tagged source for manual installation and configuration.\n",
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
