#!/bin/bash
set -eu
set -o pipefail

# Build GLogS graph from aids_merged dataset

workspace=$(realpath $(dirname $0)/../../)

storage_schema=$workspace/schemas/dummy_schema.json
schema=$workspace/schemas/aids_merged/aids_merged_glogs_schema.json
input=$workspace/datasets/aids_merged/aids_merged
output=$workspace/graphs/aids_merged/glogs/aids_merged

$workspace/glogs/ir/target/release/build_graph --schema1 $schema --schema2 $storage_schema -d $input -o $output