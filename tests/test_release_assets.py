"""Release boundary regressions; stdlib only, without installing the server."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flower_build_release", SOURCE / "tools/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="flower-release-assets-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.dist = Path(self.temporary.name) / "dist"
        self.root.mkdir()
        self.dist.mkdir()
        self.presentation = {
            path.relative_to(SOURCE).as_posix()
            for path in (SOURCE / "docs/presentation").rglob("*")
            if path.is_file() and path.suffix in release.PRESENTATION_SUFFIXES
        }
        sources = {"pyproject.toml", "LICENSE", "NOTICE", *release.ASSET_SOURCES.values(),
                   *release.CONTAINER_SOURCES, *release.THIRD_PARTY_SOURCES, *self.presentation}
        for relative in sources:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
        self.project = release.validate_project(self.root)
        self.packages()

    def packages(self, *, omit: str | None = None, replace: dict[str, bytes] | None = None,
                 nonregular: str | None = None):
        """Write minimal package fixtures at the release metadata/asset seam."""
        name = self.project["name"].replace("-", "_")
        version = self.project["version"]
        metadata = (
            "Metadata-Version: 2.4\n"
            f"Name: {self.project['name']}\nVersion: {version}\n"
            "License-Expression: Apache-2.0\nLicense-File: LICENSE\nLicense-File: NOTICE\n"
            f"Requires-Python: {self.project['requires-python']}\n"
            f'Requires-Dist: runtime-llama=={release.RUNTIME_VERSION}; extra == "inference"\n\n'
        ).encode()
        distinfo = f"{name}-{version}.dist-info"
        with zipfile.ZipFile(self.dist / f"{name}-{version}-py3-none-any.whl", "w") as archive:
            archive.writestr(f"{distinfo}/METADATA", metadata)
            for relative in ("LICENSE", "NOTICE"):
                archive.writestr(f"{distinfo}/licenses/{relative}", (self.root / relative).read_bytes())
            archive.writestr(release.BOOTSTRAP_RESOURCE.removeprefix("src/"),
                             (self.root / release.BOOTSTRAP_RESOURCE).read_bytes())
        payloads = {relative: (self.root / relative).read_bytes()
                    for relative in ("LICENSE", "NOTICE", *release.ASSET_SOURCES.values(),
                                     *sorted(release.CONTAINER_SOURCES), *sorted(release.THIRD_PARTY_SOURCES),
                                     *sorted(self.presentation))}
        payloads["PKG-INFO"] = metadata
        if replace:
            payloads.update(replace)
        if omit:
            payloads.pop(omit)
        with tarfile.open(self.dist / f"{name}-{version}.tar.gz", "w:gz") as archive:
            for relative, payload in payloads.items():
                member = tarfile.TarInfo(f"{name}-{version}/{relative}")
                if relative == nonregular:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "unexpected.ps1"
                    archive.addfile(member)
                else:
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))

    def test_checked_sources_share_the_release_version(self):
        self.assertEqual(release.validate_project(SOURCE)["version"], self.project["version"])

    def test_operator_screenshots_are_not_selected_for_source_distribution(self):
        directives = (SOURCE / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
        self.assertIn("include assets/flower-mcp-logo.png", directives)
        self.assertNotIn("recursive-include assets *.png", directives)
        self.assertIn("/assets/Screenshot*.png", (SOURCE / ".gitignore").read_text(encoding="utf-8"))

    def test_powershell_default_version_mismatch_blocks_build(self):
        script = self.root / "tools/install.ps1"
        content = script.read_text(encoding="utf-8")
        content = content.replace(f"[string]$Version = '{self.project['version']}',",
                                  "[string]$Version = '99.0.0',", 1)
        script.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PowerShell installer default release version"):
            release.validate_project(self.root)

    def test_duplicate_powershell_default_is_rejected(self):
        script = self.root / "tools/install.ps1"
        with script.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[string]$Version = '{self.project['version']}',\n")
        with self.assertRaisesRegex(ValueError, "PowerShell installer default release version"):
            release.validate_project(self.root)

    def test_prepare_copies_powershell_and_runtime_and_checks_exact_eight_asset_inventory(self):
        notes = self.root / "release-notes.md"
        result = release.prepare(self.root, self.dist, notes=notes)
        self.assertEqual(len(result["assets"]), 8)
        self.assertEqual(set(result["assets"]), {path.name for path in self.dist.iterdir()})
        self.assertEqual((self.dist / "install.ps1").read_bytes(),
                         (self.root / "tools/install.ps1").read_bytes())
        digest = hashlib.sha256((self.dist / "install.ps1").read_bytes()).hexdigest()
        self.assertIn(f"{digest}  install.ps1\n", (self.dist / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertEqual(release.prepare(self.root, self.dist, verify_checksums=True), result)
        text = notes.read_text(encoding="utf-8")
        self.assertIn("install.ps1", text)
        self.assertIn("version-pinned Windows PowerShell launcher", text)
        self.assertIn("runtime-llama", text)
        self.assertEqual((self.dist / release.RUNTIME_WHEEL).read_bytes(),
                         (self.root / release.THIRD_PARTY_ROOT / release.RUNTIME_WHEEL).read_bytes())
        self.assertIn(f"{release.RUNTIME_SHA256}  {release.RUNTIME_WHEEL}\n",
                      (self.dist / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertIn(f"releases/download/v{self.project['version']}/install.ps1", text)
        self.assertIn(
            "```powershell\npowershell.exe -NoProfile -ExecutionPolicy Bypass "
            f"-File .\\install.ps1 -Version '{self.project['version']}' -Platform codex\n```",
            text,
        )
        self.assertIn("-NoRegister", text)
        self.assertNotIn("releases/download/v0.1.0/install.ps1", text)
        self.assertIn("docs/presentation/index.html", text)

    def test_source_runtime_hash_tampering_blocks_build(self):
        wheel = self.root / release.THIRD_PARTY_ROOT / release.RUNTIME_WHEEL
        with wheel.open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "delivered SHA-256"):
            release.prepare(self.root, self.dist)

    def test_missing_runtime_provenance_blocks_build(self):
        (self.root / release.THIRD_PARTY_ROOT / "provenance.json").unlink()
        with self.assertRaisesRegex(ValueError, "provenance sources must be regular files"):
            release.prepare(self.root, self.dist)

    def test_runtime_attribution_must_match_its_original_wheel(self):
        (self.root / release.THIRD_PARTY_ROOT / "llamatelemetry.LICENSE").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "attribution differs"):
            release.prepare(self.root, self.dist)

    def test_sdist_must_include_each_optional_runtime_source(self):
        for source in sorted(release.THIRD_PARTY_SOURCES):
            with self.subTest(source=source):
                self.packages(omit=source)
                with self.assertRaisesRegex(ValueError, "source distribution omits required source"):
                    release.prepare(self.root, self.dist)

    def test_package_validation_identifies_flower_when_runtime_is_listed_first(self):
        release.prepare(self.root, self.dist)
        files = release.release_assets(self.root, self.dist, self.project)
        runtime = self.dist / release.RUNTIME_WHEEL
        release.check_packages(self.root, [runtime, *(path for path in files if path != runtime)], self.project)

    def test_core_wheel_cannot_bundle_optional_runtime(self):
        name = self.project["name"].replace("-", "_")
        wheel = self.dist / f"{name}-{self.project['version']}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("third_party/runtime-llama/" + release.RUNTIME_WHEEL, b"unexpected")
        with self.assertRaisesRegex(ValueError, "core wheel must not contain"):
            release.prepare(self.root, self.dist)

    def test_altered_runtime_release_asset_blocks_verification(self):
        release.prepare(self.root, self.dist)
        (self.dist / release.RUNTIME_WHEEL).write_bytes(b"replaced")
        with self.assertRaisesRegex(ValueError, "release .* differs from the checked source"):
            release.prepare(self.root, self.dist, verify_checksums=True)

    def test_unexpected_second_runtime_wheel_blocks_inventory(self):
        (self.dist / "runtime_llama-99.0.0-py3-none-any.whl").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "dist must contain exactly"):
            release.prepare(self.root, self.dist)

    def test_sdist_must_include_the_offline_reader(self):
        self.packages(omit="docs/presentation/index.html")
        with self.assertRaisesRegex(ValueError, "source distribution omits required source docs/presentation/index.html"):
            release.prepare(self.root, self.dist)

    def test_sdist_must_include_each_container_build_source(self):
        for source in sorted(release.CONTAINER_SOURCES):
            with self.subTest(source=source):
                self.packages(omit=source)
                with self.assertRaisesRegex(ValueError, "source distribution omits required source"):
                    release.prepare(self.root, self.dist)

    def test_sdist_container_inputs_must_match_and_be_regular_files(self):
        self.packages(replace={"Dockerfile": b"FROM unexpected:latest\n"})
        with self.assertRaisesRegex(ValueError, "source distribution Dockerfile differs"):
            release.prepare(self.root, self.dist)
        self.packages(nonregular=".dockerignore")
        with self.assertRaisesRegex(ValueError, "sources must be regular files"):
            release.prepare(self.root, self.dist)

    def test_sdist_must_include_shared_reader_assets(self):
        self.packages(omit="docs/presentation/assets/reader.js")
        with self.assertRaisesRegex(ValueError, "source distribution omits required source docs/presentation/assets/reader.js"):
            release.prepare(self.root, self.dist)

    def test_sdist_reader_bytes_must_match_the_checkout(self):
        self.packages(replace={"docs/presentation/index.html": b"<!doctype html><p>altered reader</p>"})
        with self.assertRaisesRegex(ValueError, "source distribution docs/presentation/index.html differs"):
            release.prepare(self.root, self.dist)

    def test_sdist_reader_must_be_a_regular_file(self):
        self.packages(nonregular="docs/presentation/index.html")
        with self.assertRaisesRegex(ValueError, "sources must be regular files"):
            release.prepare(self.root, self.dist)

    def test_missing_powershell_asset_blocks_verification(self):
        release.prepare(self.root, self.dist)
        (self.dist / "install.ps1").unlink()
        with self.assertRaisesRegex(ValueError, "dist must contain exactly"):
            release.prepare(self.root, self.dist, verify_checksums=True)

    def test_altered_powershell_asset_blocks_verification(self):
        release.prepare(self.root, self.dist)
        with (self.dist / "install.ps1").open("ab") as stream:
            stream.write(b"\n# changed after build\n")
        with self.assertRaisesRegex(ValueError, "release installer differs"):
            release.prepare(self.root, self.dist, verify_checksums=True)

    def test_sdist_must_reach_the_powershell_source(self):
        self.packages(omit="tools/install.ps1")
        with self.assertRaisesRegex(ValueError, "source distribution omits required source tools/install.ps1"):
            release.prepare(self.root, self.dist)

    def test_sdist_powershell_source_must_match_the_checkout(self):
        self.packages(replace={"tools/install.ps1": b"# altered package source\n"})
        with self.assertRaisesRegex(ValueError, "source distribution tools/install.ps1 differs"):
            release.prepare(self.root, self.dist)

    def test_sdist_powershell_source_must_be_a_regular_file(self):
        self.packages(nonregular="tools/install.ps1")
        with self.assertRaisesRegex(ValueError, "copied asset sources must be regular files"):
            release.prepare(self.root, self.dist)

    def test_manifest_must_include_the_powershell_checksum(self):
        release.prepare(self.root, self.dist)
        manifest = self.dist / "SHA256SUMS"
        lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
        manifest.write_text("".join(line for line in lines if not line.endswith("  install.ps1\n")),
                            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256SUMS does not match"):
            release.prepare(self.root, self.dist, verify_checksums=True)


if __name__ == "__main__":
    unittest.main()
