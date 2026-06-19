#!/usr/bin/env bash
# Fetch the local TTS voice models for Companion UI read-back into a target dir,
# in the on-disk layout that app/tts/providers.py expects. Run on the host that
# owns the external SSD (e.g. the Mac mini). Models are NEVER committed to the repo.
#
# Usage: scripts/fetch_tts_models.sh /Volumes/T7/CompanionData/tts/models
#
# Override sources via env if upstream paths change:
#   PIPER_SV_ONNX_URL, PIPER_SV_JSON_URL, KOKORO_ONNX_URL, KOKORO_VOICES_URL
# Override the Swedish Piper voice id (must match TTS_SV_VOICE used by the app):
#   TTS_SV_VOICE=sv_SE-nst-medium scripts/fetch_tts_models.sh <models-dir>
set -euo pipefail

DEST="${1:?usage: fetch_tts_models.sh <models-dir>}"
# Swedish Piper voice id — mirrors TTS_SV_VOICE / TTSConfig.sv_voice so a custom
# voice lands exactly where resolve_voice() probes: <models>/piper/<id>/<id>.onnx.
PIPER_SV_VOICE="${TTS_SV_VOICE:-sv_SE-lisa-medium}"
PIPER_DIR="$DEST/piper/$PIPER_SV_VOICE"
KOKORO_DIR="$DEST/kokoro"

PIPER_SV_ONNX_URL="${PIPER_SV_ONNX_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main/sv/sv_SE/lisa/medium/sv_SE-lisa-medium.onnx}"
PIPER_SV_JSON_URL="${PIPER_SV_JSON_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main/sv/sv_SE/lisa/medium/sv_SE-lisa-medium.onnx.json}"
KOKORO_ONNX_URL="${KOKORO_ONNX_URL:-https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx}"
KOKORO_VOICES_URL="${KOKORO_VOICES_URL:-https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin}"

fetch() { # url out
  local url="$1" out="$2"
  if [[ -s "$out" ]]; then echo "exists, skip: $out"; return 0; fi
  echo "downloading: $url"
  curl -fSL --retry 3 -o "$out.part" "$url"
  mv "$out.part" "$out"
  [[ -s "$out" ]] || { echo "ERROR: empty download $out" >&2; exit 1; }
}

mkdir -p "$PIPER_DIR" "$KOKORO_DIR"
fetch "$PIPER_SV_ONNX_URL" "$PIPER_DIR/$PIPER_SV_VOICE.onnx"
fetch "$PIPER_SV_JSON_URL" "$PIPER_DIR/$PIPER_SV_VOICE.onnx.json"
fetch "$KOKORO_ONNX_URL"   "$KOKORO_DIR/kokoro-v1.0.int8.onnx"
fetch "$KOKORO_VOICES_URL" "$KOKORO_DIR/voices-v1.0.bin"

echo "OK. Installed:"
ls -la "$PIPER_DIR" "$KOKORO_DIR"
echo "NOTE: confirm upstream URLs/checksums on first run; pin checksums once verified."
