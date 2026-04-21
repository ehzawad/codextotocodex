#!/bin/bash
set -euo pipefail

# Codex Chronicle installer.
# Prefers a prebuilt binary release, but falls back to a source-based venv
# install when no release asset exists yet.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ehzawad/codextotocodex/main/install.sh | bash
#
# Environment overrides (for testing / pinning):
#   CODEX_CHRONICLE_VERSION  - git tag, e.g. vX.Y.Z. Default: latest release.
#   CODEX_CHRONICLE_BASE_URL - override download host (e.g. local mirror).
#   CODEX_CHRONICLE_HOME     - data + runtime root. Default: $HOME/.codex-chronicle.

REPO_SLUG="ehzawad/codextotocodex"
CHRONICLE_HOME="${CODEX_CHRONICLE_HOME:-${CHRONICLE_HOME:-$HOME/.codex-chronicle}}"
BIN_DIR="$HOME/.local/bin"
RUNTIME_DIR="$CHRONICLE_HOME/runtime"
VERSION="${CODEX_CHRONICLE_VERSION:-${CHRONICLE_VERSION:-latest}}"
BASE_URL="${CODEX_CHRONICLE_BASE_URL:-${CHRONICLE_BASE_URL:-https://github.com/$REPO_SLUG/releases}}"

echo "Installing Codex Chronicle..."
echo ""

# -----------------------------------------------------------------------------
# 1. Detect platform
# -----------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS/$ARCH" in
    Darwin/arm64)       TARGET="darwin-arm64" ;;
    Linux/x86_64)       TARGET="linux-x86_64" ;;
    Darwin/x86_64)
        echo "ERROR: macOS Intel is not a prebuilt target yet."
        echo "  Build locally: git clone git@github.com:$REPO_SLUG.git && cd codextotocodex && pip install pyinstaller -e . && pyinstaller --name codex-chronicle --onedir --clean --noupx codex_chronicle/_entrypoint.py"
        exit 1
        ;;
    Linux/aarch64|Linux/arm64)
        echo "ERROR: Linux arm64 is not a prebuilt target yet."
        echo "  File an issue or build locally (same recipe as above)."
        exit 1
        ;;
    *)
        echo "ERROR: unsupported platform $OS/$ARCH"
        exit 1
        ;;
esac
echo "Platform: $TARGET"

# -----------------------------------------------------------------------------
# 2. Check dependencies (just curl/tar/codex - no Python, no git needed)
# -----------------------------------------------------------------------------
MISSING=""
for bin in curl tar; do
    command -v "$bin" >/dev/null 2>&1 || MISSING="$MISSING $bin"
done
CODEX_FOUND=""
if command -v codex >/dev/null 2>&1; then
    CODEX_FOUND="$(command -v codex)"
else
    for d in "$HOME/.local/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
        if [ -x "$d/codex" ]; then
            CODEX_FOUND="$d/codex"
            break
        fi
    done
fi
[ -z "$CODEX_FOUND" ] && MISSING="$MISSING codex"

if [ -n "$MISSING" ]; then
    echo "ERROR: Missing required tools:$MISSING"
    echo ""
    if echo "$MISSING" | grep -q codex; then
        echo '  Install the Codex CLI and ensure `codex` is on PATH.'
    fi
    exit 1
fi
echo "Codex:   $CODEX_FOUND"

# -----------------------------------------------------------------------------
# 3. Resolve download URLs
# -----------------------------------------------------------------------------
if [ "$VERSION" = "latest" ]; then
    # GitHub's /releases/latest/download/<asset> follows the redirect to the
    # newest tagged release — no REST API call, no jq, no rate limit.
    ASSET_URL="$BASE_URL/latest/download/codex-chronicle-$TARGET.tar.gz"
    SHA_URL="$BASE_URL/latest/download/codex-chronicle-$TARGET.tar.gz.sha256"
    SOURCE_URL="https://codeload.github.com/$REPO_SLUG/tar.gz/refs/heads/main"
else
    ASSET_URL="$BASE_URL/download/$VERSION/codex-chronicle-$TARGET.tar.gz"
    SHA_URL="$BASE_URL/download/$VERSION/codex-chronicle-$TARGET.tar.gz.sha256"
    SOURCE_URL="https://codeload.github.com/$REPO_SLUG/tar.gz/refs/tags/$VERSION"
fi
echo "Asset:    $ASSET_URL"

# -----------------------------------------------------------------------------
# 4. Download + verify + extract
# -----------------------------------------------------------------------------
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
cd "$TMPDIR"

INSTALL_MODE="prebuilt"
echo "Downloading prebuilt release..."
set +e
curl -fL --progress-bar -o codex-chronicle.tar.gz "$ASSET_URL"
ASSET_RC=$?
curl -fsSL -o codex-chronicle.tar.gz.sha256 "$SHA_URL"
SHA_RC=$?
set -e

if [ "$ASSET_RC" -eq 0 ] && [ "$SHA_RC" -eq 0 ]; then
    echo "Verifying SHA256..."
    EXPECTED=$(awk '{print $1}' codex-chronicle.tar.gz.sha256)
    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL=$(sha256sum codex-chronicle.tar.gz | awk '{print $1}')
    else
        ACTUAL=$(shasum -a 256 codex-chronicle.tar.gz | awk '{print $1}')
    fi
    if [ "$EXPECTED" != "$ACTUAL" ]; then
        echo "ERROR: SHA256 mismatch"
        echo "  expected: $EXPECTED"
        echo "  actual:   $ACTUAL"
        exit 1
    fi
    echo "SHA256 ok: $ACTUAL"

    echo "Extracting..."
    tar -xzf codex-chronicle.tar.gz
else
    INSTALL_MODE="source"
    echo "No prebuilt release asset found for $TARGET."
    echo "Falling back to source install from:"
    echo "  $SOURCE_URL"
    command -v python3 >/dev/null 2>&1 || {
        echo "ERROR: python3 is required for source fallback installs."
        exit 1
    }
    curl -fL --progress-bar -o codex-chronicle-src.tar.gz "$SOURCE_URL"
    SOURCE_DIR="$(tar -tzf codex-chronicle-src.tar.gz | head -1 | cut -d/ -f1)"
    echo "Extracting source..."
    tar -xzf codex-chronicle-src.tar.gz
fi

# -----------------------------------------------------------------------------
# 5. Clean up legacy install layouts
# -----------------------------------------------------------------------------
# Stop the daemon if it's running, so we can safely replace the binary.
DAEMON_WAS_RUNNING=0
if [ -f "$CHRONICLE_HOME/daemon.pid" ]; then
    DAEMON_PID=$(cat "$CHRONICLE_HOME/daemon.pid" 2>/dev/null || echo "")
    if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
        DAEMON_WAS_RUNNING=1
        kill -TERM "$DAEMON_PID" 2>/dev/null || true
        # Give launchd/systemd a moment to notice before we overwrite files.
        sleep 1
    fi
fi

# Remove the old source-tree install (venv + shell wrappers + git clone).
# The binary doesn't need any of it. Keep user data under $CHRONICLE_HOME,
# just nuke the managed .src dir if it's there.
if [ -d "$CHRONICLE_HOME/src" ]; then
    echo "Removing legacy source-tree install at $CHRONICLE_HOME/src..."
    rm -rf "$CHRONICLE_HOME/src"
fi
# Old symlinks / wrapper scripts from earlier layouts.
rm -f "$BIN_DIR/chronicle" "$BIN_DIR/chronicle-hook"
rm -f "$BIN_DIR/codex-chronicle" "$BIN_DIR/codex-chronicle-hook"

# -----------------------------------------------------------------------------
# 6. Install runtime + symlinks
# -----------------------------------------------------------------------------
mkdir -p "$BIN_DIR" "$CHRONICLE_HOME"
# Atomic swap: extract side-by-side, then rename. Prevents half-written runtime
# dir from being live if something crashes mid-install.
NEW_RUNTIME="$CHRONICLE_HOME/runtime.new"
rm -rf "$NEW_RUNTIME"
if [ "$INSTALL_MODE" = "prebuilt" ]; then
    mv "codex-chronicle-$TARGET" "$NEW_RUNTIME"
    RUNTIME_CLI_REL="codex-chronicle"
    RUNTIME_HOOK_REL="codex-chronicle"
else
    mkdir -p "$NEW_RUNTIME"
    RUNTIME_CLI_REL="venv/bin/codex-chronicle"
    RUNTIME_HOOK_REL="venv/bin/codex-chronicle-hook"
fi

if [ -d "$RUNTIME_DIR" ]; then
    OLD_RUNTIME="$CHRONICLE_HOME/runtime.old"
    rm -rf "$OLD_RUNTIME"
    mv "$RUNTIME_DIR" "$OLD_RUNTIME"
fi
mv "$NEW_RUNTIME" "$RUNTIME_DIR"
rm -rf "$CHRONICLE_HOME/runtime.old"

if [ "$INSTALL_MODE" = "source" ]; then
    python3 -m venv "$RUNTIME_DIR/venv"
    "$RUNTIME_DIR/venv/bin/pip" install --upgrade pip >/dev/null
    "$RUNTIME_DIR/venv/bin/pip" install "./$SOURCE_DIR" >/dev/null
fi

# macOS: strip quarantine. curl-downloaded files rarely carry quarantine, but
# tar can import it from individual entries, and some corporate MDM policies
# attach it. Clearing it here avoids Gatekeeper killing every binary launch.
if [ "$OS" = "Darwin" ]; then
    xattr -dr com.apple.quarantine "$RUNTIME_DIR" 2>/dev/null || true
fi

RUNTIME_CLI="$RUNTIME_DIR/$RUNTIME_CLI_REL"
RUNTIME_HOOK="$RUNTIME_DIR/$RUNTIME_HOOK_REL"

# Relative symlinks so the install layout stays portable if $HOME moves.
ln -sf "$RUNTIME_CLI" "$BIN_DIR/codex-chronicle"
ln -sf "$RUNTIME_HOOK" "$BIN_DIR/codex-chronicle-hook"

# -----------------------------------------------------------------------------
# 7. PATH check
# -----------------------------------------------------------------------------
if ! echo ":$PATH:" | grep -qF ":$BIN_DIR:"; then
    SHELL_RC=""
    case "$(basename "${SHELL:-}")" in
        zsh)  SHELL_RC="$HOME/.zshrc" ;;
        bash) SHELL_RC="$HOME/.bashrc" ;;
        fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
        *)    SHELL_RC="$HOME/.profile" ;;
    esac
    EXPORT_LINE='export PATH="$HOME/.local/bin:$PATH"'
    if ! grep -qF "$EXPORT_LINE" "$SHELL_RC" 2>/dev/null; then
        echo "$EXPORT_LINE" >> "$SHELL_RC"
        echo "Added ~/.local/bin to PATH in $SHELL_RC"
    fi
    export PATH="$BIN_DIR:$PATH"
fi

# -----------------------------------------------------------------------------
# 8. Configure hooks (via the binary we just installed)
# -----------------------------------------------------------------------------
echo "Configuring Codex hooks..."
mkdir -p "${CODEX_HOME:-$HOME/.codex}"
"$BIN_DIR/codex-chronicle" install-hooks

# -----------------------------------------------------------------------------
# 9. Tighten data dir perms + restart daemon if needed
# -----------------------------------------------------------------------------
chmod 700 "$CHRONICLE_HOME" 2>/dev/null || true

EFFECTIVE_MODE=$("$BIN_DIR/codex-chronicle" doctor 2>/dev/null | awk '/^mode:/ {print $2}')
[ -z "$EFFECTIVE_MODE" ] && EFFECTIVE_MODE="foreground"

if [ "$EFFECTIVE_MODE" = "background" ]; then
    if [ "$OS" = "Darwin" ]; then
        if launchctl print "gui/$(id -u)/com.codex_chronicle.daemon" >/dev/null 2>&1; then
            launchctl kickstart -k "gui/$(id -u)/com.codex_chronicle.daemon" >/dev/null 2>&1 \
                && echo "Kickstarted launchd daemon (new binary active)." \
                || echo "  (launchctl kickstart failed; daemon will pick up new binary on next restart)"
        fi
    elif [ "$OS" = "Linux" ]; then
        if systemctl --user is-active --quiet codex-chronicle-daemon.service 2>/dev/null; then
            systemctl --user restart codex-chronicle-daemon.service \
                && echo "Restarted systemd daemon (new binary active)." \
                || echo "  (systemctl restart failed; daemon will pick up new binary on next restart)"
        fi
    fi
fi

# -----------------------------------------------------------------------------
# 10. Verify + summary
# -----------------------------------------------------------------------------
echo ""
echo "Installed:"
echo "  $BIN_DIR/codex-chronicle      -> $RUNTIME_CLI"
echo "  $BIN_DIR/codex-chronicle-hook -> $RUNTIME_HOOK"
echo "  runtime:                 $RUNTIME_DIR  ($(du -sh "$RUNTIME_DIR" 2>/dev/null | awk '{print $1}'))"
echo "  version:                 $("$BIN_DIR/codex-chronicle" --version 2>/dev/null || echo 'unknown')"
echo "  install mode:            $INSTALL_MODE"
echo "  mode:                    $EFFECTIVE_MODE"
echo ""
echo "Installation complete!"
echo ""
echo "Restart Codex so the hooks take effect."
echo ""
echo "Other useful commands:"
echo "  codex-chronicle doctor            # diagnose config, daemon status, drift"
echo "  codex-chronicle update            # fetch and install the latest release"
echo "  codex-chronicle install-daemon    # switch to background summarization mode"
echo "  codex-chronicle query timeline    # recent sessions across all projects"
