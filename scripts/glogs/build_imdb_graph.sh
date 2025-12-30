#!/bin/bash
set -eu
set -o pipefail

# Build GLogS graph from IMDB dataset

workspace=$(realpath $(dirname $0)/../../)

storage_schema=$workspace/schemas/dummy_schema.json
schema=$workspace/schemas/imdb/imdb_glogs_schema.json
input=$workspace/datasets/imdb/imdb_unique_vid
output=$workspace/graphs/imdb/glogs/imdb

$workspace/glogs/ir/target/release/build_graph --schema1 $schema --schema2 $storage_schema -d $input -o $output