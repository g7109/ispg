#!/bin/bash
set -eu
set -o pipefail

# Estimate the cardinality of a given pattern
# Argument: catalog, pattern 

catalog=$(realpath $1)
pattern=$(realpath $2)

workspace=$(realpath $(dirname $0)/../../)

$workspace/glogs/ir/target/release/pattern_count -c $catalog -p $pattern -r -s 30