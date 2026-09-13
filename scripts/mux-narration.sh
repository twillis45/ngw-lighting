#!/usr/bin/env bash
# Mux the narration clips onto the demo video at their cue times.
#
#   ./mux-narration.sh ngw-demo-1440x900.mp4 ./vo ngw-demo-narrated.mp4
#
# Expects ./vo/01.wav … 11.wav, numbered in script order (docs/DEMO-NARRATION.md).
# Verifies every clip fits before its successor starts; refuses to build if not,
# because overlapping narration is two voices talking at once.

set -euo pipefail

VIDEO="${1:-ngw-demo-1440x900.mp4}"
VODIR="${2:-./vo}"
OUT="${3:-ngw-demo-narrated.mp4}"

# Cue times in seconds, from the caption transitions measured in the video.
#
# Line 6 stays at 40 even though the script calls for two beats of silence on
# the uncertainty shot first. The silence is already there: line 5 ends around
# 0:38, so the gap to 0:40 IS the pause. Delaying the clip itself to 0:42 pushes
# its tail past 0:52 and into line 7.
CUES=(3 11 20 26 33 40 52 60 80 93 99)
N=${#CUES[@]}

command -v ffmpeg  >/dev/null || { echo "ffmpeg not found"; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe not found"; exit 1; }
[[ -f "$VIDEO" ]] || { echo "no video at $VIDEO"; exit 1; }

dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

VIDDUR=$(dur "$VIDEO")
echo "video: $VIDEO  (${VIDDUR}s)"
echo

# ── verify fit ───────────────────────────────────────────────────────────────
fail=0
for ((i = 0; i < N; i++)); do
  f=$(printf "%s/%02d.wav" "$VODIR" $((i + 1)))
  [[ -f "$f" ]] || { echo "MISSING $f"; fail=1; continue; }
  d=$(dur "$f")
  start=${CUES[$i]}
  end=$(awk -v s="$start" -v d="$d" 'BEGIN{printf "%.2f", s+d}')
  if ((i + 1 < N)); then
    next=${CUES[$((i + 1))]}
  else
    next=$VIDDUR
  fi
  over=$(awk -v e="$end" -v n="$next" 'BEGIN{printf "%.2f", e-n}')
  if awk -v e="$end" -v n="$next" 'BEGIN{exit !(e > n + 0.05)}'; then
    printf "  %02d  %5ss + %5.2fs = %6.2f   next %5ss   OVERLAP %ss\n" \
      $((i + 1)) "$start" "$d" "$end" "$next" "$over"
    fail=1
  else
    printf "  %02d  %5ss + %5.2fs = %6.2f   next %5ss   ok\n" \
      $((i + 1)) "$start" "$d" "$end" "$next"
  fi
done

echo
if ((fail)); then
  cat <<'MSG'
REFUSING TO BUILD — a clip runs into the next one, or a file is missing.

Fix by one of:
  * regenerate the offending line faster (seed_audio speech_rate +10 .. +25)
  * shorten that line in docs/DEMO-NARRATION.md and regenerate it
  * move its cue earlier in CUES above, if the shot it belongs to starts sooner
MSG
  exit 1
fi

# ── build ────────────────────────────────────────────────────────────────────
args=(-i "$VIDEO")
filter=""
mix=""
for ((i = 0; i < N; i++)); do
  f=$(printf "%s/%02d.wav" "$VODIR" $((i + 1)))
  args+=(-i "$f")
  ms=$((CUES[i] * 1000))
  filter+="[$((i + 1)):a]adelay=${ms}|${ms},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a$i];"
  mix+="[a$i]"
done
filter+="${mix}amix=inputs=${N}:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad=whole_dur=${VIDDUR}[vo]"

# No -shortest: the narration ends before the picture does, and -shortest would
# truncate the video to the last spoken word — cutting the end card off.
# apad pads the mix with silence out to the video's length instead.
ffmpeg -y "${args[@]}" \
  -filter_complex "$filter" \
  -map 0:v -map "[vo]" \
  -c:v copy -c:a aac -b:a 192k -ar 48000 \
  "$OUT"

echo
echo "wrote $OUT"
