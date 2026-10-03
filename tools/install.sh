#!/usr/bin/env bash
# Install a pinned Flower release; curl piping reads agent selection from /dev/tty.
set -euo pipefail

FLOWER_REPOSITORY="https://github.com/Damel91/flower-mcp"
FLOWER_VERSION="0.1.1"
UV_VERSION="0.12.21"
selection=""
has_client_config=0
backend_args=()

fail() { printf 'Flower installation failed: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'HELP'
Flower MCP release installer for macOS and Linux.
With no agent flag, choose Codex, Claude Code, Cursor or installation only.

Options:
  --platform codex|claude-code|cursor   Register this agent without a menu
  --no-register                       Install without registering an agent
  --version MAJOR.MINOR.PATCH          Pinned release (default: 0.1.1)
  --venv PATH                          Dedicated installation environment
  --upgrade                            Upgrade an existing owned installation
  --client-config PATH                 Explicit agent configuration file
  --profile NAME                       Persistent profile (default: default)
  --profile-root PATH                  Persistent lifecycle data directory
HELP
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --platform)
            [[ $# -ge 2 ]] || fail "--platform requires an agent name"
            [[ -z "$selection" ]] || fail "choose only one agent or --no-register"
            case "$2" in codex|claude-code|cursor) selection="$2" ;; *) fail "unsupported agent: $2" ;; esac
            shift 2 ;;
        --no-register)
            [[ -z "$selection" ]] || fail "choose only one agent or --no-register"
            selection="none"; shift ;;
        --version)
            [[ $# -ge 2 ]] || fail "--version requires MAJOR.MINOR.PATCH"
            FLOWER_VERSION="$2"; shift 2 ;;
        --venv|--client-config|--profile|--profile-root)
            [[ $# -ge 2 ]] || fail "$1 requires a value"
            if [[ "$1" == --client-config ]]; then has_client_config=1; fi
            backend_args+=("$1" "$2"); shift 2 ;;
        --upgrade) backend_args+=("$1"); shift ;;
        *) fail "unknown option: $1 (use --help)" ;;
    esac
done

[[ "$FLOWER_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || fail "version must be a stable MAJOR.MINOR.PATCH release"
case "$(uname -s)" in
    Darwin) installation_base="${HOME:?}/Library/Application Support/Flower MCP Install" ;;
    Linux)
        if [[ "${XDG_DATA_HOME:-}" == /* ]]; then
            installation_base="$XDG_DATA_HOME/flower-mcp-install"
        else
            installation_base="${HOME:?}/.local/share/flower-mcp-install"
        fi ;;
    *) fail "the curl installer supports macOS and Linux; Windows can use the Python release installer" ;;
esac

if [[ -z "$selection" ]]; then
    printf 'Install Flower MCP %s\n1) Codex\n2) Claude Code\n3) Cursor\n4) Install only\n' "$FLOWER_VERSION" >&2
    while [[ -z "$selection" ]]; do
        printf 'Select an agent [1-4]: ' >&2
        if ! IFS= read -r answer 2>/dev/null </dev/tty; then
            fail "no terminal is available; pass --platform codex|claude-code|cursor or --no-register"
        fi
        case "$answer" in
            1) selection="codex" ;;
            2) selection="claude-code" ;;
            3) selection="cursor" ;;
            4) selection="none" ;;
            *) printf 'Enter 1, 2, 3 or 4.\n' >&2 ;;
        esac
    done
fi
if [[ "$selection" == "none" ]]; then
    [[ "$has_client_config" == 0 ]] || fail "--client-config requires an agent selection"
    backend_args+=(--no-register)
else
    backend_args+=(--platform "$selection")
fi
backend_args+=(--version "$FLOWER_VERSION")

command -v curl >/dev/null || fail "curl is required"
command -v awk >/dev/null || fail "awk is required"
if command -v sha256sum >/dev/null; then
    checksum_command="sha256sum"
elif command -v shasum >/dev/null; then
    checksum_command="shasum"
else
    fail "sha256sum or shasum is required to verify release files"
fi

temporary="$(mktemp -d "${TMPDIR:-/tmp}/flower-bootstrap.XXXXXXXX")"
trap 'rm -rf -- "$temporary"' EXIT
download() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 120 --output "$2" "$1"
}
release_url="$FLOWER_REPOSITORY/releases/download/v$FLOWER_VERSION"
download "$release_url/SHA256SUMS" "$temporary/SHA256SUMS"
download "$release_url/install_flower.py" "$temporary/install_flower.py"
expected="$(awk '
    NF == 0 { next }
    {
        if ($0 !~ /^[0-9a-fA-F]+ [ *][A-Za-z0-9_.-]+$/ || length(substr($0, 1, index($0, " ") - 1)) != 64) exit 1
        name = substr($0, 67)
        if (name == "." || name == ".." || seen[name]++) exit 1
        if (name == "install_flower.py") { result = tolower(substr($0, 1, 64)); found++ }
    }
    END { if (found != 1) exit 1; print result }
' "$temporary/SHA256SUMS")" || fail "SHA256SUMS does not contain one valid installer checksum"
if [[ "$checksum_command" == "sha256sum" ]]; then
    actual="$(sha256sum "$temporary/install_flower.py" | awk '{print tolower($1)}')"
else
    actual="$(shasum -a 256 "$temporary/install_flower.py" | awk '{print tolower($1)}')"
fi
[[ "$actual" == "$expected" ]] || fail "Python installer checksum does not match the pinned release"

python_command=""
for candidate in python3 python; do
    if candidate_path="$(command -v "$candidate")" && \
        "$candidate_path" -I -c 'import sys, ensurepip, ssl, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        python_command="$candidate_path"
        break
    fi
done
if [[ -z "$python_command" ]]; then
    printf 'Preparing managed Python 3.11 for Flower MCP...\n' >&2
    download "https://astral.sh/uv/$UV_VERSION/install.sh" "$temporary/uv-installer.sh"
    UV_UNMANAGED_INSTALL="$temporary/uv" UV_NO_MODIFY_PATH=1 sh "$temporary/uv-installer.sh"
    uv_command="$temporary/uv/uv"
    [[ "$("$uv_command" --version | awk '{print $2}')" == "$UV_VERSION" ]] || fail "uv bootstrap version differs from the pinned version"
    (
        cd "$temporary"
        UV_PYTHON_INSTALL_DIR="$installation_base/python" UV_CACHE_DIR="$temporary/uv-cache" \
            "$uv_command" --no-config venv --seed --managed-python --python 3.11 "$temporary/bootstrap"
    )
    python_command="$temporary/bootstrap/bin/python"
fi

"$python_command" -I "$temporary/install_flower.py" "${backend_args[@]}"
