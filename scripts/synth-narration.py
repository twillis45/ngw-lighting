"""Synthesize narration at a target words-per-minute, clamped to fit each window."""
import sys, wave, pathlib, re
from piper import PiperVoice, SynthesisConfig

VOICE = "voices/en-us-lessac-medium.onnx"
OUT = pathlib.Path("./vo")
OUT.mkdir(parents=True, exist_ok=True)

# em-dashes replaced with commas: the dash isn't in the phoneme map and it also
# reads as a hard stop rather than the breath the script intends.
LINES = [
    (3,  "This is No Guesswork Lighting. It reads a portrait, and tells you how it was lit."),
    (11, "Start with any photograph. A reference, or a frame from your own shoot."),
    (20, "You crop to the face. That's where light leaves its evidence."),
    (26, "Geometry comes first. Catchlight position. The direction the nose shadow falls."),
    (33, "Then the read. The pattern, the confidence, and how many sources were in the room."),
    (40, "It tells you where it was not certain. Two readings disagreed. Clamshell was just as credible. It names its doubt, rather than hiding it."),
    (52, "The blueprint is the deliverable. Key, elevation, distance, modifier. Something you could rebuild on set tomorrow."),
    (60, "Thirty-one documented setups, filtered to the work you actually do."),
    (80, "It runs the other way too. No photograph. Describe the subject and the look, and it builds the setup."),
    (93, "Every read is kept. What you shot, and how it was lit."),
    (99, "It is built to hold up under ambiguity. When it cannot resolve something, it says so."),
]
VIDEO_END = 110.13
GAP = 0.40
TARGET_WPM = 125.0
MAX_SCALE = 2.10

voice = PiperVoice.load(VOICE)


def render(text, scale, path):
    cfg = SynthesisConfig(length_scale=scale, noise_scale=0.667, noise_w_scale=0.8, volume=1.0)
    with wave.open(str(path), "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=cfg)
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


print(f"{'#':>3} {'words':>5} {'win':>6} {'want':>6} {'scale':>6} {'dur':>6} {'wpm':>5}  fit")
rows = []
for i, (cue, text) in enumerate(LINES):
    nxt = LINES[i + 1][0] if i + 1 < len(LINES) else VIDEO_END
    window = nxt - cue - GAP
    words = len(re.findall(r"[A-Za-z0-9'’-]+", text))
    want = min(words / TARGET_WPM * 60.0, window)      # calm, but never past the window
    p = OUT / f"{i+1:02d}.wav"

    # length_scale is sub-linear in duration, so solve for it instead of
    # computing it once: each pass corrects by the ratio it actually produced.
    dur = render(text, 1.0, p)
    scale = 1.0
    for _ in range(5):
        if abs(dur - want) <= 0.12:
            break
        nxt_scale = min(MAX_SCALE, max(0.85, scale * (want / dur)))
        if abs(nxt_scale - scale) < 1e-3:
            break
        scale = nxt_scale
        dur = render(text, scale, p)
    if dur > window:                                    # safety: tighten if still long
        for _ in range(3):
            if dur <= window:
                break
            scale = max(0.85, scale * (window / dur) * 0.99)
            dur = render(text, scale, p)

    wpm = words / dur * 60
    ok = "ok" if dur <= window + 0.01 else f"OVER {dur-window:.2f}"
    rows.append((dur, ok))
    print(f"{i+1:>3} {words:>5} {window:>6.2f} {want:>6.2f} {scale:>6.3f} {dur:>6.2f} {wpm:>5.0f}  {ok}")

bad = [r for r in rows if r[1] != "ok"]
tot = sum(r[0] for r in rows)
print(f"\ntotal speech {tot:.1f}s in {VIDEO_END:.0f}s video  ({tot/VIDEO_END*100:.0f}% voiced)")
print("ALL LINES FIT" if not bad else f"{len(bad)} OVER")
sys.exit(1 if bad else 0)
