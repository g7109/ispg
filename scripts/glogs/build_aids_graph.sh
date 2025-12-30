#!/bin/bash
set -eu
set -o pipefail

# Build GLogS graph from aids dataset

workspace=$(realpath $(dirname $0)/../../)

storage_schema=$workspace/schemas/dummy_schema.json
schema=$workspace/schemas/aids/aids_glogs_schema.json
input=$workspace/datasets/aids/aids
output=$workspace/graphs/aids/glogs/aids

$workspace/glogs/ir/target/release/build_graph --schema1 $schema --schema2 $storage_schema -d $input -o $output