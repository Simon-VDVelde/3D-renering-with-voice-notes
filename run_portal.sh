#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL_DIR="$SCRIPT_DIR/tool"

# Zorg dat de python environment gebruikt wordt
if [ -d "$TOOL_DIR/.venv" ]; then
    source "$TOOL_DIR/.venv/bin/activate"
fi

PORT=${PORT:-8080}

echo "=========================================================="
echo "🚀 SPATIAL SOP — ENTERPRISE B2B WEB PORTAL"
echo "=========================================================="
echo "Open je browser op:"
echo "👉 http://localhost:$PORT"
echo ""
echo "📱 Tip: Om de portal op je smartphone te openen, gebruik je lokale IP:"
echo "👉 http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT"
echo "=========================================================="

python3 "$TOOL_DIR/server.py"
