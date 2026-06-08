#!/usr/bin/env bash
# setup.sh — one-shot deployment script for ISPG
# Run from the repository root: bash setup.sh
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKSPACE"

# ── 1. Prerequisites check ──────────────────────────────────────────────────

require_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "[ERROR] Required command not found: $1" >&2
        echo "        Please install it and re-run setup.sh." >&2
        exit 1
    fi
}

require_cmd python3
require_cmd cargo

echo "[INFO] Python: $(python3 --version)"
echo "[INFO] Cargo:  $(cargo --version)"

# ── 2. Build GLogS Rust binaries ────────────────────────────────────────────

GLOGS_BIN="$WORKSPACE/glogs/ir/target/release"

if [ ! -f "$GLOGS_BIN/pattern_count" ]; then
    echo "[INFO] Building GLogS binaries (this may take a few minutes)..."
    (cd glogs/ir && cargo build --release 2>&1)
    echo "[INFO] GLogS build complete."
else
    echo "[INFO] GLogS binaries already present, skipping build."
fi

echo "[INFO] Verifying GLogS binaries..."
for bin in pattern_count build_graph build_catalog; do
    if [ ! -f "$GLOGS_BIN/$bin" ]; then
        echo "[ERROR] Missing binary: $GLOGS_BIN/$bin" >&2
        exit 1
    fi
done
echo "[INFO] GLogS binaries OK."

# ── 3. Make wrapper scripts executable ──────────────────────────────────────

chmod +x scripts/glogs/estimate.sh 2>/dev/null || true

# ── 4. Python virtual environment ───────────────────────────────────────────

if [ ! -d ".venv" ]; then
    echo "[INFO] Creating Python virtual environment..."
    python3 -m venv .venv
fi

echo "[INFO] Installing Python dependencies..."
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "[INFO] Python environment ready."

# ── 5. Verify catalog ───────────────────────────────────────────────────────

LDBC_CATALOG="$WORKSPACE/catalogs/ldbc_small/glogs/ldbc_sf0.003.bincode"
if [ -f "$LDBC_CATALOG" ]; then
    echo "[INFO] LDBC catalog found: $LDBC_CATALOG"
else
    echo ""
    echo "[WARN] LDBC catalog not found: $LDBC_CATALOG"
    echo "       To build it, prepare datasets/ldbc/sf0.003_vid/ and run:"
    echo "         bash ispg/ldbc/build_ldbc_small_graph.sh 0.003"
    echo "         bash ispg/ldbc/build_ldbc_small_catalog.sh 0.003 32"
fi

# ── 6. Summary ──────────────────────────────────────────────────────────────

echo ""
echo "┌──────────────────────────────────────────────────────┐"
echo "│  ISPG setup complete.                                │"
echo "│                                                      │"
echo "│  Activate the environment:                           │"
echo "│    source .venv/bin/activate                         │"
echo "│                                                      │"
echo "│  Run the LDBC IC optimizer:                          │"
echo "│    python ispg/ldbc/ic/ldbc_query_optimizer.py --all │"
echo "│                                                      │"
echo "│  Run a single query:                                 │"
echo "│    python ispg/ldbc/ic/ldbc_query_optimizer.py \\     │"
echo "│      --query ic-1                                    │"
echo "└──────────────────────────────────────────────────────┘"
