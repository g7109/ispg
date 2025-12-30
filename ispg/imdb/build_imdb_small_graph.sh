#!/bin/bash
set -eu
set -o pipefail

# Build GLogS graph from *small* IMDB dataset

workspace=$(realpath $(dirname $0)/../../)

storage_schema=$workspace/schemas/dummy_schema.json
schema=$workspace/ispg/imdb/imdb_small_glogs_schema.json
input=$workspace/ispg/imdb/imdb_small_bfs_vid
output=$workspace/graphs/imdb_small/glogs/imdb_small

mkdir -p "$(dirname "$output")"

$workspace/glogs/ir/target/release/build_graph \
  --schema1 "$schema" \
  --schema2 "$storage_schema" \
  -d "$input" \
  -o "$output"
