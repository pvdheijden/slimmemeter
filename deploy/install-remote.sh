#!/usr/bin/env bash
#
# Install or upgrade slimmemeter on a Raspberry Pi over SSH, from this checkout of the
# repository. Copies the working tree (including uncommitted changes, without doc/) to the
# Pi and runs deploy/setup.sh there with sudo.
#
#   deploy/install-remote.sh [user@]host [service-user]
#
# service-user runs the P1-data and weather clients, default the SSH login user.
# SSH options such as a key or port go in ~/.ssh/config.

set -euo pipefail

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "usage: $0 [user@]host [service-user]" >&2
    exit 2
fi
HOST=$1
REPO=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)

# One SSH connection for all steps, so a password is asked only once
CONTROL_DIR=$(mktemp -d)
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$CONTROL_DIR/%C" -o ControlPersist=10m)
cleanup() {
    "${SSH[@]}" -O exit "$HOST" 2>/dev/null || true
    rm -rf "$CONTROL_DIR"
}
trap cleanup EXIT

SERVICE_USER=${2:-$("${SSH[@]}" "$HOST" 'id -un')}

VERSION=$(git -C "$REPO" describe --always --dirty)
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
    echo "note: deploying uncommitted changes ($VERSION)"
fi

echo "==> Copying slimmemeter $VERSION to $HOST"
STAGE=$("${SSH[@]}" "$HOST" 'mktemp -d /tmp/slimmemeter.XXXXXX')
# Tracked and new files, leaving out ignored files, deleted files and the documentation
(
    cd "$REPO"
    git ls-files -z --cached --others --exclude-standard \
        | while IFS= read -r -d '' file; do
            [ -f "$file" ] && [[ $file != doc/* ]] && printf '%s\0' "$file"
        done \
        | tar --null -T - -czf -
) | "${SSH[@]}" "$HOST" "tar xzf - -C $STAGE && echo $(printf '%q' "$VERSION") > $STAGE/DEPLOYED"

echo "==> Running the installation on $HOST as root, services run as $SERVICE_USER"
"${SSH[@]}" -t "$HOST" \
    "sudo bash $STAGE/deploy/setup.sh $(printf '%q' "$SERVICE_USER"); status=\$?; rm -rf $STAGE; exit \$status"
