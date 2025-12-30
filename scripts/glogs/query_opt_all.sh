#!/bin/bash
set -u
set -o pipefail

graph=$(realpath $1)
schema=$(realpath $2)
catalog=$(realpath $3)
pattern_dir=$(realpath $4)
mkdir -p $5
output_dir=$(realpath $5)
threads=$6

workspace=$(realpath $(dirname $0)/../../)

patterns=$(find $pattern_dir -name '*.json' -type f | sort)
for pattern in $patterns; do
    count=$($workspace/scripts/glogs/query_opt.sh $graph $schema $catalog $pattern $threads)
    echo "$pattern: $count"
    filename=$(basename $pattern)
    jq ".count=$count" $pattern > $output_dir/$filename.tmp
    mv $output_dir/$filename.tmp $output_dir/$filename
done
