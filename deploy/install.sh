#!/usr/bin/env bash
#
# Install ecoNEXT Gateway as a systemd service.
#
# Usage:
#   sudo ./deploy/install.sh                  # install from source repo
#   sudo ./deploy/install.sh /srv/econext      # custom prefix
#   sudo ./deploy/install.sh --uninstall      # remove service and install dir
#
# Bundle install (used by bootstrap.sh):
#   ECONEXT_WHEEL=/path/to/wheel.whl sudo ./deploy/install.sh
#
# What it does:
#   1. Creates PREFIX directory (default /opt/econext-gateway)
#   2. Creates a venv and installs the package (from wheel or source)
#   3. Generates and installs a systemd service unit
#   4. Installs the udev rule for PLUM ecoLINK3 adapter
#   5. Enables and starts the service
#
# Prerequisites:
#   - Python 3.11+
#   - uv (https://docs.astral.sh/uv/) or pip

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SERVICE_NAME="econext-gateway"
DEFAULT_PREFIX="/opt/econext-gateway"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
UDEV_FILE="/etc/udev/rules.d/99-econext.rules"

# Defaults (overridable via env)
ECONEXT_USER="${ECONEXT_USER:-$(logname 2>/dev/null || echo "$SUDO_USER")}"
ECONEXT_SERIAL_PORT="${ECONEXT_SERIAL_PORT:-/dev/econext}"
ECONEXT_LOG_LEVEL="${ECONEXT_LOG_LEVEL:-INFO}"
ECONEXT_API_PORT="${ECONEXT_API_PORT:-8000}"

# ---- helpers ---------------------------------------------------------------

info()  { echo "==> $*"; }
warn()  { echo "WARNING: $*" >&2; }
die()   { echo "ERROR: $*" >&2; exit 1; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root (use sudo)"
    fi
}

check_deps() {
    command -v python3 >/dev/null 2>&1 || die "python3 not found"

    local pyver
    pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
        info "Python $pyver found"
    else
        die "Python 3.11+ required (found $pyver)"
    fi

    # Find uv (optional) - check common locations since sudo may strip PATH
    UV=""
    for candidate in \
        "$(command -v uv 2>/dev/null)" \
        "/home/${ECONEXT_USER}/.local/bin/uv" \
        "/home/${ECONEXT_USER}/.cargo/bin/uv" \
        "/usr/local/bin/uv" \
        "/usr/bin/uv"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            UV="$candidate"
            break
        fi
    done

    if [[ -n "$UV" ]]; then
        info "Using uv at $UV"
    else
        info "uv not found, using python3 -m venv + pip"
    fi
}

# Create venv and install a package (wheel path or "." for source install)
# Uses uv if available, otherwise falls back to python3 venv + pip
venv_install() {
    local prefix="$1"
    local package="$2"

    if [[ -n "$UV" ]]; then
        sudo -u "$ECONEXT_USER" bash -c "
            cd '$prefix'
            '$UV' venv --python python3 --allow-existing
            '$UV' pip install --python .venv/bin/python '$package'
        "
    else
        sudo -u "$ECONEXT_USER" bash -c "
            cd '$prefix'
            python3 -m venv .venv
            .venv/bin/pip install --upgrade pip
            .venv/bin/pip install '$package'
        "
    fi
}

# ---- uninstall -------------------------------------------------------------

do_uninstall() {
    local prefix="${1:-$DEFAULT_PREFIX}"
    check_root
    info "Uninstalling ${SERVICE_NAME}..."

    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Stopping service..."
        systemctl stop "$SERVICE_NAME"
    fi
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        systemctl disable "$SERVICE_NAME"
    fi
    [[ -f "$SERVICE_FILE" ]] && rm -v "$SERVICE_FILE"
    systemctl daemon-reload

    if [[ -d "$prefix" ]]; then
        info "Removing $prefix..."
        rm -rf "$prefix"
    fi

    info "Uninstall complete. udev rule at $UDEV_FILE left in place (remove manually if desired)."
    exit 0
}

# ---- install ---------------------------------------------------------------

do_install() {
    local prefix="${1:-$DEFAULT_PREFIX}"

    check_root
    check_deps

    if [[ -z "$ECONEXT_USER" ]]; then
        die "Cannot determine install user. Set ECONEXT_USER=<username>"
    fi
    id "$ECONEXT_USER" >/dev/null 2>&1 || die "User '$ECONEXT_USER' does not exist"

    info "Installing ${SERVICE_NAME} to ${prefix}"
    info "  User:        $ECONEXT_USER"
    info "  Serial port: $ECONEXT_SERIAL_PORT"
    info "  API port:    $ECONEXT_API_PORT"
    info "  Log level:   $ECONEXT_LOG_LEVEL"

    # -- stop existing service if running --
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Stopping existing service..."
        systemctl stop "$SERVICE_NAME"
    fi

    mkdir -p "$prefix"

    if [[ -n "${ECONEXT_WHEEL:-}" ]]; then
        # -- bundle install: install from pre-built wheel --
        info "Installing from wheel: $ECONEXT_WHEEL"
        chown -R "$ECONEXT_USER":"$ECONEXT_USER" "$prefix"
        venv_install "$prefix" "$ECONEXT_WHEEL"
    else
        # -- dev install: copy source and install from it --
        info "Copying source to $prefix..."
        rsync -a --delete \
            --exclude '.venv' \
            --exclude '__pycache__' \
            --exclude '.pytest_cache' \
            --exclude '.git' \
            --exclude 'logs' \
            "$REPO_DIR/" "$prefix/"
        chown -R "$ECONEXT_USER":"$ECONEXT_USER" "$prefix"
        info "Creating venv and installing package..."
        venv_install "$prefix" "."
    fi

    # -- verify install --
    local version
    version="$("$prefix/.venv/bin/python" -c 'from econext_gateway import __version__; print(__version__)')"
    info "Installed version: $version"

    # -- install systemd service --
    info "Installing systemd service..."
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=ecoNEXT Gateway
After=network.target
Wants=network.target

[Service]
Type=simple
User=${ECONEXT_USER}
WorkingDirectory=${prefix}
ExecStart=${prefix}/.venv/bin/uvicorn econext_gateway.main:app --host 0.0.0.0 --port ${ECONEXT_API_PORT}
Restart=always
RestartSec=10
Environment=ECONEXT_SERIAL_PORT=${ECONEXT_SERIAL_PORT}
Environment=ECONEXT_LOG_LEVEL=${ECONEXT_LOG_LEVEL}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    # -- install udev rule --
    info "Installing udev rule to $UDEV_FILE..."
    cp "$SCRIPT_DIR/99-econext.rules" "$UDEV_FILE"
    udevadm control --reload-rules
    udevadm trigger

    # -- start --
    info "Starting service..."
    systemctl start "$SERVICE_NAME"
    sleep 1

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "Service is running."
    else
        warn "Service failed to start. Check: journalctl -u $SERVICE_NAME -n 30"
    fi

    echo ""
    info "Installation complete."
    echo "  Service:  systemctl status $SERVICE_NAME"
    echo "  Logs:     journalctl -u $SERVICE_NAME -f"
    echo "  API:      http://$(hostname -I | awk '{print $1}'):${ECONEXT_API_PORT}/health"
    echo "  Prefix:   $prefix"
}

# ---- main ------------------------------------------------------------------

case "${1:-}" in
    --uninstall|-u)
        do_uninstall "${2:-$DEFAULT_PREFIX}"
        ;;
    --help|-h)
        sed -n '2,/^$/s/^# \?//p' "$0"
        exit 0
        ;;
    *)
        do_install "${1:-$DEFAULT_PREFIX}"
        ;;
esac
