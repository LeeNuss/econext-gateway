#!/usr/bin/env bash
#
# Install econet GM3 Gateway as a systemd service.
#
# Usage:
#   sudo ./deploy/install.sh                  # install to /opt/econet-gm3-gateway
#   sudo ./deploy/install.sh /srv/econet      # custom prefix
#   sudo ./deploy/install.sh --uninstall      # remove service and install dir
#
# What it does:
#   1. Copies source to PREFIX (default /opt/econet-gm3-gateway)
#   2. Creates a venv and installs the package via uv pip install .
#   3. Generates and installs a systemd service unit
#   4. Installs the udev rule for PLUM ecoLINK3 adapter
#   5. Enables and starts the service
#
# Prerequisites:
#   - Python 3.11+
#   - uv (https://docs.astral.sh/uv/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SERVICE_NAME="econet-gm3-gateway"
DEFAULT_PREFIX="/opt/econet-gm3-gateway"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
UDEV_FILE="/etc/udev/rules.d/99-econet.rules"

# Defaults (overridable via env)
ECONET_USER="${ECONET_USER:-$(logname 2>/dev/null || echo "$SUDO_USER")}"
ECONET_SERIAL_PORT="${ECONET_SERIAL_PORT:-/dev/econet}"
ECONET_LOG_LEVEL="${ECONET_LOG_LEVEL:-INFO}"
ECONET_API_PORT="${ECONET_API_PORT:-8000}"

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

    # Find uv - check common locations since sudo may strip PATH
    UV=""
    for candidate in \
        "$(command -v uv 2>/dev/null)" \
        "/home/${ECONET_USER}/.local/bin/uv" \
        "/home/${ECONET_USER}/.cargo/bin/uv" \
        "/usr/local/bin/uv" \
        "/usr/bin/uv"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            UV="$candidate"
            break
        fi
    done
    [[ -n "$UV" ]] || die "uv not found (https://docs.astral.sh/uv/)"
    info "Using uv at $UV"

    local pyver
    pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
        info "Python $pyver found"
    else
        die "Python 3.11+ required (found $pyver)"
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

    if [[ -z "$ECONET_USER" ]]; then
        die "Cannot determine install user. Set ECONET_USER=<username>"
    fi
    id "$ECONET_USER" >/dev/null 2>&1 || die "User '$ECONET_USER' does not exist"

    info "Installing ${SERVICE_NAME} to ${prefix}"
    info "  User:        $ECONET_USER"
    info "  Serial port: $ECONET_SERIAL_PORT"
    info "  API port:    $ECONET_API_PORT"
    info "  Log level:   $ECONET_LOG_LEVEL"

    # -- stop existing service if running --
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        info "Stopping existing service..."
        systemctl stop "$SERVICE_NAME"
    fi

    # -- copy source to prefix --
    info "Copying source to $prefix..."
    mkdir -p "$prefix"
    rsync -a --delete \
        --exclude '.venv' \
        --exclude '__pycache__' \
        --exclude '.pytest_cache' \
        --exclude '.git' \
        --exclude 'logs' \
        "$REPO_DIR/" "$prefix/"
    chown -R "$ECONET_USER":"$ECONET_USER" "$prefix"

    # -- create venv and install --
    info "Creating venv and installing package..."
    sudo -u "$ECONET_USER" bash -c "
        cd '$prefix'
        '$UV' venv --python python3 --allow-existing
        '$UV' pip install --python .venv/bin/python .
    "

    # -- verify install --
    local version
    version="$("$prefix/.venv/bin/python" -c 'from econet_gm3_gateway import __version__; print(__version__)')"
    info "Installed version: $version"

    # -- install systemd service --
    info "Installing systemd service..."
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=econet GM3 Gateway
After=network.target
Wants=network.target

[Service]
Type=simple
User=${ECONET_USER}
WorkingDirectory=${prefix}
ExecStart=${prefix}/.venv/bin/uvicorn econet_gm3_gateway.main:app --host 0.0.0.0 --port ${ECONET_API_PORT}
Restart=always
RestartSec=10
Environment=ECONET_SERIAL_PORT=${ECONET_SERIAL_PORT}
Environment=ECONET_LOG_LEVEL=${ECONET_LOG_LEVEL}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    # -- install udev rule --
    info "Installing udev rule to $UDEV_FILE..."
    cp "$prefix/deploy/99-econet.rules" "$UDEV_FILE"
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
    echo "  API:      http://$(hostname -I | awk '{print $1}'):${ECONET_API_PORT}/health"
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
