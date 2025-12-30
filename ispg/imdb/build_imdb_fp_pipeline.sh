#!/usr/bin/env bash
set -euo pipefail

# ===============================
# Argument parsing
# ===============================
RATIO="${1:-0.00035}"   # Arg1: induced subgraph ratio (default: 0.00035)
THREADS="${2:-32}"      # Arg2: build_catalog threads (default: 32)

echo "[INFO] Using ratio = ${RATIO}, threads = ${THREADS}"

# ===============================
# Paths
# ===============================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" # Current script directory: .../ispg/imdb
# Repo root: .../ispg
WORKSPACE="$(realpath "${SCRIPT_DIR}/../..")"

INPUT_DIR="${WORKSPACE}/datasets/imdb/imdb"
SAMPLE_DIR="${WORKSPACE}/ispg/imdb/imdb_small_bfs"
VID_DIR="${WORKSPACE}/ispg/imdb/imdb_small_bfs_vid"

SMALL_SCHEMA="${WORKSPACE}/ispg/imdb/imdb_small_glogs_schema.json"
IMDB_SCHEMA="${WORKSPACE}/schemas/imdb/imdb_glogs_schema.json"

GRAPH_DIR="${WORKSPACE}/graphs/imdb_small/glogs"
CATALOG_DIR="${WORKSPACE}/catalogs/imdb_small/glogs"
BINCODE_PATH="${CATALOG_DIR}/imdb_small.bincode"

mkdir -p "${SAMPLE_DIR}" "${VID_DIR}" "${GRAPH_DIR}" "${CATALOG_DIR}"

echo "[INFO] WORKSPACE     = ${WORKSPACE}"
echo "[INFO] INPUT_DIR     = ${INPUT_DIR}"
echo "[INFO] SAMPLE_DIR    = ${SAMPLE_DIR}"
echo "[INFO] VID_DIR       = ${VID_DIR}"
echo "[INFO] GRAPH_DIR     = ${GRAPH_DIR}"
echo "[INFO] CATALOG_DIR   = ${CATALOG_DIR}"
echo "[INFO] BINCODE_PATH  = ${BINCODE_PATH}"

# ===============================
# Step 1: sample induced subgraph
# ===============================
echo "[STEP 1] Sampling induced subgraph with ratio=${RATIO} ..."
source "${WORKSPACE}/.venv/bin/activate"

python "${WORKSPACE}/ispg/imdb/imdb_sample_induced_bfs.py" \
  --input-dir "${INPUT_DIR}" \
  --output-dir "${SAMPLE_DIR}" \
  --ratio "${RATIO}"

echo "[STEP 1] Done."

# ===============================
# Step 2: reassign global VIDs (LDBC style)
# ===============================
echo "[STEP 2] Reassign global VID (LDBC style) ..."
python "${WORKSPACE}/ispg/imdb/imdb_reassign_vid_ldbc_style.py" \
  --input-dir "${SAMPLE_DIR}" \
  --output-dir "${VID_DIR}" \
  --schema "${IMDB_SCHEMA}"

echo "[STEP 2] Done."

# ===============================
# Step 3: build graph (GLogS graph)
# ===============================
echo "[STEP 3] Build GLogS graph on sampled IMDB ..."
bash "${WORKSPACE}/ispg/imdb/build_imdb_small_graph.sh"

echo "[STEP 3] Done."

# ===============================
# Step 4: build catalog (statistics)
# ===============================
echo "[STEP 4] Build GLogS catalog (bincode) with threads=${THREADS} ..."
bash "${WORKSPACE}/ispg/imdb/build_imdb_small_catalog.sh" "${THREADS}"

echo "[STEP 4] Done."

echo "[ALL DONE] Catalog ready at: ${BINCODE_PATH}"
echo "           Point the optimizer's GLogSEstimator to this bincode to use the FP-based estimates."
