#!/usr/bin/env bash
#
# Install the Modbus sniffer as a standalone tool (separate from the gateway).
#
# Usage:
#   sudo ./deploy/install-sniffer.sh                  # install to /opt/modbus-sniffer
#   sudo ./deploy/install-sniffer.sh /srv/sniffer     # custom prefix
#   sudo ./deploy/install-sniffer.sh --uninstall      # remove everything
#
# Environment variables:
#   NFS_SHARE       NFS share the daily ship appends to (e.g. mynas:/vol/modbus)
#   INSTALL_USER    User to own files (default: invoking user)
#
# What it does:
#   1. Creates PREFIX directory (default /opt/modbus-sniffer)
#   2. Copies the sniffer tools and creates a venv with pyserial
#   3. Installs the udev rule for the Waveshare USB-RS485 adapter
#   4. Creates wrapper scripts in /usr/local/bin
#   5. Installs modbus-sniffer.service (capture to /var/lib/modbus-sniffer,
#      never touches the NAS) and modbus-sniffer-ship.timer (one NAS write
#      a day at 02:05 local time)
#   6. Optionally creates the NFS mount unit (if NFS_SHARE is set)
#
# Prerequisites:
#   - Python 3.11+
#   - Waveshare USB-RS485 adapter (FTDI FT232RL)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_PREFIX="/opt/modbus-sniffer"
UDEV_FILE="/etc/udev/rules.d/99-modbus-sniffer.rules"
MOUNT_UNIT="mnt-nas-modbus.mount"
MOUNT_POINT="/mnt/nas/modbus"
STATE_DIR="/var/lib/modbus-sniffer"
DEFAULTS_FILE="/etc/default/modbus-sniffer"

# NFS share the daily ship writes to (optional). If unset, an existing
# mount unit is left alone and the ship step simply fails until the share
# is mounted at $MOUNT_POINT by other means.
#   NFS_SHARE=mynas:/volume1/modbus sudo ./deploy/install-sniffer.sh
NFS_SHARE="${NFS_SHARE:-}"

INSTALL_USER="${INSTALL_USER:-$(logname 2>/dev/null || echo "$SUDO_USER")}"

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
}

create_venv() {
    local prefix="$1"

    # Find uv
    local uv=""
    for candidate in \
        "$(command -v uv 2>/dev/null)" \
        "/home/${INSTALL_USER}/.local/bin/uv" \
        "/home/${INSTALL_USER}/.cargo/bin/uv" \
        "/usr/local/bin/uv" \
        "/usr/bin/uv"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            uv="$candidate"
            break
        fi
    done

    if [[ -n "$uv" ]]; then
        info "Creating venv with uv..."
        sudo -u "$INSTALL_USER" bash -c "
            cd '$prefix'
            '$uv' venv --python python3 --allow-existing
            '$uv' pip install --python .venv/bin/python pyserial
        "
    else
        info "Creating venv with pip..."
        sudo -u "$INSTALL_USER" bash -c "
            cd '$prefix'
            python3 -m venv .venv
            .venv/bin/pip install --upgrade pip
            .venv/bin/pip install pyserial
        "
    fi
}

# ---- uninstall -------------------------------------------------------------

do_uninstall() {
    local prefix="${1:-$DEFAULT_PREFIX}"
    check_root
    info "Uninstalling modbus-sniffer..."

    local unit
    for unit in modbus-sniffer-ship.timer modbus-sniffer-ship.service modbus-sniffer.service; do
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            systemctl stop "$unit"
        fi
        if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
            systemctl disable "$unit"
        fi
        rm -fv "/etc/systemd/system/$unit"
    done

    # Unmount and remove NFS mount unit
    if systemctl is-active --quiet "$MOUNT_UNIT" 2>/dev/null; then
        systemctl stop "$MOUNT_UNIT"
    fi
    if systemctl is-enabled --quiet "$MOUNT_UNIT" 2>/dev/null; then
        systemctl disable "$MOUNT_UNIT"
    fi
    rm -fv "/etc/systemd/system/$MOUNT_UNIT"
    systemctl daemon-reload

    # Remove wrapper scripts
    rm -fv /usr/local/bin/modbus-detect
    rm -fv /usr/local/bin/modbus-sniffer

    # Remove install dir
    if [[ -d "$prefix" ]]; then
        info "Removing $prefix..."
        rm -rf "$prefix"
    fi

    # Remove udev rule
    if [[ -f "$UDEV_FILE" ]]; then
        rm -v "$UDEV_FILE"
        udevadm control --reload-rules
        udevadm trigger
    fi

    info "Uninstall complete."
    info "State directory $STATE_DIR (unshipped chunks, alerts.log) and $DEFAULTS_FILE left in place."
    exit 0
}

# ---- install ---------------------------------------------------------------

install_unit() {
    # Copy a unit from deploy/, substituting prefix and user.
    local name="$1" prefix="$2"
    sed -e "s|/opt/modbus-sniffer|${prefix}|g" \
        -e "s|^User=pi$|User=${INSTALL_USER}|" \
        "$SCRIPT_DIR/$name" > "/etc/systemd/system/$name"
}

do_install() {
    local prefix="${1:-$DEFAULT_PREFIX}"

    check_root
    check_deps

    if [[ -z "$INSTALL_USER" ]]; then
        die "Cannot determine install user. Set INSTALL_USER=<username>"
    fi
    id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist"

    info "Installing modbus-sniffer to ${prefix}"
    info "  User:  $INSTALL_USER"
    info "  Cache: $STATE_DIR/cache"
    info "  NAS:   $MOUNT_POINT (daily ship only)"

    # -- copy tools --
    mkdir -p "$prefix"
    cp "$REPO_DIR/tools/modbus_detect.py" "$prefix/"
    cp "$REPO_DIR/tools/modbus_sniffer.py" "$prefix/"
    cp "$SCRIPT_DIR/modbus-sniffer-ship.sh" "$prefix/"
    chmod +x "$prefix/modbus-sniffer-ship.sh"
    chown -R "$INSTALL_USER":"$INSTALL_USER" "$prefix"

    # -- venv with pyserial --
    create_venv "$prefix"

    # -- verify --
    "$prefix/.venv/bin/python" -c "import serial; print(f'pyserial {serial.VERSION}')"
    info "Dependencies OK"

    # -- wrapper scripts --
    info "Installing CLI wrappers to /usr/local/bin..."

    cat > /usr/local/bin/modbus-detect <<EOF
#!/usr/bin/env bash
exec ${prefix}/.venv/bin/python ${prefix}/modbus_detect.py "\$@"
EOF
    chmod +x /usr/local/bin/modbus-detect

    cat > /usr/local/bin/modbus-sniffer <<EOF
#!/usr/bin/env bash
# capture: interactive capture into ./modbus_cache with decoded frames on screen
# import/analyze/export: work on a throwaway SQLite database (see docs/HEATPUMP_MODBUS.md)
cmd="\${1:-}"
if [[ "\$cmd" == "capture" ]]; then
    exec ${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py capture --port /dev/heatpump --baud 9600 --stopbits 2 --parity N -v "\${@:2}"
else
    exec ${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py "\$@"
fi
EOF
    chmod +x /usr/local/bin/modbus-sniffer

    # -- udev rule --
    info "Installing udev rule to $UDEV_FILE..."
    cp "$SCRIPT_DIR/99-modbus-sniffer.rules" "$UDEV_FILE"
    udevadm control --reload-rules
    udevadm trigger

    # -- defaults file (webhook etc.) --
    if [[ ! -f "$DEFAULTS_FILE" ]]; then
        cat > "$DEFAULTS_FILE" <<EOF
# Environment for modbus-sniffer.service
# POST alert lines as JSON to this URL (Home Assistant webhook, Uptime Kuma push, ...)
#MODBUS_SNIFFER_WEBHOOK=http://homeassistant.local:8123/api/webhook/modbus-sniffer
EOF
        info "Wrote $DEFAULTS_FILE (webhook disabled)"
    fi

    # -- NFS mount (optional) --
    if [[ -n "$NFS_SHARE" ]]; then
        info "Installing NFS mount unit for $NFS_SHARE..."
        cat > "/etc/systemd/system/$MOUNT_UNIT" <<MOUNT_EOF
[Unit]
Description=NAS share for Modbus sniffer data
After=network-online.target
Wants=network-online.target

[Mount]
What=$NFS_SHARE
Where=$MOUNT_POINT
Type=nfs
Options=soft,timeo=50,retrans=3,_netdev

[Install]
WantedBy=multi-user.target
MOUNT_EOF
        mkdir -p "$MOUNT_POINT"
        systemctl daemon-reload
        systemctl enable "$MOUNT_UNIT"
        systemctl start "$MOUNT_UNIT"
        if mountpoint -q "$MOUNT_POINT"; then
            info "NFS mounted at $MOUNT_POINT"
        else
            warn "NFS mount failed - check $NFS_SHARE is reachable"
        fi
    elif [[ -f "/etc/systemd/system/$MOUNT_UNIT" ]]; then
        info "Keeping existing $MOUNT_UNIT"
    else
        warn "No NFS_SHARE set and no $MOUNT_UNIT: the daily ship will fail until $MOUNT_POINT is mounted"
    fi

    # -- systemd units --
    info "Installing systemd units..."
    install_unit modbus-sniffer.service "$prefix"
    install_unit modbus-sniffer-ship.service "$prefix"
    install_unit modbus-sniffer-ship.timer "$prefix"
    systemctl daemon-reload
    systemctl enable modbus-sniffer
    systemctl enable --now modbus-sniffer-ship.timer

    if systemctl is-active --quiet modbus-sniffer; then
        info "Restarting running modbus-sniffer (flushes the open chunk first)..."
        systemctl restart modbus-sniffer
    else
        info "Service installed (not started). Use: sudo systemctl start modbus-sniffer"
    fi

    echo ""
    info "Installation complete."
    echo ""
    echo "  Start service:      sudo systemctl start modbus-sniffer"
    echo "  Service status:     sudo systemctl status modbus-sniffer"
    echo "  Service logs:       journalctl -u modbus-sniffer -f"
    echo "  Flush open chunk:   sudo systemctl kill -s SIGUSR1 modbus-sniffer"
    echo "  Ship now (NAS!):    sudo systemctl start modbus-sniffer-ship"
    echo "  Next ship:          systemctl list-timers modbus-sniffer-ship.timer"
    echo ""
    echo "  Detect bus params:  modbus-detect --port /dev/heatpump"
    echo "  Manual capture:     modbus-sniffer capture"
    echo "  Analyze:            modbus-sniffer import $STATE_DIR/cache --db /var/tmp/recent.db"
    echo "                      modbus-sniffer analyze --db /var/tmp/recent.db"
    echo ""
    echo "  Cache:     $STATE_DIR/cache   Alerts: $STATE_DIR/alerts.log"
    echo "  NAS:       $MOUNT_POINT/YYYY/MM/YYYY-MM-DD.frames.gz"
    echo "  Install:   $prefix"
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
