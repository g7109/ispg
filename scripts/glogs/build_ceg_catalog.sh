#!/bin/bash
set -eu
set -o pipefail

workspace=$(realpath $(dirname $0)/../../)
catalog=$(realpath $1)
schema=$(realpath $2)
input=$(realpath $3)
output=$(realpath -m $4)

SCHEMA_PATH=$schema \
    $workspace/glogs/ir/target/release/build_ceg_catalog -c $catalog -i $input -o $output
