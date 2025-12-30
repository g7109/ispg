#!/bin/bash
set -eu
set -o pipefail

graph=$(realpath $1)
schema=$(realpath $2)
catalog=$(realpath $3)
pattern=$(realpath $4)
threads=$5

workspace=$(realpath $(dirname $0)/../../)

SCHEMA_PATH=$schema \
DATA_PATH=$graph \
$workspace/glogs/ir/target/release/query_opt -c $catalog -p $pattern -t $threads
