#!/usr/bin/env bash
set -euo pipefail

SF="${1:-0.003}"
THREADS="${2:-32}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(realpath "${SCRIPT_DIR}/../..")"

GRAPH_PATH="${WORKSPACE}/graphs/ldbc_small/glogs/ldbc_sf${SF}"
SCHEMA_PATH="${WORKSPACE}/ispg/ldbc/ldbc_glogs_schema.json"
CATALOG_DIR="${WORKSPACE}/catalogs/ldbc_small/glogs"
OUTPUT_PATH="${CATALOG_DIR}/ldbc_sf${SF}.bincode"

if [[ ! -d "${GRAPH_PATH}" ]]; then
	echo "[ERROR] Graph directory not found: ${GRAPH_PATH}" >&2
	exit 1
fi

mkdir -p "${CATALOG_DIR}"

echo "[INFO] Building GLogS catalog for LDBC sf${SF} with ${THREADS} threads"
SCHEMA_PATH="${SCHEMA_PATH}" \
SAMPLE_PATH="${GRAPH_PATH}" \
"${WORKSPACE}/glogs/ir/target/release/build_catalog" \
	-m from_meta \
	-t "${THREADS}" \
	-p "${OUTPUT_PATH}"
