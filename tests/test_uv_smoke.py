"""Safety and startup regressions for the uv public qualifier; actual uv is separate."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flower_smoke_uv", SOURCE / "tools/smoke_uv.py")
uv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uv)


class UvQualifierTests(unittest.TestCase):
    def test_existing_state_is_rejected_before_source_or_command_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "ledger.sqlite3"
            marker.write_bytes(b"existing user data")
            with self.assertRaisesRegex(ValueError, "fresh"):
                uv.qualify(Path("missing"), root, Path("missing"), "missing", "a" * 40)
            self.assertEqual(marker.read_bytes(), b"existing user data")

    def test_environment_does_not_reuse_caller_profile_or_virtual_environment(self):
        original = {"PATH": "/safe/bin", "PYTHONPATH": "/checkout", "VIRTUAL_ENV": "/shared",
                    "UV_PROJECT_ENVIRONMENT": "/other", "FLOWER_HOME": "/user/state"}
        result = uv.core_environment(original, Path("/owned/test"), "/iaEnv/python")
        self.assertNotIn("PYTHONPATH", result)
        self.assertNotIn("VIRTUAL_ENV", result)
        self.assertEqual(result["UV_PROJECT_ENVIRONMENT"], "/owned/test/project/.venv")
        self.assertEqual(result["FLOWER_HOME"], "/owned/test/state")
        self.assertEqual(original["FLOWER_HOME"], "/user/state")

    def test_command_selects_uv_environment_and_avoids_startup_resync(self):
        arguments = uv.server_arguments(Path("/owned/state"))
        self.assertEqual(arguments[:4], ["run", "--no-sync", "flower-mcp", "serve"])
        self.assertEqual(arguments[-2:], ["--transport", "stdio"])
        self.assertEqual(arguments[arguments.index("--profile-root") + 1], "/owned/state")

    def test_source_copy_excludes_local_ledgers_environments_and_build_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            package = source / "src/flow_of_work_mcp"
            package.mkdir(parents=True)
            for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
                (source / name).write_text("fixture")
            (package / "__init__.py").write_text("fixture")
            for name in ("ledger.sqlite3", ".env", ".venv/secret", "src/ignored.egg-info/PKG-INFO"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private")
            copied = uv.copy_source(source, root / "copy")
            self.assertEqual(len(copied), 5)
            self.assertNotIn("ledger.sqlite3", copied)
            self.assertFalse((root / "copy/.venv").exists())

    def test_nested_package_state_is_refused_before_copying_private_bytes(self):
        for name in (".env", "ledger.sqlite3", "nested/token.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                package = source / "src/flow_of_work_mcp"
                package.mkdir(parents=True)
                for required in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
                    (source / required).write_text("fixture")
                private = package / name
                private.parent.mkdir(parents=True, exist_ok=True)
                private.write_text("private fixture")
                with self.assertRaisesRegex(ValueError, "unapproved package input"):
                    uv.copy_source(source, root / "copy")
                self.assertFalse((root / "copy/src/flow_of_work_mcp" / name).exists())

    def test_inherited_uv_redirects_and_python_home_cannot_escape_owned_project(self):
        original = {"UV_PROJECT": "/shared/project", "UV_WORKING_DIR": "/shared",
                    "UV_CONFIG_FILE": "/shared/uv.toml", "PYTHONHOME": "/shared/python"}
        result = uv.core_environment(original, Path("/owned/test"), "/iaEnv/python")
        self.assertNotEqual(result.get("UV_PROJECT"), "/shared/project")
        self.assertNotEqual(result.get("UV_WORKING_DIR"), "/shared")
        self.assertNotIn("UV_CONFIG_FILE", result)
        self.assertNotIn("PYTHONHOME", result)


if __name__ == "__main__":
    unittest.main()
