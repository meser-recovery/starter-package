#!/bin/bash

cd audio/bt6

for f in *; do 
    n=$(printf "%s" "$f" | iconv -f UTF-8-MAC -t UTF-8);
    if [[ "$n" != "$f" ]]; then
        echo "Fixing: $f → $n"
        mv "$f" "$n"
    fi
done
