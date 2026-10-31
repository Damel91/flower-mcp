"""Client installer routes forward literal arguments without native client effects."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flower_client_installer", SOURCE / "tools/install_flower.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ClientInstallationTests(unittest.TestCase):
    def test_python_installer_accepts_clients_with_explicit_selected_file(self):
        for platform in ("antigravity", "gemini-cli", "opencode"):
            with self.subTest(platform=platform):
                args = installer.build_parser().parse_args([
                    "--platform", platform, "--client-config", "selected client settings.json",
                    "--profile-root", "Flower profiles",
                ])
                self.assertEqual(args.platform, platform)
                self.assertEqual(args.client_config, Path("selected client settings.json"))
                self.assertEqual(args.profile_root, Path("Flower profiles"))
                self.assertFalse(args.no_register)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Bash frontend requires POSIX")
    def test_bash_frontend_forwards_each_client_and_literal_paths(self):
        for platform in ("antigravity", "gemini-cli", "opencode"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(prefix="flower-client-frontend-") as temporary:
                root = Path(temporary)
                binaries = root / "bin"
                binaries.mkdir()
                backend = root / "install_flower.py"
                backend.write_bytes(b"# synthetic backend, never executed\n")
                manifest = root / "SHA256SUMS"
                manifest.write_text(hashlib.sha256(backend.read_bytes()).hexdigest() + "  install_flower.py\n")
                capture = root / "forwarded-args.txt"
                helpers = {
                    "curl": '''#!/bin/sh
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) output="$2"; shift 2 ;;
        https://*) url="$1"; shift ;;
        *) shift ;;
    esac
done
case "$url" in
    */SHA256SUMS) cp "$FLOWER_TEST_MANIFEST" "$output" ;;
    */install_flower.py) cp "$FLOWER_TEST_BACKEND" "$output" ;;
    *) exit 97 ;;
esac
''',
                    "python3": '''#!/bin/sh
if [ "$2" = "-c" ]; then exit 0; fi
printf '%s\\n' "$@" > "$FLOWER_TEST_CAPTURE"
''',
                }
                for name, content in helpers.items():
                    executable = binaries / name
                    executable.write_text(content)
                    executable.chmod(0o755)
                config = root / 'Client settings "selected".json'
                profiles = root / "Flower profiles"
                environment = root / "Flower venv"
                env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                       "TMPDIR": str(root), "FLOWER_TEST_MANIFEST": str(manifest),
                       "FLOWER_TEST_BACKEND": str(backend), "FLOWER_TEST_CAPTURE": str(capture)}
                result = subprocess.run([
                    "bash", str(SOURCE / "tools/install.sh"), "--platform", platform,
                    "--client-config", str(config), "--profile-root", str(profiles),
                    "--venv", str(environment),
                ], env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = capture.read_text().splitlines()
                self.assertEqual(forwarded[0], "-I")
                self.assertEqual(forwarded[2:10], [
                    "--client-config", str(config), "--profile-root", str(profiles),
                    "--venv", str(environment), "--platform", platform,
                ])
                self.assertEqual(forwarded[10], "--version")
                self.assertFalse(config.exists())
                self.assertFalse(profiles.exists())
                self.assertFalse(environment.exists())


if __name__ == "__main__":
    unittest.main()
