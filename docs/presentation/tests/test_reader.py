"""Editorial corpus and offline packaging checks; not Flower qualification."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("flower_presentation_reader", ROOT / "build_reader.py")
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class ReaderChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo/docs/presentation/ita"
        self.root.mkdir(parents=True)
        (self.root.parent / "assets").mkdir()
        for name in reader.ASSETS:
            (self.root.parent / "assets" / name).write_bytes(b"test asset")
        self.pages = [{"path": "README.md", "group": "Test", "label": "Index"}]
        self.write("README.md", "# Index\n\nA local document.\n")

    def write(self, path, source):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")

    def manifest(self):
        self.write("navigation.json", json.dumps({
            "title": "Flower MCP", "subtitle": "Test", "language": "it",
            "product_revision": "a" * 40, "pages": self.pages,
        }))

    def compile(self):
        self.manifest()
        return reader.compile_reader(self.root)

    def test_actual_corpus_and_generated_files_are_current(self):
        for folder, language in reader.LANGUAGES.items():
            with self.subTest(folder=folder):
                root = ROOT / folder
                output, report = reader.compile_reader(root)
                self.assertEqual(report["pages"], 18)
                self.assertEqual(report["language"], language)
                self.assertEqual(report["public_tools_checked"], 36)
                self.assertGreater(report["links_checked"], 100)
                self.assertEqual(output, (root / "index.html").read_text(encoding="utf-8"))
                self.assertEqual(report, json.loads((root / "build-report.json").read_text(encoding="utf-8")))
                self.assertNotIn("/Users/", output)

    def test_build_is_deterministic_and_compile_does_not_write(self):
        self.manifest()
        before = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(reader.compile_reader(self.root), reader.compile_reader(self.root))
        after = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / "index.html").exists())

    def test_method_screenshots_have_no_exif_or_text_metadata(self):
        for name in reader.ASSETS:
            if not name.startswith("method-"):
                continue
            with self.subTest(name=name):
                data = (ROOT / "assets" / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                offset = 8
                while offset < len(data):
                    size = int.from_bytes(data[offset:offset + 4], "big")
                    kind = data[offset + 4:offset + 8]
                    self.assertNotIn(kind, {b"eXIf", b"iTXt", b"tEXt", b"zTXt"})
                    offset += size + 12
                self.assertEqual(offset, len(data))

    def test_shared_image_links_open_the_local_crop_not_a_frozen_product_url(self):
        self.write("README.md", "# Index\n\n[![Crop](../assets/method-plan.png)](../assets/method-plan.png)\n")
        output, _ = self.compile()
        self.assertIn('href="../assets/method-plan.png"', output)
        self.assertIn('src="../assets/method-plan.png"', output)
        self.assertNotIn(reader.REPOSITORY_URL + "/blob/", output)

    def test_same_filename_in_different_directories_remains_distinct(self):
        for directory in ("one", "two"):
            self.pages.append({"path": f"{directory}/README.md", "group": "Test", "label": directory})
            self.write(f"{directory}/README.md", f"# {directory}\n\n[Back](../README.md)\n")
        output, report = self.compile()
        self.assertEqual(report["pages"], 3)
        self.assertIn('data-document="one/README.md"', output)
        self.assertIn('data-document="two/README.md"', output)
        self.assertNotEqual(reader.anchor_prefix("one/README.md"), reader.anchor_prefix("two/README.md"))

    def test_local_page_and_section_links_are_routed(self):
        self.write("README.md", "# Index\n\n[Next](next.md#perché)\n")
        self.write("next.md", "# Next\n\n## Perché\n\n[Back](README.md)\n")
        self.pages.append({"path": "next.md", "group": "Test", "label": "Next"})
        output, _ = self.compile()
        self.assertIn('data-page="next.md" data-section="perché"', output)
        self.assertIn('id="' + reader.anchor_prefix("next.md") + '--perché"', output)

    def test_missing_links_and_anchors_are_rejected(self):
        for link in ("absent.md", "#absent"):
            with self.subTest(link=link):
                self.write("README.md", f"# Index\n\n[Broken]({link})\n")
                with self.assertRaisesRegex(ValueError, "Missing"):
                    self.compile()

    def test_duplicate_and_noncanonical_manifest_paths_are_rejected(self):
        for path in ("README.md", "one/../README.md", "one\\README.md"):
            with self.subTest(path=path):
                self.pages = [
                    {"path": "README.md", "group": "Test", "label": "Index"},
                    {"path": path, "group": "Test", "label": "Invalid"},
                ]
                with self.assertRaisesRegex(ValueError, "Duplicate or noncanonical"):
                    self.compile()

    def test_pages_cannot_escape_publication_except_public_bootstrap(self):
        self.pages.append({"path": "../private.md", "group": "Test", "label": "Invalid"})
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.compile()

    def test_public_bootstrap_is_embedded_not_fetched(self):
        self.write("../../BOOTSTRAP.md", "# Public bootstrap\n")
        self.pages.append({"path": "../../BOOTSTRAP.md", "group": "Test", "label": "Bootstrap"})
        output, report = self.compile()
        self.assertEqual(report["pages"], 2)
        self.assertIn("Public bootstrap</h1>", output)
        self.assertNotIn("fetch(", output)

    def test_raw_html_is_not_executed(self):
        self.write("README.md", '# Index\n\n<script>alert("x")</script>\n')
        output, _ = self.compile()
        self.assertNotIn('<script>alert("x")</script>', output)
        self.assertIn("&lt;script&gt;", output)

    def test_remote_images_and_unsafe_links_are_rejected_or_inert(self):
        self.write("README.md", "# Index\n\n![Remote](https://example.test/image.png)\n")
        with self.assertRaisesRegex(ValueError, "Nonlocal image"):
            self.compile()
        self.write("README.md", "# Index\n\n[Unsafe](javascript:alert%281%29)\n")
        output, _ = self.compile()
        self.assertNotIn('href="javascript:', output)

    def test_images_cannot_escape_publication(self):
        self.write("../../../private.png", "not an image")
        self.write("README.md", "# Index\n\n![Private](../../../private.png)\n")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.compile()

    def test_duplicate_headings_get_distinct_anchors(self):
        parser = MarkdownIt("commonmark")
        _, anchors, title = reader.parse_document(parser, "# Index\n\n## Perché\n\n## Perché\n")
        self.assertEqual(title, "Index")
        self.assertEqual(anchors, {"index", "perché", "perché-1"})

    def test_headless_document_and_unfrozen_revision_are_rejected(self):
        self.write("README.md", "## No main heading\n")
        with self.assertRaisesRegex(ValueError, "H1"):
            self.compile()
        self.write("README.md", "# Index\n")
        self.manifest()
        manifest = json.loads((self.root / "navigation.json").read_text())
        manifest["product_revision"] = "main"
        self.write("navigation.json", json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "frozen Git commit"):
            reader.compile_reader(self.root)

    def test_catalog_requires_every_public_tool_once(self):
        repository = self.root.parents[2]
        registry = repository / "src/flow_of_work_mcp/application/operation_contracts.py"
        registry.parent.mkdir(parents=True)
        registry.write_text('ToolDescriptor("fow_example")\n', encoding="utf-8")
        self.assertEqual(reader.validate_public_catalog(repository, "| `fow_example` | Example |"), 1)
        for source in ("", "| `fow_wrong` | Wrong |", "| `fow_example` | One |\n| `fow_example` | Two |"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "tool table drift"):
                    reader.validate_public_catalog(repository, source)

    def test_public_source_reference_must_exist_and_match_revision(self):
        (self.root.parents[2] / "src").mkdir()
        for revision in ("a" * 40, "b" * 40):
            url = f"{reader.REPOSITORY_URL}/blob/{revision}/src/missing.py"
            self.write("README.md", f"# Index\n\n[Source]({url})\n")
            with self.assertRaisesRegex(ValueError, "Unverifiable public source"):
                self.compile()

    def test_offline_shell_has_local_assets_and_blocks_connections(self):
        output, _ = self.compile()
        self.assertIn("connect-src 'none'", output)
        self.assertNotRegex(output, r'<(?:script|link|img)[^>]+(?:src|href)="https?://')
        self.assertIn('tabindex="-1"', output)

    def test_editions_have_matching_pages_tools_and_public_sources(self):
        manifests = [json.loads((ROOT / folder / "navigation.json").read_text(encoding="utf-8")) for folder in reader.LANGUAGES]
        paths = [[page["path"] for page in manifest["pages"]] for manifest in manifests]
        self.assertEqual(paths[0], paths[1])
        for path in paths[0]:
            with self.subTest(path=path):
                editions = [(ROOT / folder / path).read_text(encoding="utf-8") for folder in reader.LANGUAGES]
                self.assertEqual(set(re.findall(r"`(fow_[a-z_]+)`", editions[0])), set(re.findall(r"`(fow_[a-z_]+)`", editions[1])))
                self.assertEqual(set(re.findall(r"https?://[^)\s]+", editions[0])), set(re.findall(r"https?://[^)\s]+", editions[1])))
                self.assertEqual(len(re.findall(r"^#{1,6} ", editions[0], re.MULTILINE)), len(re.findall(r"^#{1,6} ", editions[1], re.MULTILINE)))

    def test_installation_closes_the_story_and_separates_windows_source_from_release(self):
        for folder in reader.LANGUAGES:
            with self.subTest(folder=folder):
                root = ROOT / folder
                manifest = json.loads((root / "navigation.json").read_text(encoding="utf-8"))
                paths = [page["path"] for page in manifest["pages"]]
                self.assertEqual(paths[paths.index("06-operate.md") + 1], "try-flower.md")
                self.assertIn("try-flower.md", (root / "06-operate.md").read_text(encoding="utf-8"))
                source = (root / "try-flower.md").read_text(encoding="utf-8")
                for name in ("install.sh", "install_flower.py", "flow_of_work_mcp-0.1.0-py3-none-any.whl",
                             "flow_of_work_mcp-0.1.0.tar.gz", "SHA256SUMS", "BOOTSTRAP.md"):
                    self.assertIn(f"/releases/download/v0.1.0/{name}", source)
                self.assertIn("https://raw.githubusercontent.com/Damel91/flower-mcp/main/tools/install.ps1", source)
                self.assertNotIn("/releases/download/v0.1.0/install.ps1", source)

    def test_english_shell_and_errors_are_localized(self):
        output, _ = reader.compile_reader(ROOT / "eng")
        self.assertIn('<html lang="en">', output)
        self.assertIn("Skip to content", output)
        self.assertIn('data-missing-page="The requested page', output)
        self.assertNotIn("La pagina richiesta", output)
        self.assertNotIn("Indice del percorso", output)

    def test_language_selector_is_current_and_uses_local_readers(self):
        output = reader.compile_selector(ROOT)
        self.assertEqual(output, (ROOT / "index.html").read_text(encoding="utf-8"))
        self.assertIn('href="ita/index.html"', output)
        self.assertIn('href="eng/index.html"', output)
        self.assertNotIn('<script', output)
        self.assertNotIn('href="eng/README.md"', output)

    def test_only_canonical_shared_assets_can_be_used(self):
        self.write("README.md", "# Index\n\n![Logo](../assets/flower-mcp-logo.png)\n")
        output, _ = self.compile()
        self.assertIn('src="../assets/flower-mcp-logo.png"', output)
        self.write("../assets/private.png", "not an image")
        self.write("README.md", "# Index\n\n![Invalid](../assets/private.png)\n")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.compile()


if __name__ == "__main__":
    unittest.main()
