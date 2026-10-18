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
    return {"docs/INSTALLATION.md", "docs/UPGRADING.md", "docs/NATIVE-PROJECT-DELETION.md",
            "docs/LENS-CATALOG.md",
            "docs/INFERENCE.md", "docs/ADVANCED-CONFIGURATION.md", "docs/glama-build-spec.example.json",
            f"docs/RELEASE-NOTES-{project['version']}.md"}


def release_notes(root: Path, project: dict) -> bytes:
    """Use the checked versioned guide as the sole release-note authority."""
    source = root / "docs" / f"RELEASE-NOTES-{project['version']}.md"
    if source.is_symlink() or not source.is_file():
        raise ValueError("versioned release notes must be a regular file")
    payload = source.read_bytes()
    lines = payload.decode("utf-8").splitlines()
    if not lines or lines[0] != f"# Flower MCP {project['version']}" or not any(
        line.strip() for line in lines[1:]
    ):
        raise ValueError("versioned release notes must name the exact version and contain its reviewed guidance")
    # A GitHub Release body has a different relative-link base from docs/. Keep
    # reviewed prose intact while binding sibling guide links to this exact tag.
    def guide_link(match: re.Match) -> str:
        name, fragment = match.groups()
        target = root / "docs" / name
        if target.is_symlink() or not target.is_file():
            raise ValueError("versioned release notes reference a missing regular guide")
        return f"](https://github.com/Damel91/flower-mcp/blob/v{project['version']}/docs/{name}{fragment or ''})"

    text = re.sub(r"\]\(([A-Za-z0-9][A-Za-z0-9_.-]*\.md)(#[^\s)]*)?\)", guide_link, payload.decode("utf-8"))
    return text.encode("utf-8")


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
    note_payload = release_notes(root, project)
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
        notes.write_bytes(note_payload)
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
