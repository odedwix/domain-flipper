#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "═══════════════════════════════════════════"
echo "  Domain Flipper — Starting up"
echo "═══════════════════════════════════════════"

# Check .env exists
if [ ! -f .env ]; then
  echo "  → No .env found. Copying .env.example → .env"
  cp .env.example .env
  echo "  → Edit .env to add your API keys before running live scans."
fi

# Install deps
echo "  → Installing Python dependencies…"
pip install -r requirements.txt --quiet

# Download NLTK words corpus
echo "  → Ensuring NLTK data…"
python -c "import nltk; nltk.download('words', quiet=True)" 2>/dev/null || true

# Start server
echo ""
echo "  ✓ Open http://localhost:8000 in your browser"
echo "  ✓ Click 'Demo Data' to load sample domains instantly"
echo "  ✓ Press Ctrl+C to stop"
echo ""
cd backend
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
