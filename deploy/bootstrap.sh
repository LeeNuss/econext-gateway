#!/usr/bin/env bash
#
# Bootstrap installer for ecoNEXT Gateway.
#
# Downloads the latest (or specified) release bundle from GitHub
# and runs the install script.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LeeNuss/econext-gateway/main/deploy/bootstrap.sh | sudo bash
#   curl -fsSL ... | sudo bash -s -- --version 0.2.0
#   curl -fsSL ... | sudo bash -s -- --pre
#

set -euo pipefail

REPO="LeeNuss/econext-gateway"
VERSION=""
PRE_RELEASE=false
TMPDIR=""

info()  { echo "==> $*"; }
die()   { echo "ERROR: $*" >&2; exit 1; }

cleanup() {
    [[ -n "$TMPDIR" && -d "$TMPDIR" ]] && rm -rf "$TMPDIR"
}
trap cleanup EXIT

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version|-v)
            VERSION="$2"
            shift 2
            ;;
        --pre|--prerelease)
            PRE_RELEASE=true
            shift
            ;;
        --help|-h)
            echo "Usage: bootstrap.sh [--version VERSION] [--pre]"
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

# Must be root
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root (use sudo)"
fi

# Check deps
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

# Resolve version
if [[ -z "$VERSION" ]]; then
    if [[ "$PRE_RELEASE" == true ]]; then
        info "Fetching latest pre-release..."
        VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases" \
            | grep '"tag_name"' | head -1 | sed -E 's/.*"v([^"]+)".*/\1/')
    else
        info "Fetching latest release..."
        VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
    fi
    [[ -n "$VERSION" ]] || die "Could not determine latest version"
fi
info "Installing version ${VERSION}"

# Download bundle
BUNDLE_URL="https://github.com/${REPO}/releases/download/v${VERSION}/gateway-bundle-${VERSION}.tar.gz"
TMPDIR="$(mktemp -d)"

info "Downloading ${BUNDLE_URL}..."
curl -fsSL "$BUNDLE_URL" -o "${TMPDIR}/bundle.tar.gz" || die "Download failed. Check that version ${VERSION} exists."

info "Extracting..."
tar -xzf "${TMPDIR}/bundle.tar.gz" -C "$TMPDIR"

# Find the wheel
WHEEL=$(ls "${TMPDIR}"/*.whl 2>/dev/null | head -1)
[[ -n "$WHEEL" ]] || die "No wheel found in bundle"

# Run install script with the wheel
export ECONEXT_WHEEL="$WHEEL"
bash "${TMPDIR}/deploy/install.sh"
