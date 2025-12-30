#!/bin/bash
set -eu
set -o pipefail

threads=${1:-32}   # Default: 32 threads

workspace=$(realpath $(dirname $0)/../../)

output_dir=$workspace/catalogs/imdb_small/glogs
mkdir -p "$output_dir"
output=$output_dir/imdb_small.bincode

# Schema and graph paths for the small graph
SCHEMA_PATH=$workspace/ispg/imdb/imdb_small_glogs_schema.json \
SAMPLE_PATH=$workspace/graphs/imdb_small/glogs/imdb_small \
$workspace/glogs/ir/target/release/build_catalog \
  -m from_meta \
  -t "$threads" \
  -p "$output"
