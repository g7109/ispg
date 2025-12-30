#!/bin/bash
set -eu
set -o pipefail

threads=$1

workspace=$(realpath $(dirname $0)/../../)
output_dir=$workspace/catalogs/imdb/glogs
mkdir -p $output_dir
output=$output_dir/imdb.bincode

SCHEMA_PATH=$workspace/schemas/imdb/imdb_glogs_schema.json \
SAMPLE_PATH=$workspace/graphs/imdb/glogs/imdb \
$workspace/glogs/ir/target/release/build_catalog -m from_meta -t $threads -p $output