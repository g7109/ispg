#!/bin/bash
set -eu
set -o pipefail

threads=$1

workspace=$(realpath $(dirname $0)/../../)
output_dir=$workspace/catalogs/aids_merged/glogs
mkdir -p $output_dir
output=$output_dir/aids_merged.bincode

SCHEMA_PATH=$workspace/schemas/aids_merged/aids_merged_glogs_schema.json \
SAMPLE_PATH=$workspace/graphs/aids_merged/glogs/aids_merged \
$workspace/glogs/ir/target/release/build_catalog -m from_meta -t $threads -p $output