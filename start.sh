#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR"

PORT=$(python3 -c "import yaml; d=yaml.safe_load(open('config/settings.yaml')); print(d['app']['port'])" 2>/dev/null || echo "8800")

echo "domainSync running on http://localhost:$PORT"
echo "   API docs: http://localhost:$PORT/api/docs"
echo "   Press Ctrl+C to stop"
echo ""

uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" --log-level warning
