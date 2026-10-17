"""Release boundary regressions; stdlib only, without installing the server."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import tomllib
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flower_build_release", SOURCE / "tools/build_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

# Independently lock the upstream identity; these tests must detect builder drift.
RUNTIME_URL = (
    "https://github.com/Damel91/llama-runtime/releases/download/v0.5.0/"
    "runtime_llama-0.5.0-py3-none-any.whl#sha256="
    "dc7c2e056f55f68181dd82158417e5f53e0aed8189a07acf10e59314a80f6d13"
)
RUNTIME_REQUIREMENT = f"runtime-llama @ {RUNTIME_URL}"
ASSET_SOURCES = {"install.sh": "tools/install.sh", "install.ps1": "tools/install.ps1",
                 "install_flower.py": "tools/install_flower.py",
                 "BOOTSTRAP.md": "src/flow_of_work_mcp/resources/agent-bootstrap.md"}


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
        self.project = tomllib.loads((SOURCE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.project["optional-dependencies"]["inference"] = [RUNTIME_REQUIREMENT]
        self.release_docs = release.release_documentation(self.project)
        sources = {"pyproject.toml", "LICENSE", "NOTICE", *ASSET_SOURCES.values(),
                   *release.CONTAINER_SOURCES,
                   *self.release_docs, *self.presentation}
        for relative in sources:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
        project_file = self.root / "pyproject.toml"
        project_file.write_text(re.sub(r'^inference = .*$', f'inference = ["{RUNTIME_REQUIREMENT}"]',
                                      project_file.read_text(encoding="utf-8"), flags=re.MULTILINE),
                                encoding="utf-8")
        self.packages()

    def metadata(self, requirements=None):
        if requirements is None:
            requirements = [f'{RUNTIME_REQUIREMENT}; extra == "inference"']
        return (
            "Metadata-Version: 2.4\n"
            f"Name: {self.project['name']}\nVersion: {self.project['version']}\n"
            "License-Expression: Apache-2.0\nLicense-File: LICENSE\nLicense-File: NOTICE\n"
            f"Requires-Python: {self.project['requires-python']}\n"
            "Provides-Extra: inference\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requirements) + "\n"
        ).encode()

    def packages(self, *, omit: str | None = None, replace: dict[str, bytes] | None = None,
                 nonregular: str | None = None, wheel_members: dict[str, bytes] | None = None,
                 sdist_members: dict[str, bytes] | None = None, wheel_metadata: bytes | None = None,
                 sdist_metadata: bytes | None = None):
        """Write minimal package fixtures at the release metadata/asset seam."""
        name = self.project["name"].replace("-", "_")
        version = self.project["version"]
        metadata = self.metadata()
        distinfo = f"{name}-{version}.dist-info"
        with zipfile.ZipFile(self.dist / f"{name}-{version}-py3-none-any.whl", "w") as archive:
            archive.writestr(f"{distinfo}/METADATA", wheel_metadata or metadata)
            for relative in ("LICENSE", "NOTICE"):
                archive.writestr(f"{distinfo}/licenses/{relative}", (self.root / relative).read_bytes())
            archive.writestr(release.BOOTSTRAP_RESOURCE.removeprefix("src/"),
                             (self.root / release.BOOTSTRAP_RESOURCE).read_bytes())
            for relative, payload in (wheel_members or {}).items():
                archive.writestr(relative, payload)
        payloads = {relative: (self.root / relative).read_bytes()
                    for relative in ("LICENSE", "NOTICE", *ASSET_SOURCES.values(),
                                     *sorted(release.CONTAINER_SOURCES),
                                     *sorted(self.release_docs), *sorted(self.presentation))}
        payloads["PKG-INFO"] = sdist_metadata or metadata
        payloads.update(sdist_members or {})
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

    def test_prepare_copies_installers_and_checks_exact_seven_asset_inventory(self):
        notes = self.root / "release-notes.md"
        result = release.prepare(self.root, self.dist, notes=notes)
        self.assertEqual(len(result["assets"]), 7)
        self.assertEqual(set(result["assets"]), {path.name for path in self.dist.iterdir()})
        self.assertEqual((self.dist / "install.ps1").read_bytes(),
                         (self.root / "tools/install.ps1").read_bytes())
        digest = hashlib.sha256((self.dist / "install.ps1").read_bytes()).hexdigest()
        self.assertIn(f"{digest}  install.ps1\n", (self.dist / "SHA256SUMS").read_text(encoding="utf-8"))
        self.assertEqual(release.prepare(self.root, self.dist, verify_checksums=True), result)
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        self.assertEqual(notes.read_bytes(), release.release_notes(self.root, self.project))
        self.assertIn(guide.read_text(encoding="utf-8").splitlines()[0], notes.read_text(encoding="utf-8"))
        self.assertFalse(any(path.name.startswith("runtime_llama") for path in self.dist.iterdir()))

    def test_generated_notes_bind_relative_guides_to_exact_release_tag_without_rewriting_prose(self):
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        content = (f"# Flower MCP {self.project['version']}\n\n"
                   "Keep **bounded** claims and multiline evidence.\n\n"
                   "Read [upgrade](UPGRADING.md#preservation) and [external](https://example.invalid/notes.md).\n")
        guide.write_text(content, encoding="utf-8")
        source_sha256 = hashlib.sha256(guide.read_bytes()).hexdigest()
        self.packages()
        output = self.root / "generated-notes.md"
        release.prepare(self.root, self.dist, notes=output)
        expected = content.replace(
            "](UPGRADING.md#preservation)",
            f"](https://github.com/Damel91/flower-mcp/blob/v{self.project['version']}/docs/UPGRADING.md#preservation)",
        )
        self.assertEqual(output.read_text(encoding="utf-8"), expected)
        self.assertEqual(guide.read_text(encoding="utf-8"), content)
        self.assertEqual(hashlib.sha256(guide.read_bytes()).hexdigest(), source_sha256)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), hashlib.sha256(expected.encode("utf-8")).hexdigest())
        self.assertNotEqual(hashlib.sha256(output.read_bytes()).hexdigest(), source_sha256)

    def test_generated_notes_reject_missing_relative_guide_before_asset_changes(self):
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        guide.write_text(f"# Flower MCP {self.project['version']}\n\nRead [missing](MISSING.md).\n", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in self.dist.iterdir()}
        with self.assertRaisesRegex(ValueError, "missing regular guide"):
            release.prepare(self.root, self.dist, notes=self.root / "generated-notes.md")
        self.assertEqual({path.name: path.read_bytes() for path in self.dist.iterdir()}, before)

    def test_generated_notes_preserve_reviewed_breaking_contract_and_upgrade_guidance(self):
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        content = (
            f"# Flower MCP {self.project['version']}\n\n"
            "Candidate: installed/CI/HTTPS qualification remains pending.\n\n"
            "Breaking input: prerequisite_requirement_ids replaces dependency_closure_ids.\n"
            "First milestone uses []; previous producers are distinct from current coding work.\n"
            "Correlated flow.operation-effect.v1 rejects before effect; post-commit stays unknown.\n"
            "Native project-purge is outside MCP; Windows durability is unqualified.\n"
            "Same-schema55 upgrade preserves SQLite, receipts, evidence and YAML.\n"
            "Use --upgrade --dry-run and --backup-root before pip; no atomic package rollback.\n"
            "Supported schema52→55 migration is a separate checkpoint.\n"
            "Optional runtime-llama0.5.0 is inference-only; core needs no endpoint.\n"
        ).encode("utf-8")
        guide.write_bytes(content)
        self.packages()
        output = self.root / "generated-notes.md"
        release.prepare(self.root, self.dist, notes=output)
        self.assertEqual(output.read_bytes(), content)
        self.assertNotIn(b"retain their callable contracts", output.read_bytes())
        release.prepare(self.root, self.dist, verify_checksums=True, notes=output)
        self.assertEqual(output.read_bytes(), content)

    def test_generated_notes_reject_wrong_version_or_empty_guidance_before_asset_changes(self):
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        output = self.root / "generated-notes.md"
        original_assets = {path.name: path.read_bytes() for path in self.dist.iterdir()}
        for content in ("# Flower MCP 99.0.0\n\nWrong version.\n",
                        f"# Flower MCP {self.project['version']}\n\n", ""):
            with self.subTest(content=content):
                guide.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "exact version"):
                    release.prepare(self.root, self.dist, notes=output)
                self.assertFalse(output.exists())
                self.assertEqual({path.name: path.read_bytes() for path in self.dist.iterdir()}, original_assets)

    def test_generated_notes_require_regular_versioned_authority(self):
        guide = self.root / "docs" / f"RELEASE-NOTES-{self.project['version']}.md"
        guide.unlink()
        with self.assertRaisesRegex(ValueError, "regular file"):
            release.prepare(self.root, self.dist, notes=self.root / "generated-notes.md")
        guide.mkdir()
        with self.assertRaisesRegex(ValueError, "regular file"):
            release.release_notes(self.root, self.project)
        guide.rmdir()
        target = self.root / "other-notes.md"
        target.write_text(f"# Flower MCP {self.project['version']}\n\nExternal notes.\n", encoding="utf-8")
        guide.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular file"):
            release.release_notes(self.root, self.project)

    def test_project_dependency_accepts_normalized_name_and_spacing(self):
        self.change_inference(f" Runtime.Llama@  {RUNTIME_URL} ")
        release.validate_project(self.root)

    def change_inference(self, requirement):
        path = self.root / "pyproject.toml"
        path.write_text(re.sub(r'^inference = .*$', f'inference = ["{requirement}"]',
                               path.read_text(encoding="utf-8"), flags=re.MULTILINE), encoding="utf-8")

    def test_project_rejects_wrong_public_identity_and_duplicate_dependency(self):
        for requirement in ("runtime-llama==0.4.1", RUNTIME_REQUIREMENT.replace("0.5.0", "0.4.1"),
                            RUNTIME_REQUIREMENT.replace("dc7c2", "0c7c2"),
                            RUNTIME_REQUIREMENT.split("#", 1)[0],
                            RUNTIME_REQUIREMENT + "; python_version >= '3.11'"):
            with self.subTest(requirement=requirement):
                self.change_inference(requirement)
                with self.assertRaisesRegex(ValueError, "inference extra"):
                    release.validate_project(self.root)
        self.change_inference(RUNTIME_REQUIREMENT)
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace(f'inference = ["{RUNTIME_REQUIREMENT}"]',
                                                f'inference = ["{RUNTIME_REQUIREMENT}", "{RUNTIME_REQUIREMENT}"]'))
        with self.assertRaisesRegex(ValueError, "inference extra"):
            release.validate_project(self.root)

    def test_project_rejects_normalized_runtime_core_and_other_extra_leakage(self):
        path = self.root / "pyproject.toml"
        original = path.read_text(encoding="utf-8")
        for changed in (original.replace("dependencies = [", 'dependencies = [\n    "Runtime.Llama==0.4.1",', 1),
                        original.replace("[project.optional-dependencies]",
                                         '[project.optional-dependencies]\nother = ["runtime_llama==0.4.1"]')):
            with self.subTest(changed=changed):
                path.write_text(changed, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "confined to the inference extra"):
                    release.validate_project(self.root)

    def test_metadata_accepts_normalized_runtime_name_spacing_and_only_inference_marker(self):
        for marker in ('extra == "inference"', "extra=='inference'", '( extra == "inference" )',
                       '"inference" == extra'):
            with self.subTest(marker=marker):
                release.check_metadata(self.metadata([f" Runtime.Llama@ {RUNTIME_URL} ; {marker}"]), self.project)

    def test_metadata_rejects_wrong_identity_duplicates_and_core_leakage(self):
        correct = f'{RUNTIME_REQUIREMENT}; extra == "inference"'
        for requirements in ([RUNTIME_REQUIREMENT], [correct, correct],
                             [correct, "Runtime.Llama==0.4.1"], ["runtime-llama==0.4.0; extra == 'inference'"],
                             [correct.replace("dc7c2", "0c7c2")],
                             [correct.replace('; extra == "inference"', '')],
                             [correct + ' or python_version >= "3.11"'],
                             [correct + ' and python_version >= "3.11"'],
                             [correct + ' # ignored Python comment'],
                             [correct.replace('"inference"', '"infer" "ence"')],
                             [correct.replace('"inference"', '"other"')],
                             [f'runtime-llama[unexpected] @ {RUNTIME_URL}; extra == "inference"'], []):
            with self.subTest(requirements=requirements):
                with self.assertRaisesRegex(ValueError, "confined to the inference extra"):
                    release.check_metadata(self.metadata(requirements), self.project)

    def test_metadata_must_advertise_the_inference_extra_once(self):
        metadata = self.metadata()
        for altered in (metadata.replace(b"Provides-Extra: inference\n", b""),
                        metadata.replace(b"Provides-Extra: inference\n", b"Provides-Extra: inference\n" * 2)):
            with self.subTest(metadata=altered):
                with self.assertRaisesRegex(ValueError, "confined to the inference extra"):
                    release.check_metadata(altered, self.project)

    def test_both_archive_metadata_files_enforce_the_optional_boundary(self):
        invalid = self.metadata([RUNTIME_REQUIREMENT])
        for package in ("wheel_metadata", "sdist_metadata"):
            with self.subTest(package=package):
                self.packages(**{package: invalid})
                with self.assertRaisesRegex(ValueError, "confined to the inference extra"):
                    release.prepare(self.root, self.dist)

    def test_both_archives_reject_runtime_wheels_packages_and_vendor_payload(self):
        for path in ("runtime_llama-0.5.0-py3-none-any.whl", "third_party/runtime-llama/LICENSE",
                     "src/runtime_llama/__init__.py", "runtime_llama/__init__.py",
                     "runtime_llama-0.4.1.dist-info/METADATA", "src/flow_of_work_mcp/_vendor/llamatelemetry.py"):
            for package in ("wheel_members", "sdist_members"):
                with self.subTest(path=path, package=package):
                    self.packages(**{package: {path: b"unexpected runtime"}})
                    with self.assertRaisesRegex(ValueError, "must not contain the optional runtime"):
                        release.prepare(self.root, self.dist)

    def test_runtime_and_other_unexpected_release_assets_block_inventory(self):
        for name in ("runtime_llama-0.5.0-py3-none-any.whl", "unexpected.txt"):
            with self.subTest(name=name):
                path = self.dist / name
                path.write_bytes(b"unexpected")
                with self.assertRaisesRegex(ValueError, "dist must contain exactly"):
                    release.prepare(self.root, self.dist)
                path.unlink()

    def test_extra_checksum_member_is_rejected(self):
        release.prepare(self.root, self.dist)
        with (self.dist / "SHA256SUMS").open("a", encoding="utf-8") as stream:
            stream.write("0" * 64 + "  runtime_llama-0.5.0-py3-none-any.whl\n")
        with self.assertRaisesRegex(ValueError, "SHA256SUMS does not match"):
            release.prepare(self.root, self.dist, verify_checksums=True)

    def test_no_runtime_vendor_source_or_manifest_rule_remains(self):
        self.assertFalse((SOURCE / "third_party/runtime-llama").exists())
        self.assertNotIn("third_party/runtime-llama", (SOURCE / "MANIFEST.in").read_text(encoding="utf-8"))

    def test_sdist_must_include_the_offline_reader(self):
        self.packages(omit="docs/presentation/index.html")
        with self.assertRaisesRegex(ValueError, "source distribution omits required source docs/presentation/index.html"):
            release.prepare(self.root, self.dist)

    def test_sdist_must_include_the_current_installation_upgrade_and_release_guides(self):
        for source in sorted(self.release_docs):
            with self.subTest(source=source):
                self.packages(omit=source)
                with self.assertRaisesRegex(ValueError, f"source distribution omits required source {source}"):
                    release.prepare(self.root, self.dist)

    def test_sdist_upgrade_instructions_must_match_the_checked_source(self):
        self.packages(replace={"docs/UPGRADING.md": b"Unexpected stale upgrade instructions.\n"})
        with self.assertRaisesRegex(ValueError, "source distribution docs/UPGRADING.md differs"):
            release.prepare(self.root, self.dist)

    def test_sdist_release_guide_drift_cannot_generate_release_notes(self):
        path = f"docs/RELEASE-NOTES-{self.project['version']}.md"
        self.packages(replace={path: b"Stale callable-contract or qualification claims.\n"})
        output = self.root / "generated-notes.md"
        with self.assertRaisesRegex(ValueError, f"source distribution {re.escape(path)} differs"):
            release.prepare(self.root, self.dist, notes=output)
        self.assertFalse(output.exists())

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
