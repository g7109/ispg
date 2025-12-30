#!/usr/bin/env bash
set -euo pipefail

SF="${1:-0.003}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(realpath "${SCRIPT_DIR}/../..")"

INPUT_DIR="${WORKSPACE}/datasets/ldbc/sf${SF}_vid"
STORAGE_SCHEMA="${WORKSPACE}/schemas/dummy_schema.json"
LDBC_SCHEMA="${WORKSPACE}/ispg/ldbc/ldbc_glogs_schema.json"
OUTPUT_DIR="${WORKSPACE}/graphs/ldbc_small/glogs"
OUTPUT_PATH="${OUTPUT_DIR}/ldbc_sf${SF}"

if [[ ! -d "${INPUT_DIR}" ]]; then
  echo "[ERROR] Flattened dataset not found: ${INPUT_DIR}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

echo "[INFO] Building GLogS graph for LDBC sf${SF}"
"${WORKSPACE}/glogs/ir/target/release/build_graph" \
  --schema1 "${LDBC_SCHEMA}" \
  --schema2 "${STORAGE_SCHEMA}" \
  --delimiter '|' \
  -d "${INPUT_DIR}" \
  -o "${OUTPUT_PATH}"
