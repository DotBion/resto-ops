#!/usr/bin/env bash
# Fetch real café footage for the Queue Monitor's default source (not redistributed in this repo).
# Café dataset (Kim et al., ECCV 2024, https://dk-kim.github.io/CAFE/), café 8, clips 187, 27, 28:
# people standing in line at the counter on the left. ~42 MiB of HTTP ranges, ~1 minute.
# Output: demo/real/cafe-781-counter.mp4 (git-ignored). The server picks it up as the default source.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
OUT=demo/real/cafe-781-counter.mp4
[ -f "$OUT" ] && { echo "Real default footage already present: $OUT"; exit 0; }
WORK=eval/local/real-default
mkdir -p "$WORK" demo/real
LIST="$WORK/concat.txt"; : > "$LIST"
for clip in 8/187 8/27 8/28; do
  id="${clip/\//_}"
  [ -d "$WORK/clips/$id" ] || "$PY" -m eval.fetch_example "$WORK/clips/$id" --clip "$clip"
  [ -f "$WORK/clips_$id.mp4" ] || "$PY" -m eval.import_cafe "$WORK/clips/$id" --fps 30 --cafe source-8 --view unknown \
      --recording-group cafe-source-8 --split development --manifest "$WORK/manifest.json" >/dev/null
  echo "file '$PWD/$WORK/clips_$id.mp4'" >> "$LIST"
done
ffmpeg -nostdin -loglevel error -y -f concat -safe 0 -i "$LIST" -an -c:v libx264 -preset veryfast -crf 26 \
  -vf "scale=1280:-2,fps=10" -pix_fmt yuv420p -movflags +faststart "$OUT"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1))"
