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
#   NFS_SHARE       NFS share for database storage (e.g. mynas:/vol/modbus)
#   INSTALL_USER    User to own files (default: invoking user)
#
# What it does:
#   1. Creates PREFIX directory (default /opt/modbus-sniffer)
#   2. Copies the sniffer tools and creates a venv with pyserial
#   3. Installs the udev rule for the Waveshare USB-RS485 adapter
#   4. Creates wrapper scripts in /usr/local/bin
#   5. Optionally creates an NFS mount unit (if NFS_SHARE is set)
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

# NFS share for database storage (optional).
# Set NFS_SHARE to enable, e.g.:
#   NFS_SHARE=mynas:/volume1/modbus sudo ./deploy/install-sniffer.sh
NFS_SHARE="${NFS_SHARE:-}"
DB_DIR="${MOUNT_POINT}"

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

    # Stop and disable service
    if systemctl is-active --quiet modbus-sniffer 2>/dev/null; then
        systemctl stop modbus-sniffer
    fi
    if systemctl is-enabled --quiet modbus-sniffer 2>/dev/null; then
        systemctl disable modbus-sniffer
    fi
    rm -fv /etc/systemd/system/modbus-sniffer.service

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
    info "Data directory $DB_DIR left in place (remove manually if desired)."
    exit 0
}

# ---- install ---------------------------------------------------------------

do_install() {
    local prefix="${1:-$DEFAULT_PREFIX}"

    check_root
    check_deps

    if [[ -z "$INSTALL_USER" ]]; then
        die "Cannot determine install user. Set INSTALL_USER=<username>"
    fi
    id "$INSTALL_USER" >/dev/null 2>&1 || die "User '$INSTALL_USER' does not exist"

    info "Installing modbus-sniffer to ${prefix}"
    info "  User: $INSTALL_USER"
    info "  Data: $DB_DIR"

    # -- copy tools --
    mkdir -p "$prefix"
    cp "$REPO_DIR/tools/modbus_detect.py" "$prefix/"
    cp "$REPO_DIR/tools/modbus_sniffer.py" "$prefix/"
    chown -R "$INSTALL_USER":"$INSTALL_USER" "$prefix"

    # -- venv with pyserial --
    create_venv "$prefix"

    # -- verify --
    "$prefix/.venv/bin/python" -c "import serial; print(f'pyserial {serial.VERSION}')"
    info "Dependencies OK"

    # -- data directory (on NFS, created by mount) --

    # -- wrapper scripts --
    info "Installing CLI wrappers to /usr/local/bin..."

    cat > /usr/local/bin/modbus-detect <<EOF
#!/usr/bin/env bash
exec ${prefix}/.venv/bin/python ${prefix}/modbus_detect.py "\$@"
EOF
    chmod +x /usr/local/bin/modbus-detect

    cat > /usr/local/bin/modbus-sniffer <<EOF
#!/usr/bin/env bash
# Default database location for persistent storage
export MODBUS_DB="${DB_DIR}/modbus_capture.db"
cmd="\${1:-capture}"
if [[ "\$cmd" == "capture" ]]; then
    exec ${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py capture --db "\$MODBUS_DB" "\${@:2}"
elif [[ "\$cmd" == "analyze" ]]; then
    exec ${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py analyze --db "\$MODBUS_DB" "\${@:2}"
elif [[ "\$cmd" == "export" ]]; then
    exec ${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py export --db "\$MODBUS_DB" "\${@:2}"
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
    else
        info "No NFS_SHARE set, using local storage at $MOUNT_POINT"
        mkdir -p "$MOUNT_POINT"
        chown "$INSTALL_USER":"$INSTALL_USER" "$MOUNT_POINT"
    fi

    # -- systemd service --
    info "Installing systemd service..."

    local nfs_deps=""
    if [[ -n "$NFS_SHARE" ]]; then
        nfs_deps="After=dev-heatpump.device $MOUNT_UNIT
BindsTo=dev-heatpump.device
Requires=$MOUNT_UNIT"
    else
        nfs_deps="After=dev-heatpump.device
BindsTo=dev-heatpump.device"
    fi

    cat > /etc/systemd/system/modbus-sniffer.service <<SVC_EOF
[Unit]
Description=Modbus RTU bus sniffer (passive capture)
${nfs_deps}

[Service]
Type=simple
User=$INSTALL_USER
ExecStartPre=+/bin/bash -c 'DEV=\$(readlink -f /dev/heatpump); TTYNAME=\$(basename \$DEV); echo 1 > /sys/bus/usb-serial/devices/\$TTYNAME/latency_timer'
ExecStart=${prefix}/.venv/bin/python ${prefix}/modbus_sniffer.py capture --port /dev/heatpump --baud 9600 --stopbits 2 --parity N --db ${DB_DIR}/modbus_capture.db
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVC_EOF
    systemctl daemon-reload
    systemctl enable modbus-sniffer
    info "Service installed (not started). Use: sudo systemctl start modbus-sniffer"

    echo ""
    info "Installation complete."
    echo ""
    echo "  Start service:      sudo systemctl start modbus-sniffer"
    echo "  Service status:     sudo systemctl status modbus-sniffer"
    echo "  Service logs:       journalctl -u modbus-sniffer -f"
    echo ""
    echo "  Detect bus params:  modbus-detect --port /dev/modbus_sniff"
    echo "  Manual capture:     modbus-sniffer capture --auto-detect"
    echo "  Analyze data:       modbus-sniffer analyze"
    echo "  Export CSV:          modbus-sniffer export --format csv"
    echo ""
    echo "  Database:  $DB_DIR/modbus_capture.db"
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
