#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Endowment Accounting Software — Startup Script
# ─────────────────────────────────────────────────────────────

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/app"

echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│     Endowment Accounting Software           │"
echo "│     Fund Management Platform                │"
echo "└─────────────────────────────────────────────┘"
echo ""

# Install dependencies if needed
if ! python3 -c "import flask" 2>/dev/null; then
  echo "→ Installing dependencies..."
  pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet --break-system-packages 2>/dev/null \
    || pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet
fi

echo "→ Starting server at http://localhost:5000"
echo ""
echo "  Default login:"
echo "    Username: admin"
echo "    Password: Admin1234!"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

cd "$APP_DIR"
python3 app.py
