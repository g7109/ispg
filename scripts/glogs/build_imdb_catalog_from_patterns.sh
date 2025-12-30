#!/bin/bash
set -eu
set -o pipefail

input=$(realpath $1)

workspace=$(realpath $(dirname $0)/../../)
output_dir=$workspace/catalogs/imdb/glogs
mkdir -p $output_dir
output=$output_dir/imdb.bincode

$workspace/glogs/ir/target/release/build_catalog_from_patterns -i $input -o $output
