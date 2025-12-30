#!/bin/bash
set -eu
set -o pipefail

threads=$1

workspace=$(realpath $(dirname $0)/../../)
output_dir=$workspace/catalogs/aids/glogs
mkdir -p $output_dir
output=$output_dir/aids.bincode

SCHEMA_PATH=$workspace/schemas/aids/aids_glogs_schema.json \
SAMPLE_PATH=$workspace/graphs/aids/glogs/aids \
$workspace/glogs/ir/target/release/build_catalog -m from_meta -t $threads -p $output