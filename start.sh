#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "import yaml; d=yaml.safe_load(open('config/settings.yaml')); print(d['app']['port'])" 2>/dev/null || echo "8800")
CERT="$SCRIPT_DIR/certs/cert.pem"
KEY="$SCRIPT_DIR/certs/key.pem"

echo "domainSync running on https://localhost:$PORT"
echo "   API docs: https://localhost:$PORT/api/docs"
echo "   Press Ctrl+C to stop"
echo ""

# --timeout-keep-alive 75: uvicorn's 5s default closes idle keep-alive sockets
# while the browser is still reusing them, which surfaces as intermittent
# "Load failed" on the next request (e.g. saving a form after typing a while).
if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" \
    --ssl-certfile "$CERT" --ssl-keyfile "$KEY" \
    --timeout-keep-alive 75 --log-level warning
else
  uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" \
    --timeout-keep-alive 75 --log-level warning
fi
