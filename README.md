# No Guesswork Lighting

**Version:** 1.4.0
**Last updated:** 2026-03-16

Deterministic lighting recommendation engine and photographer-facing web app.
Analyzes reference photos, reverse-engineers lighting setups, scores and ranks
30+ lighting systems, and produces interactive setup diagrams with confidence
metrics.

---

## Document Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.4.0 | 2026-03-16 | Complete rewrite. Updated architecture, project structure, API reference, responsive layout docs, gear matching, theme system, testing. Replaces outdated v1 README. |
| 1.0.0 | 2025-05-08 | Original v1 README (scoring engine + legacy `/recommend` endpoint). |

---

## Quickstart

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd ui && npm install && npm run dev
```

- App UI: http://localhost:5173
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Two install failures seen on a clean Debian/Ubuntu container (9/13/2026)

Both are **observations with a working fix**, not explained mechanisms.

**1. `pip install -r requirements.txt` aborts on PyYAML**

```
ERROR: Cannot uninstall PyYAML 6.0.1, RECORD file not found.
       Hint: The package was installed by debian.
```

The distro's PyYAML has no `RECORD`, so pip will not replace it and the install
stops — nothing after that line arrives. Workaround:

```bash
pip install --ignore-installed PyYAML -r requirements.txt
```

**2. mediapipe fails on first use — only if you are OFF the pin**

```
OSError: libEGL.so.1: cannot open shared object file      # then, after fixing that:
OSError: libGLESv2.so.2: cannot open shared object file
```

Raised from `ctypes.CDLL` in `mediapipe/tasks/python/core/mediapipe_c_bindings.py`
on the first `mp.Image(...)`.

**This is a symptom of having installed mediapipe unpinned.** A bare
`pip install mediapipe` currently resolves to 1.0.1, and the two releases do not
ship the same native library at all:

| | `mediapipe==0.10.32` (pinned here) | `mediapipe==1.0.1` |
|---|---|---|
| `tasks/c/libmediapipe.so` | 28,650,160 bytes | 114,335,992 bytes |
| `NEEDED libEGL.so.1` | no | **yes** |
| `NEEDED libGLESv2.so.2` | no | **yes** |

So the real fix is to install from `requirements.txt` and stay on 0.10.32, which
needs no GL libraries. If you deliberately want a current mediapipe:

```bash
apt-get install -y libegl1 libgles2
```

**The `Dockerfile` is correct as it stands.** It installs `libgl1` and
`libglib2.0-0` and no EGL/GLES packages, which is exactly right for the pinned
version — verified by reading the ELF headers of both wheels, not by building
the image, as no container runtime was available.

An earlier version of this note said the two releases shipped byte-identical
libraries and that the requirement therefore applied to the pin as well. That
was wrong, and wrong for a specific reason worth recording: the comparison was
run against the *installed* library, which `pip install -r requirements.txt` had
already downgraded to 0.10.32. It compared 0.10.32 with 0.10.32 and reported a
match. Always compare the artifacts you name, not the one that happens to be
installed.

Without these, `analyze_image_regions` returns
`{"ok": false, "error": "opencv-python and mediapipe are required"}` — correct,
and easy to misread as a missing pip install when the wheel is right there.

## Make Targets

```
make run         Dev server with auto-reload (default :8000)
make run-prod    Production server (2 workers)
make test        Run pytest -v (70 test files, 2100+ tests)
make test-fast   Run pytest -q
make format      Auto-format with ruff
make lint        Lint check
make clean       Remove caches
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  React SPA (Vite)                                               │
│  ui/src/                                                        │
│    App.jsx → AppHeader + Sidebar/BottomNav + Screen             │
│    screens/  (18 screens)                                       │
│    cards/    (20 result cards)                                   │
│    transform.js  (API response → UI card data)                  │
└────────────────────────┬────────────────────────────────────────┘
                         │ fetch /api/*
┌────────────────────────▼────────────────────────────────────────┐
│  FastAPI Backend                                                │
│  main.py → routers:                                             │
│    /api/shoot-match    Primary recommendation endpoint          │
│    /api/shoot-mode     Live shooting assistant                  │
│    /api/lab            Developer analysis tools                 │
│    /api/auth           User authentication                      │
│    /api/user-data      Kit + saved setups sync                  │
│    /api/diagnostics    Engine introspection                     │
│    /api/lighting-dna   Pattern DNA fingerprinting               │
│    /api/spatial        Room planner calculations                │
│    /api/admin          Admin tools                              │
│    /recommend          Legacy v1 endpoint                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│  Engine (engine/)                                               │
│    image_analysis.py      Vision pipeline orchestrator          │
│    reference_read.py      3-layer image analysis (VLM)          │
│    lighting_inference.py  Pattern + cue interpretation          │
│    consensus_solver.py    Multi-signal consensus                │
│    scoring.py             Deterministic scoring + confidence    │
│    selector.py            System ranking + selection            │
│    diagram.py             Spatial diagram generation            │
│    patterns.py            Pattern classification                │
│    rule_engine.py         Legacy orchestration layer            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ngw-core/
├── main.py                    FastAPI app, route registration, static mounts
├── engine/                    Core analysis + recommendation engine (45 modules)
│   ├── image_analysis.py      Vision pipeline orchestrator (basic/vision/extended)
│   ├── reference_read.py      3-layer reference analysis via VLM
│   ├── lighting_inference.py  Lighting pattern + cue interpretation
│   ├── cue_inference.py       Shadow, highlight, catchlight analysis
│   ├── cue_extraction.py      Low-level cue extraction from image data
│   ├── consensus_solver.py    Multi-hypothesis consensus solver
│   ├── contradiction_engine.py Signal contradiction detection
│   ├── consistency_engine.py  Cross-signal consistency validation
│   ├── scoring.py             Deterministic scoring + confidence (0-100)
│   ├── selector.py            System ranking, top-3 picks, tie-breaking
│   ├── diagram.py             DiagramSpec generation (top-down + side view)
│   ├── patterns.py            Pattern classification (rembrandt, loop, etc.)
│   ├── pattern_matcher.py     Pattern matching against canonical definitions
│   ├── vlm.py                 Vision-Language Model integration
│   ├── vlm_reconstruction.py  VLM-based setup reconstruction
│   ├── vision_pipeline.py     Face detection, segmentation, palette extraction
│   ├── vision_passes.py       Multi-pass vision analysis
│   ├── rule_engine.py         Legacy orchestration layer
│   ├── normalizer.py          Gear-name alias resolution
│   ├── master_mode.py         Master photographer mode profiles
│   ├── archetype_classifier.py Image archetype classification
│   ├── lighting_dna.py        Lighting DNA fingerprinting
│   ├── lighting_knowledge_library.py  Canonical pattern database
│   ├── reference_dataset.py   Reference image dataset management
│   ├── reference_ingestion.py Reference image processing pipeline
│   ├── reference_matcher.py   Reference similarity matching
│   └── signal_weights.py      Signal weighting configuration
│
├── api/routes/                API route handlers (10 modules)
│   ├── shoot_match.py         Primary: mood + gear + ref image → recommendation
│   ├── shoot_mode.py          Live shooting assistant
│   ├── lab.py                 Developer analysis + benchmarking tools
│   ├── auth.py                User authentication (register/login)
│   ├── user_data.py           Kit + saved setups cloud sync
│   ├── diagnostics.py         Engine introspection endpoints
│   ├── lighting_dna.py        Pattern DNA analysis
│   ├── spatial.py             Room planner distance calculations
│   └── admin.py               Admin tools
│
├── ui/                        React SPA (Vite + JSX)
│   ├── src/
│   │   ├── App.jsx            Root: AppHeader + sidebar/bottom-nav + screen
│   │   ├── main.jsx           Entry point, theme initialization
│   │   ├── api.js             API client (fetch wrappers)
│   │   ├── transform.js       API response → UI card data mapper
│   │   ├── gearPresets.js     Gear profile → criteria mapping
│   │   ├── screens/           18 screen components
│   │   │   ├── WelcomeScreen.jsx       Home screen (3 entry points)
│   │   │   ├── SetupWizard.jsx         Multi-step wizard flow
│   │   │   ├── ResultsScreen.jsx       Card stack results (two-col on desktop)
│   │   │   ├── ReferenceEvalScreen.jsx Reference image analysis flow
│   │   │   ├── RecipeScreen.jsx        Browse lighting recipes (grid on desktop)
│   │   │   ├── MyKitScreen.jsx         Gear inventory management
│   │   │   ├── SavedSetupsScreen.jsx   Saved setup library
│   │   │   ├── ShootModeScreen.jsx     Live shooting assistant
│   │   │   ├── ShotMatchScreen.jsx     Before/after comparison
│   │   │   ├── LabScreen.jsx           Developer analysis tools
│   │   │   ├── RoomPlannerScreen.jsx   Room dimension planner
│   │   │   └── SettingsScreen.jsx      App settings
│   │   ├── cards/             20 result card components
│   │   │   ├── BestMatchCard.jsx       Hero recommendation + gear match banner
│   │   │   ├── DiagramCard.jsx         Canvas-based diagram (top + side view)
│   │   │   ├── ShootSetupCard.jsx      Per-light setup details
│   │   │   ├── RefLightingCard.jsx     Reference image lighting analysis
│   │   │   ├── RefImageReadCard.jsx    Reference image scene analysis
│   │   │   ├── RefRecreationCard.jsx   How to recreate the reference
│   │   │   ├── RefInterpretationsCard.jsx  Confidence interpretations
│   │   │   ├── CameraSubjectCard.jsx   Camera + subject guidance
│   │   │   ├── HowToTestCard.jsx       Interactive test checklist
│   │   │   ├── QuickFixesCard.jsx      Problem → fix pairs
│   │   │   ├── WhatToLookForCard.jsx   Good signs + warnings
│   │   │   ├── SpaceCheckCard.jsx      Room fit check
│   │   │   ├── OtherSetupsCard.jsx     Alternative recommendations
│   │   │   ├── SkinToneCard.jsx        Skin tone adjustments
│   │   │   ├── TestShotCard.jsx        Test shot comparison
│   │   │   └── FeedbackCard.jsx        User feedback collection
│   │   ├── components/        23 shared UI components
│   │   │   ├── AppHeader.jsx           Sticky header + theme + settings
│   │   │   ├── BottomNav.jsx           Bottom nav (mobile) / sidebar (desktop)
│   │   │   ├── ReliabilityDots.jsx     Confidence visualization
│   │   │   ├── MasterModeSelector.jsx  Master photographer mode picker
│   │   │   └── Toast.jsx              Toast notifications
│   │   ├── data/              19 data/API modules
│   │   │   ├── kitStore.js             Gear inventory (localStorage + server)
│   │   │   ├── setupStore.js           Saved setups (localStorage + server)
│   │   │   ├── recipes.js              Pre-built lighting recipe library
│   │   │   ├── themeStore.js           Theme persistence (5 themes)
│   │   │   └── settingsStore.js        App settings persistence
│   │   ├── context/
│   │   │   └── AppContext.jsx          Global state (screen, result, user, etc.)
│   │   ├── modes/
│   │   │   └── featureFlags.js         Feature flag system
│   │   └── styles/
│   │       └── app.css                 Single stylesheet (responsive breakpoints)
│   └── index.html
│
├── data/
│   ├── lighting_systems.json  30+ pre-built lighting system candidates
│   ├── taxonomy.json          Enums: gear, modifiers, moods, environments
│   ├── gear_aliases.json      Brand/model → canonical ID mappings
│   ├── lighting_patterns.json Pattern definitions
│   ├── reference_index.json   Reference image metadata index
│   └── systems/canonical/     Per-pattern YAML definitions
│
├── tests/                     70 test files, 2100+ tests
├── docs/                      Additional documentation
├── Makefile
└── requirements.txt
```

---

## Key Workflows

### 1. Reverse-Engineer a Photo (Primary Flow)
```
User uploads reference image
  → POST /api/shoot-match (multipart: image + mood + gear + environment)
  → engine/image_analysis.py: vision pipeline (face detect, segment, palette)
  → engine/reference_read.py: VLM 3-layer analysis (image_read, lighting_read, recreation_setup)
  → engine/lighting_inference.py: pattern + cue interpretation
  → engine/selector.py: rank systems → best match
  → engine/diagram.py: generate DiagramSpec
  → API returns full recommendation + reference analysis
  → ui/transform.js: maps to card data
  → ResultsScreen renders card stack
```

### 2. Build from Scratch
```
User selects mood + subject + environment + gear
  → POST /api/shoot-match (JSON: mood, subject, environment, gear_profile)
  → api/routes/shoot_match.py: filter systems by criteria
  → engine/selector.py: rank → best match
  → engine/diagram.py: generate DiagramSpec
  → API returns recommendation
  → ResultsScreen renders card stack
```

### 3. Browse Recipes
```
User selects from pre-built recipe library
  → POST /recommend (recipe criteria)
  → engine/rule_engine.py: score → select → diagram
  → ResultsScreen renders card stack
```

---

## Responsive Layout

| Breakpoint | Layout | Navigation |
|------------|--------|------------|
| < 640px (mobile) | Single column, full-width cards | Bottom nav bar (fixed) |
| 640px+ (tablet) | Single column, wider padding, 3-col mood grid | Bottom nav bar |
| 768px+ (desktop) | Sidebar nav + content area, 2-col recipe grid | Left sidebar |
| 1080px+ (wide) | Wider sidebar, two-column results, 3-col recipes | Left sidebar |
| 1400px+ (ultra) | Max content width 1100px | Left sidebar |

### Desktop Layout (768px+)
The app shell uses a flex layout:
```
┌──────────────────────────────────────────────────┐
│  AppHeader (sticky)                              │
├────────┬─────────────────────────────────────────┤
│        │                                         │
│ Sidebar│  Screen Content                         │
│  Home  │  (max-width constrained for readability)│
│ Recipes│                                         │
│ My Kit │                                         │
│ Saved  │                                         │
│  New   │                                         │
│        │                                         │
└────────┴─────────────────────────────────────────┘
```

### Results Screen (1080px+)
```
┌──────────────────────┬───────────────────────────┐
│  Your Setup          │  Test & Troubleshoot      │
│  - Best Match        │  - How to Test            │
│  - Shoot Setup       │  - Test Shot              │
│  - Skin Tone         │  - What to Look For       │
│  - Space Check       │  - Quick Fixes            │
│  Camera & Subject    │                           │
├──────────────────────┴───────────────────────────┤
│  Feedback  |  Alternatives (full width)          │
└──────────────────────────────────────────────────┘
```

---

## Theme System

Five themes available, toggled via header button:
- **Dark** (default) — Studio dark (#0E0F12)
- **Light** — Clean white
- **Photoshop** — Adobe Photoshop-inspired
- **Lightroom** — Adobe Lightroom-inspired
- **Daynote** — Warm editorial

All themes use CSS custom properties defined in `ui/src/styles/app.css`.

---

## Gear Matching

The system uses **progressive filter relaxation** to always return useful results:

| Tier | Strategy | Example |
|------|----------|---------|
| 1 - exact | Mood + environment + exact gear | "beauty + studio + speedlight" |
| 2 - gear_group | Mood + environment + gear family | "speedlight" matches any flash type |
| 3 - any_gear | Mood + exact gear (drop environment) | Works for any location |
| 4 - any_gear_group | Mood + gear family (drop environment) | Broadest gear match |
| 5 - mood_only | Best setup for mood regardless of gear | Always returns results |

Gear substitution groups: `flash`, `continuous`, `ambient`, `specialty`

---

## API Reference

### POST /api/shoot-match
Primary recommendation endpoint. Accepts multipart form (with image) or JSON.

**Parameters:**
- `mood` (string): beauty, corporate, cinematic, editorial, natural
- `subject_type` (string): headshot, portrait, full_body, etc.
- `environment` (string): studio_small, studio_medium, outdoor, etc.
- `gear_profile` (string): speedlight, strobe_mono, led_panel, etc.
- `ceiling_height` (float, optional): room ceiling in feet
- `image` (file, optional): reference photo to reverse-engineer
- `modifiers_available` (list, optional): available light modifiers

**Response includes:**
- `bestMatch`: name, confidence, rationale, pattern, reliability
- `setup`: per-light details (role, modifier, position, power)
- `diagram`: DiagramSpec for rendering
- `cameraSettings`: aperture, ISO, shutter, WB
- `referenceImageAnalysis`: 3-layer analysis (if image provided)
- `lightingIntelligence`: detected pattern, cues, confidence
- `gearMatch`: tier, label, adaptation notes
- `alternatives`: other ranked systems
- `testSteps`, `quickFixes`, `goodSigns`, `warnings`

### POST /recommend
Legacy v1 endpoint. Accepts systems array + input context.

### GET /health
Returns `{"status": "ok"}`

---

## Testing

```bash
# Full suite (2100+ tests)
python3 -m pytest tests/ -q

# Specific area
python3 -m pytest tests/test_shoot_match.py -v
python3 -m pytest tests/test_lighting_inference.py -v
python3 -m pytest tests/test_consensus_solver.py -v

# UI build check
cd ui && npx vite build
```

---

## Environment Variables

See `.env.example`. Key variables:
- `LOG_LEVEL` — Logging level (default: INFO)
- `OPENAI_API_KEY` — Required for VLM-powered reference analysis
- `NGW_SECRET_KEY` — JWT signing for auth

---

## Known Architectural Issues

See `.claude/plans/enchanted-prancing-lightning.md` for the full consistency plan.

Key items:
1. **Five independent pattern classifiers** can disagree across cards
2. **Frontend confidence floors** override engine scores (lines in transform.js)
3. **Solver bypassed in production** — shoot_match calls `run_solver=False`
4. **Field name fragmentation** — `pattern` vs `shadow_pattern` vs `pattern_name`

These are tracked for Phase 2 cleanup.
