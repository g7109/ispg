#!/bin/bash
set -eu
set -o pipefail

outdir=$(pwd)/$1

workspace=$(realpath $(dirname $0)/../../)

SCHEMA_PATH=$workspace/schemas/imdb/imdb_glogs_schema.json \
    $workspace/glogs/ir/target/release/generate_catalog_patterns -o $outdir
