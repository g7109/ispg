#!/bin/bash
set -eu
set -o pipefail

schema=$(realpath $1)
pattern=$(realpath $2)
subpatterns=$(realpath $3)

workspace=$(realpath $(dirname $0)/../../)

SCHEMA_PATH=$schema \
    $workspace/glogs/ir/target/release/print_plan_cost -p $pattern -s $subpatterns --w1 1000.0 --w2 500.0
