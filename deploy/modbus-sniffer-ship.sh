#!/usr/bin/env bash
# Ship the Modbus sniffer's finished days from the local cache to the NAS.
#
# Runs once a day from modbus-sniffer-ship.timer, inside the NAS write
# window, so the disks see the sniffer exactly once a day. Every completed
# UTC day under the cache is appended to one daily file on the NAS
# (concatenated gzip members are a valid gzip file), fsynced, and only then
# deleted locally. If the share is unreachable the cache simply keeps the
# days and the next run catches up.
#
# Environment:
#   SNIFFER_STATE   state directory (default /var/lib/modbus-sniffer)
#   SNIFFER_DEST    NAS directory   (default /mnt/nas/modbus)
set -euo pipefail

STATE="${SNIFFER_STATE:-/var/lib/modbus-sniffer}"
DEST="${SNIFFER_DEST:-/mnt/nas/modbus}"
CACHE="$STATE/cache"

if ! mountpoint -q "$DEST"; then
    echo "ship: $DEST is not mounted, keeping cache" >&2
    exit 1
fi

today="$(date -u +%F)"
shipped=0

shopt -s nullglob
for daydir in "$CACHE"/????-??-??; do
    [[ -d "$daydir" ]] || continue
    day="$(basename "$daydir")"
    # Only completed UTC days; today's chunks are still being written.
    [[ "$day" < "$today" ]] || continue

    chunks=("$daydir"/*.gz)
    if (( ${#chunks[@]} == 0 )); then
        rmdir "$daydir"
        continue
    fi

    dest="$DEST/${day:0:4}/${day:5:2}/$day.frames.gz"
    mkdir -p "$(dirname "$dest")"
    cat "${chunks[@]}" >> "$dest"
    sync "$dest"
    rm -rf "$daydir"
    echo "ship: $day -> $dest (${#chunks[@]} chunks, $(stat -c %s "$dest") bytes)"
    shipped=$((shipped + 1))
done
shopt -u nullglob

# The alerts log is tiny; copy it only when it changed since the last ship.
if [[ -f "$STATE/alerts.log" ]] && [[ ! -f "$DEST/alerts.log" || "$STATE/alerts.log" -nt "$DEST/alerts.log" ]]; then
    cp -p "$STATE/alerts.log" "$DEST/alerts.log"
    sync "$DEST/alerts.log"
    echo "ship: alerts.log updated"
fi

echo "ship: $shipped day(s) shipped"
