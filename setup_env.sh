set -euo pipefail

if [ "${1:-}" = "--recreate" ]; then
  rm -rf venv
fi

if [ ! -d venv ]; then
  python -m venv venv
fi

source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt
fi

if [ -f requirements-dev.txt ]; then
  python -m pip install -r requirements-dev.txt
fi

python -m pip install -e .
