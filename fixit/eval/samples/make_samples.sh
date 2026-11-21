#!/usr/bin/env bash
# Rebuild the synthetic smoke-test clips from public Wikimedia Commons photos.
# Each photo -> a clean slow-zoom clip and a "messy" clip (dark, low contrast, blurred, noisy, shaky pan).
set -euo pipefail; cd "$(dirname "$0")"; UA="fixitcam-eval/0.1"
declare -A SRC=(
 [macbook_cable]="https://thumb.wikimedia.org/wikipedia/commons/thumb/7/71/Frayed_and_Broken_MacBook_Pro_Charger_Cable_%2816868118774%29.jpg/1280px-Frayed_and_Broken_MacBook_Pro_Charger_Cable_%2816868118774%29.jpg"
 [aerator]="https://thumb.wikimedia.org/wikipedia/commons/thumb/0/04/New_and_old_faucet_aerator.JPG/1280px-New_and_old_faucet_aerator.JPG"
 [brakepads]="https://thumb.wikimedia.org/wikipedia/commons/thumb/1/10/Worn_metallic_disc_brake_pads.jpg/1280px-Worn_metallic_disc_brake_pads.jpg"
 [umbrella]="https://upload.wikimedia.org/wikipedia/commons/6/6e/Broken_umbrella_%2830312884283%29.jpg")
for f in "${!SRC[@]}"; do
  curl -sLA "$UA" -o "$f.jpg" "${SRC[$f]}"
  ffmpeg -loglevel error -y -loop 1 -i $f.jpg -t 6 -vf "scale=1280:-2,zoompan=z='min(zoom+0.003,1.4)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=960x720:fps=25,format=yuv420p" ${f}_clean.mp4
  ffmpeg -loglevel error -y -loop 1 -i $f.jpg -t 6 -vf "scale=1280:-2,crop=iw*0.7:ih*0.7:'(iw*0.3)*(0.5+0.45*sin(t*2.3))':'(ih*0.3)*(0.5+0.45*cos(t*1.7))',scale=960:720,eq=brightness=-0.25:contrast=0.7,boxblur=3:1,noise=alls=25:allf=t,fps=25,format=yuv420p" -c:v libx264 -crf 32 ${f}_messy.mp4
  rm -f $f.jpg
done
