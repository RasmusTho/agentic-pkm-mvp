#!/usr/bin/env bash
# Mac mini = the always-on core: Ollama (embeddings + small chat) + the llm-gateway.
# Idempotent: safe to re-run. Run from anywhere; paths are resolved absolutely.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

# 1. Config -----------------------------------------------------------------
if [ ! -f "$ROOT/config.env" ]; then
  cp "$ROOT/config.example.env" "$ROOT/config.env"
  echo "Created $ROOT/config.env from the example — edit hosts/models if needed."
fi
set -a; . "$ROOT/config.env"; set +a

# 2. Ollama + models --------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama via Homebrew..."
  brew install ollama
fi
brew services start ollama >/dev/null 2>&1 || true
sleep 2
echo "Pulling models (this can take a while)..."
ollama pull "$EMBED_MODEL"
ollama pull "$MINI_CHAT_MODEL"

# 3. Gateway venv -----------------------------------------------------------
python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q --upgrade pip
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
chmod +x "$HERE/run_gateway.sh"

# 4. launchd service --------------------------------------------------------
PLIST="$HOME/Library/LaunchAgents/com.yggdrasil.llm-gateway.plist"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s#__RUN__#$HERE/run_gateway.sh#g" "$HERE/com.yggdrasil.llm-gateway.plist" >"$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 2

# 5. Verify + next steps ----------------------------------------------------
echo
echo "== Gateway health =="
curl -sS "http://127.0.0.1:${GATEWAY_PORT:-11500}/healthz" || echo "(gateway not answering yet — check /tmp/yggdrasil-llm-gateway.err)"
echo
echo "Done. Point Yggdrasil at the gateway by setting in your .env:"
echo "    LLM_PROVIDER=ollama"
echo "    OLLAMA_URL=http://127.0.0.1:${GATEWAY_PORT:-11500}"
echo "    OLLAMA_EMBED_MODEL=${EMBED_MODEL}"
echo "    LLM_MODEL=${MINI_CHAT_MODEL}"
