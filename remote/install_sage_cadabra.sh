#!/usr/bin/env bash
set -euo pipefail

MINIFORGE_DIR="${MINIFORGE_DIR:-$HOME/miniforge3}"
SAGE_ENV="${SAGE_ENV:-sage}"
BIN_DIR="$HOME/bin"
APP_DIR="$HOME/Applications"

mkdir -p "$BIN_DIR" "$APP_DIR"

if [[ ! -x "$MINIFORGE_DIR/bin/conda" ]]; then
  installer="/tmp/Miniforge3-$(uname)-$(uname -m).sh"
  curl -L -o "$installer" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
  bash "$installer" -b -p "$MINIFORGE_DIR"
fi

source "$MINIFORGE_DIR/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "$SAGE_ENV"; then
  conda create -y -n "$SAGE_ENV" sage python=3.11
else
  conda install -y -n "$SAGE_ENV" sage python=3.11
fi

"$MINIFORGE_DIR/envs/$SAGE_ENV/bin/sage" --version

python3 - <<'PY'
import json
import os
import stat
import urllib.request
from pathlib import Path

api = "https://api.github.com/repos/kpeeters/cadabra2/releases/latest"
with urllib.request.urlopen(api, timeout=60) as response:
    release = json.load(response)

assets = release.get("assets", [])
appimages = [
    asset for asset in assets
    if asset.get("name", "").lower().endswith(".appimage")
    and "x86_64" in asset.get("name", "").lower()
]
if not appimages:
    raise SystemExit("No x86_64 Cadabra AppImage asset found in latest release.")

asset = appimages[0]
target = Path.home() / "Applications" / asset["name"]
url = asset["browser_download_url"]
print(f"Downloading {asset['name']} from {release.get('tag_name', 'latest')}")
urllib.request.urlretrieve(url, target)
target.chmod(target.stat().st_mode | stat.S_IXUSR)

link = Path.home() / "bin" / "cadabra2"
print(target)
PY

cd "$APP_DIR"
extracted="$APP_DIR/Cadabra_2.5.14_x86_64_extracted"
if [[ ! -d "$extracted" ]]; then
  rm -rf squashfs-root
  "$APP_DIR/Cadabra_2.5.14_x86_64.AppImage" --appimage-extract >/tmp/cadabra_extract.log 2>&1
  mv squashfs-root "$extracted"
fi

cat > "$BIN_DIR/cadabra2" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

ROOT="${CADABRA_APPDIR:-$HOME/Applications/Cadabra_2.5.14_x86_64_extracted}"
LOADER="$ROOT/runtime/default/lib64/ld-linux-x86-64.so.2"
LIB_PATH="$ROOT/usr/lib/x86_64-linux-gnu:$ROOT/usr/lib:$ROOT/runtime/default/lib/x86_64-linux-gnu:$ROOT/runtime/default/lib"

export PATH="$ROOT/usr/bin:$PATH"
export PYTHONPATH="$ROOT/usr/lib/python3/dist-packages:$ROOT/usr/lib/python3.10/dist-packages:${PYTHONPATH:-}"

exec "$LOADER" --library-path "$LIB_PATH" "$ROOT/usr/bin/cadabra2-cli" "$@"
SH
chmod +x "$BIN_DIR/cadabra2"

"$BIN_DIR/cadabra2" --version

cat <<EOF
Sage/Cadabra install finished.
Sage:    $MINIFORGE_DIR/envs/$SAGE_ENV/bin/sage
Cadabra: $BIN_DIR/cadabra2
EOF
