#!/usr/bin/env bash
# Interactive administrator step: install fingerprint-level SSH audit logging.
set -euo pipefail

SOURCE="${1:-$HOME/astra-worker/90-astra-audit.conf}"
TARGET="/etc/ssh/sshd_config.d/90-astra-audit.conf"
BACKUP="$HOME/astra-worker/90-astra-audit.conf.previous"

[ -f "$SOURCE" ] || { echo "missing source: $SOURCE" >&2; exit 2; }

had_previous=0
if sudo test -f "$TARGET"; then
  sudo cp -- "$TARGET" "$BACKUP"
  sudo chown "$(id -u):$(id -g)" "$BACKUP"
  had_previous=1
fi

sudo install -o root -g root -m 0644 "$SOURCE" "$TARGET"
if ! sudo sshd -t; then
  echo "sshd validation failed; restoring the previous state" >&2
  if [ "$had_previous" -eq 1 ]; then
    sudo install -o root -g root -m 0644 "$BACKUP" "$TARGET"
  else
    sudo rm -f -- "$TARGET"
  fi
  exit 3
fi

sudo systemctl reload ssh
sudo sshd -T | grep '^loglevel '
echo "SSH audit configuration installed and ssh reloaded."
