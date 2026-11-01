#!/usr/bin/env bash
# Install VOICEVOX CORE (offline, high-quality Japanese TTS) for build_reel.py.
# Usage: bash setup_voicevox.sh <style_id>     e.g. bash setup_voicevox.sh 20
# Downloads only the voice model (.vvm) that contains the given voice.
set -euo pipefail
STYLE="${1:-20}"
DIR="${VOICEVOX_DIR:-$HOME/.cache/voicevox}"
G=https://github.com
VER=0.16.0
ORT=1.17.3
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR"; cd "$DIR"

python3 -c "import voicevox_core" 2>/dev/null || {
  curl -sSLO "$G/VOICEVOX/voicevox_core/releases/download/$VER/voicevox_core-$VER-cp310-abi3-manylinux_2_34_x86_64.whl"
  pip install "voicevox_core-$VER-cp310-abi3-manylinux_2_34_x86_64.whl" --break-system-packages -q
}
[ -d "voicevox_onnxruntime-linux-x64-$ORT" ] || {
  curl -sSL "$G/VOICEVOX/onnxruntime-builder/releases/download/voicevox_onnxruntime-$ORT/voicevox_onnxruntime-linux-x64-$ORT.tgz" | tar xz
}
[ -d open_jtalk_dic_utf_8-1.11 ] || {
  curl -sSL "$G/r9y9/open_jtalk/releases/download/v1.11.1/open_jtalk_dic_utf_8-1.11.tar.gz" | tar xz
}
VVM=$(python3 -c "import sys; sys.path.insert(0,'$HERE'); from voices import VOICES; print(VOICES[$STYLE][0])")
mkdir -p vvms
[ -f "vvms/$VVM.vvm" ] || curl -sSL -o "vvms/$VVM.vvm" "$G/VOICEVOX/voicevox_vvm/releases/download/$VER/$VVM.vvm"
echo "VOICEVOX ready in $DIR (voice $STYLE -> $VVM.vvm)"
