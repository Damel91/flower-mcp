"""Install the optional Flower OpenCode V2 plugin without editing client settings."""

from importlib.resources import files
from pathlib import Path
import os
from tempfile import NamedTemporaryFile

from flow_of_work_mcp.profiles import ProfileError


def install_plugin(directory: Path) -> Path:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise ProfileError("Choose an existing OpenCode project directory.")
    target = directory / ".opencode" / "plugins" / "flower-compaction.js"
    if target.parent.resolve() != target.parent:
        raise ProfileError("Choose an OpenCode project whose plugin directories are local to that project.")
    content = files("flow_of_work_mcp").joinpath("resources", "opencode", target.name).read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, prefix=".flower-compaction-", delete=False) as staged:
        temporary = Path(staged.name)
        try:
            staged.write(content)
            staged.close()
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != content:
                raise ProfileError(f"Review and move the existing plugin before installing Flower recovery: {target}") from None
        finally:
            temporary.unlink()
    return target
