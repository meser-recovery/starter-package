#!/bin/bash

cd audio/bt6

i=1
for f in *.mp3; do
  num=$(printf "%03d" "$i")
  new="bt6_${num}.mp3"
  echo "$f  ->  $new"
  mv "$f" "$new"
  i=$((i+1))
done

