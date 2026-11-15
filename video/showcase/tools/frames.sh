#!/bin/bash
# Review stills from the rendered showcase: deliverables/frames/NN_name.png
set -euo pipefail
cd "$(dirname "$0")/.."
IN=deliverables/miguel-family-showcase.mp4
OUT=deliverables/frames
rm -rf "$OUT" && mkdir -p "$OUT"
while read -r t name; do
  ffmpeg -nostdin -loglevel error -ss "$t" -i "$IN" -frames:v 1 "$OUT/$name.png"
done <<'LIST'
0.5 01_phones-rise
1.4 02_home
3.35 03_tap-see-all
3.5 04_light-to-right-phone
5.0 05_moms-day
7.6 06_moms-day-afternoon
10.0 07_to-scene-2
12.2 08_choose-water
13.7 09_love-you-mom
14.25 10_send-with-miguel
16.5 11_on-its-way
19.8 12_delivered
22.6 13_check-in
24.25 14_ask-mom
25.6 15_asking-mom
28.4 16_connected-she-waves
30.5 17_on-the-call
32.6 18_moms-day
35.0 19_miguels-summary
37.9 20_walking-pace
40.5 21_from-the-family
45.0 22_fade-out
LIST
ls "$OUT" | wc -l
