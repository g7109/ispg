#!/bin/bash
set -eu
set -o pipefail

graph=$(realpath $1)
schema=$(realpath $2)
pattern=$(realpath $3)
subpatterns=$(realpath $4)
threads=$5

workspace=$(realpath $(dirname $0)/../../)

SCHEMA_PATH=$schema \
DATA_PATH=$graph \
$workspace/glogs/ir/target/release/query -p $pattern -s $subpatterns -t $threads --w1 1000.0 --w2 500.0
