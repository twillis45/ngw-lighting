import { createContext, useContext, useReducer, useCallback } from 'react';
import { navHaptic, selectHaptic, successHaptic, warnHaptic } from '../utils/haptics';
import { primaryAdminEmail } from '../config/admin';

/* -- default light factory (kept for backward compat) -- */

let _nextId = 1;
export function defaultLight() {
  return {
    id: `light-${_nextId++}`,
    type: 'strobe_mono',
    brand: '',
    features: { dimmable: true, battery: false, waterproof: false, smart_ready: false },
  };
}

/* -- wizard step sequences ----------------------------- */

const MOOD_STEPS      = ['the_shot', 'the_space'];
const KIT_STEPS       = ['gear_entry', 'the_shot', 'the_space'];
const REF_MATCH_STEPS = ['the_shot', 'the_space'];
const EDIT_KIT_STEPS  = ['gear_entry'];

/* -- initial state ------------------------------------- */

/* -- persist master mode across sessions -- */
const MASTER_MODE_KEY = 'ngw_master_mode';
function _loadMasterMode() {
  try { return localStorage.getItem(MASTER_MODE_KEY) || null; } catch { return null; }
}

/* -- persist room dimensions across sessions -- */
const ROOM_DIMS_KEY = 'ngw_room_dimensions';
function _loadRoomDimensions() {
  try {
    const raw = localStorage.getItem(ROOM_DIMS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

/** Convert exact ceiling height (ft) to the legacy categorical value. */
function _ceilingFtToCategory(ft) {
  if (ft < 8) return 'under_8';
  if (ft < 10) return '8_9';
  if (ft < 12) return '10_12';
  return '12_plus';
}

const initialState = {
  screen: 'welcome',       // 'welcome' | 'wizard' | 'loading' | 'results' | 'symptom' | 'auth' | ...
  history: [],
  symptomSlug: null,       // active symptom slug when screen === 'symptom'
  user: null,               // { id, email, username } when logged in
  appMode: null,            // 'build' | 'match' | 'shot_match' | 'shoot' | 'lab'
  intent: null,             // 'mood' | 'kit'
  wizardStep: 0,
  wizardSteps: [],          // computed from intent
  mood: null,
  subjectType: null,
  environment: null,
  ceilingHeight: null,
  roomDimensions: _loadRoomDimensions(),  // { lengthFt, widthFt, ceilingFt, source }
  floorPlan: null,           // { subjectPos: {x,y}, cameraPos: {x,y} }
  spatialWarnings: [],       // string[] — real-time constraint warnings
  skinTone: null,            // 'light' | 'medium' | 'dark'
  masterMode: _loadMasterMode(),  // persisted across sessions
  gearPreference: 'recommend',   // 'my_gear' | 'recommend' | 'any' — homepage gear toggle
  gearMode: null,           // 'my_gear' | 'best_setup'
  gear: {
    lights: [],             // [{ type: 'speedlight', qty: 2 }, ...]
    modifiers: [],          // ['softbox', 'beauty_dish', ...]
    support: [],            // [{ type: 'c_stand', qty: 3 }, ...]
  },
  referenceImage: null,        // { file, preview, serverPath } — primary image
  referenceImages: [],         // [{ file, preview, serverPath }] — all uploaded images
  refAnalysis: null,           // analysis from reference image upload
  labPendingImage: null,       // { file, preview, serverPath } — set by "Open in Lab" to pre-load WorkbenchTab
  pendingFix: null,            // { symptomSlug, fix, patternId, confidence, startedAt } — active fix flow
  shootRole: null,             // 'photographer' | 'assistant' | 'second_shooter'
  loading: false,
  apiResponse: null,
  result: null,
  error: null,
};

/* -- reducer ------------------------------------------- */

function reducer(state, action) {
  switch (action.type) {

    /* -- intent & wizard navigation -- */

    case 'SET_APP_MODE':
      return { ...state, appMode: action.mode };

    case 'SET_INTENT': {
      const isKit = action.intent === 'kit';
      const isRefMatch = action.intent === 'ref_match';
      const isEditKit = action.intent === 'edit_kit';
      let steps;
      if (isEditKit) steps = [...EDIT_KIT_STEPS];
      else if (isRefMatch) steps = [...REF_MATCH_STEPS];
      else if (isKit) steps = [...KIT_STEPS];
      else steps = [...MOOD_STEPS];
      // Derive appMode from intent when not already set
      let appMode = state.appMode;
      if (!appMode) {
        if (isKit || isEditKit) appMode = 'build';
        else if (isRefMatch) appMode = 'match';
        else appMode = 'build';
      }
      return {
        ...state,
        appMode,
        intent: action.intent,
        wizardSteps: steps,
        wizardStep: 0,
        screen: 'wizard',
        history: [...state.history, state.screen],
        error: null,
        gearMode: (isKit || isEditKit) ? 'my_gear' : null,
      };
    }

    case 'WIZARD_NEXT': {
      const next = state.wizardStep + 1;
      if (next >= state.wizardSteps.length) return state; // don't auto-advance past end
      return { ...state, wizardStep: next };
    }

    case 'WIZARD_BACK': {
      if (state.wizardStep <= 0) {
        // go back to welcome
        const hist = [...state.history];
        const prev = hist.pop() || 'welcome';
        return {
          ...state,
          screen: prev,
          history: hist,
          wizardStep: 0,
          wizardSteps: [],
          intent: null,
        };
      }
      return { ...state, wizardStep: state.wizardStep - 1 };
    }

    /* -- simple field setters -- */

    case 'SET_MOOD':
      return { ...state, mood: action.mood };

    case 'SET_SUBJECT_TYPE':
      return { ...state, subjectType: action.subjectType };

    case 'SET_ENVIRONMENT':
      return { ...state, environment: action.environment };

    case 'SET_CEILING_HEIGHT':
      return { ...state, ceilingHeight: action.ceilingHeight };

    case 'SET_SKIN_TONE':
      return { ...state, skinTone: action.skinTone };

    case 'SET_MASTER_MODE': {
      // Persist to localStorage so it survives page reloads
      try {
        if (action.masterMode) localStorage.setItem(MASTER_MODE_KEY, action.masterMode);
        else localStorage.removeItem(MASTER_MODE_KEY);
      } catch { /* ignore */ }
      return { ...state, masterMode: action.masterMode };
    }

    /* -- homepage gear preference -- */

    case 'SET_GEAR_PREFERENCE':
      return { ...state, gearPreference: action.payload }; // 'my_gear' | 'recommend' | 'any'

    /* -- gear mode -- */

    case 'SET_GEAR_MODE': {
      let steps = [...state.wizardSteps];
      if (action.mode === 'my_gear') {
        if (!steps.includes('gear_entry')) {
          steps = [...steps, 'gear_entry'];
        }
      } else {
        steps = steps.filter(s => s !== 'gear_entry');
      }
      return { ...state, gearMode: action.mode, wizardSteps: steps };
    }

    /* -- gear: lights -- */

    case 'ADD_GEAR_LIGHT': {
      const existing = state.gear.lights.find(l => l.type === action.lightType);
      if (existing) {
        return {
          ...state,
          gear: {
            ...state.gear,
            lights: state.gear.lights.map(l =>
              l.type === action.lightType ? { ...l, qty: l.qty + 1 } : l
            ),
          },
        };
      }
      return {
        ...state,
        gear: {
          ...state.gear,
          lights: [...state.gear.lights, { type: action.lightType, qty: 1 }],
        },
      };
    }

    case 'REMOVE_GEAR_LIGHT':
      return {
        ...state,
        gear: {
          ...state.gear,
          lights: state.gear.lights.filter(l => l.type !== action.lightType),
        },
      };

    case 'UPDATE_GEAR_QTY': {
      const updated = state.gear.lights.map(l => {
        if (l.type !== action.lightType) return l;
        const newQty = l.qty + (action.delta || 0);
        return { ...l, qty: newQty };
      }).filter(l => l.qty > 0);
      return { ...state, gear: { ...state.gear, lights: updated } };
    }

    /* -- gear: load saved kit -- */

    case 'LOAD_GEAR_KIT': {
      // Normalize modifiers: accept both old string[] and new {type,qty}[] formats
      const rawMods = action.gear.modifiers || [];
      const normalizedMods = rawMods.map(m =>
        typeof m === 'string' ? { type: m, qty: 1 } : m
      );
      return { ...state, gear: { lights: action.gear.lights || [], modifiers: normalizedMods, support: action.gear.support || [] } };
    }

    /* -- gear: modifiers -- */

    case 'ADD_MODIFIER': {
      const existing = state.gear.modifiers.find(m => m.type === action.modifier);
      if (existing) {
        return {
          ...state,
          gear: {
            ...state.gear,
            modifiers: state.gear.modifiers.map(m =>
              m.type === action.modifier ? { ...m, qty: m.qty + 1 } : m
            ),
          },
        };
      }
      return {
        ...state,
        gear: {
          ...state.gear,
          modifiers: [...state.gear.modifiers, { type: action.modifier, qty: 1 }],
        },
      };
    }

    case 'REMOVE_MODIFIER':
      return {
        ...state,
        gear: {
          ...state.gear,
          modifiers: state.gear.modifiers.filter(m => m.type !== action.modifier),
        },
      };

    case 'UPDATE_MODIFIER_QTY': {
      const updated = state.gear.modifiers.map(m => {
        if (m.type !== action.modifier) return m;
        const newQty = m.qty + (action.delta || 0);
        return { ...m, qty: newQty };
      }).filter(m => m.qty > 0);
      return { ...state, gear: { ...state.gear, modifiers: updated } };
    }

    // Legacy support for old TOGGLE_MODIFIER dispatches
    case 'TOGGLE_MODIFIER': {
      const found = state.gear.modifiers.find(m => m.type === action.modifier);
      if (found) {
        return {
          ...state,
          gear: {
            ...state.gear,
            modifiers: state.gear.modifiers.filter(m => m.type !== action.modifier),
          },
        };
      }
      return {
        ...state,
        gear: {
          ...state.gear,
          modifiers: [...state.gear.modifiers, { type: action.modifier, qty: 1 }],
        },
      };
    }

    /* -- gear: support -- */

    case 'ADD_SUPPORT_GEAR': {
      const existing = state.gear.support.find(s => s.type === action.supportType);
      if (existing) {
        return {
          ...state,
          gear: {
            ...state.gear,
            support: state.gear.support.map(s =>
              s.type === action.supportType ? { ...s, qty: s.qty + 1 } : s
            ),
          },
        };
      }
      return {
        ...state,
        gear: {
          ...state.gear,
          support: [...state.gear.support, { type: action.supportType, qty: 1 }],
        },
      };
    }

    case 'REMOVE_SUPPORT_GEAR':
      return {
        ...state,
        gear: {
          ...state.gear,
          support: state.gear.support.filter(s => s.type !== action.supportType),
        },
      };

    case 'UPDATE_SUPPORT_QTY': {
      const updated = state.gear.support.map(s => {
        if (s.type !== action.supportType) return s;
        const newQty = s.qty + (action.delta || 0);
        return { ...s, qty: newQty };
      }).filter(s => s.qty > 0);
      return { ...state, gear: { ...state.gear, support: updated } };
    }

    /* -- reference image -- */

    case 'SET_REFERENCE_IMAGE':
      return { ...state, referenceImage: action.payload };

    case 'SET_REFERENCE_IMAGES':
      return {
        ...state,
        referenceImages: action.payload,
        referenceImage: action.payload[0] || null,
      };

    case 'CLEAR_REFERENCE_IMAGE':
      return { ...state, referenceImage: null, referenceImages: [], refAnalysis: null };

    case 'SET_REF_ANALYSIS':
      return { ...state, refAnalysis: action.analysis };

    case 'SET_LAB_PENDING_IMAGE':
      return { ...state, labPendingImage: action.payload };

    case 'START_FIX_FLOW':
      return { ...state, pendingFix: action.payload };
    case 'COMPLETE_FIX_FLOW':
      return { ...state, pendingFix: null };

    case 'CLEAR_LAB_PENDING_IMAGE':
      return { ...state, labPendingImage: null };

    /* -- shoot mode -- */

    case 'SET_SHOOT_ROLE':
      return { ...state, shootRole: action.role };

    /* -- spatial calibration -- */

    case 'SET_ROOM_DIMENSIONS': {
      const dims = action.dimensions;
      // Persist to localStorage
      try {
        if (dims) localStorage.setItem(ROOM_DIMS_KEY, JSON.stringify(dims));
        else localStorage.removeItem(ROOM_DIMS_KEY);
      } catch { /* ignore */ }
      // Auto-derive categorical ceiling height for backward compat
      const ceilingHeight = dims ? _ceilingFtToCategory(dims.ceilingFt) : state.ceilingHeight;
      return { ...state, roomDimensions: dims, ceilingHeight };
    }

    case 'SET_FLOOR_PLAN':
      return { ...state, floorPlan: action.plan };

    case 'SET_SPATIAL_WARNINGS':
      return { ...state, spatialWarnings: action.warnings };

    /* -- async / navigation -- */

    case 'SET_LOADING':
      return {
        ...state,
        loading: true,
        error: null,
        screen: 'loading',
        history: [...state.history, state.screen],
      };

    case 'SET_RESULT':
      return {
        ...state,
        loading: false,
        result: action.result,
        apiResponse: action.apiResponse,
        error: null,
        screen: 'results',
      };

    case 'SET_ERROR':
      return { ...state, error: action.error, loading: false, screen: 'results' };

    case 'NAVIGATE':
      return {
        ...state,
        screen: action.screen,
        history: [...state.history, state.screen],
        error: null,
      };

    case 'NAVIGATE_SYMPTOM':
      return {
        ...state,
        symptomSlug: action.slug,
        screen: 'symptom',
        history: [...state.history, state.screen],
        error: null,
      };

    case 'GO_BACK': {
      const hist = [...state.history];
      const prev = hist.pop() || 'welcome';
      return { ...state, screen: prev, history: hist };
    }

    case 'SET_USER':
      return { ...state, user: action.user };

    case 'LOGOUT':
      return { ...state, user: null };

    case 'RESET':
      _nextId = 1;
      return { ...initialState, user: state.user, masterMode: state.masterMode, roomDimensions: state.roomDimensions, appMode: null, refAnalysis: null };

    default:
      return state;
  }
}

/* -- context ------------------------------------------- */

const StateCtx = createContext(null);
const DispatchCtx = createContext(null);

/* -- dev demo state presets ------------------------------------------- */

const DEMO_RESULT = {
  bestMatch: {
    name: 'Loop Portrait',
    lightingPattern: 'Loop',
    reliabilityScore: 0.82,
    systemId: 'loop_portrait',
    description: 'Loop lighting — a small downward shadow drops from the nose at roughly 45°, cheek fully lit, minimal fill.',
    lightType: 'strobe',
  },
  setup: {
    lights: [
      {
        role: 'key', label: 'Key Light',
        modifier: '90cm Octabox', _modifierType: 'softbox_octa',
        positionText: '45° camera-left, high (15–20° above eye level)',
        distanceFt: '4 ft', distanceM: '1.2 m',
        powerHint: 'Set first — 1/4 power, adjust for f/8',
        _role: 'key', _lightingPattern: 'Loop',
        notes: ['Flag the key to prevent background spill'],
      },
      {
        role: 'fill', label: 'Fill Light',
        modifier: 'Reflector (silver/white)',
        positionText: 'Camera-right, eye level',
        distanceFt: '6 ft', distanceM: '1.8 m',
        powerHint: '2 stops below key (passive reflector)',
        _role: 'fill', _lightingPattern: 'Loop',
        notes: ['5-in-1 reflector held at camera-right — no power needed'],
      },
      {
        role: 'hair', label: 'Hair Light',
        modifier: 'Grid Spot',
        positionText: 'Behind subject, upper-right',
        distanceFt: '5 ft', distanceM: '1.5 m',
        powerHint: '1 stop below key (1/8 power)',
        _role: 'hair', _lightingPattern: 'Loop',
        notes: ['Grid tightens the beam — prevents lens flare'],
      },
    ],
  },
  lightingIntelligence: {
    detectedModifier: 'softbox_octa',
    catchlightShape: 'round',
    shadowPattern: 'loop',
    fillPresence: 'subtle',
    sourceQuality: 'soft',
    sourceDirection: 'camera-left high',
    lightCount: 3,
    skinTone: 'medium',
  },
  diagram: {
    lights: [
      { role: 'key',  label: 'Key',  angle_deg: -45, distance_m: 1.2, height_m: 2.0, modifier: 'softbox_octa' },
      { role: 'fill', label: 'Fill', angle_deg: 30,  distance_m: 1.8, height_m: 1.5, modifier: 'reflector' },
      { role: 'hair', label: 'Hair', angle_deg: 135, distance_m: 1.5, height_m: 2.1, modifier: 'grid' },
    ],
    camera: { distance_m: 2.2 },
  },
  cameraSettings: { aperture: 'f/8', iso: '100', shutter: '1/200s', wb: 'Daylight' },
  signalReliability: {
    overallSignalStrength: 0.82,
    signalsAvailable: ['catchlight_position', 'catchlight_shape', 'shadow_direction', 'nose_shadow', 'source_quality'],
    ambiguityFlags: {},
  },
  edgeCaseFlags: { blown_highlights: false, mixed_color_temperature: false, extreme_low_key: false },
  alternatives: [
    { name: 'Rembrandt', gapLabel: 'Close alternative', tradeoff: 'Rotate key 10° further for triangle on cheek' },
    { name: 'Paramount', gapLabel: 'Viable option',     tradeoff: 'Move key directly in front for butterfly shadow' },
  ],
  patternCandidates: [],
  spaceCheck: { warnings: [], minWidthFt: 12, minDepthFt: 14, minCeilingFt: 9 },
  testSteps: [
    'Key only — all other lights off',
    'Loop shadow should drop from nose at 45°',
    'Add hair light — check for lens flare with grid on',
    'Add fill reflector — shadow side should remain defined',
    'Test shot — compare shadow shape and contrast',
  ],
  goodSigns: ['Clean loop shadow drop', 'Catchlight at 10–11 o\'clock', 'Cheek fully lit'],
  warnings: ['If nose shadow touches the lip line, rotate key slightly forward'],
  quickFixes: [],
  skinToneAdjustments: null,
};

const DEMO_RING_RESULT = {
  bestMatch: {
    name: 'Ring Flash',
    lightingPattern: 'Ring Flash',
    reliabilityScore: 0.91,
    systemId: 'ring_flash',
    description: 'Ring flash — perfectly flat, shadowless lighting with characteristic donut catchlights encircling the pupil.',
    lightType: 'macro_ring_flash',
  },
  setup: {
    lights: [
      {
        role: 'key', label: 'Ring Flash',
        modifier: 'Canon MR-14EX II',
        _modifierType: 'ring_flash',
        positionText: 'On-axis, lens-mounted',
        distanceFt: '2–3 ft', distanceM: '0.6–0.9 m',
        powerHint: '1/4 power typical — adjust for f/11',
        _role: 'key', _lightingPattern: 'Ring Flash',
        notes: ['Mount directly on lens — keeps catchlights perfectly centered', 'Closer = more wraparound fill'],
      },
    ],
  },
  lightingIntelligence: {
    detectedModifier: 'ring_flash',
    catchlightShape: 'ring',
    shadowPattern: 'none',
    fillPresence: 'full',
    sourceQuality: 'flat',
    sourceDirection: 'on-axis',
    lightCount: 1,
    skinTone: 'medium',
  },
  diagram: {
    lights: [
      { role: 'key', label: 'Ring', angle_deg: 0, distance_m: 0.75, height_m: 1.6, modifier: 'ring_flash' },
    ],
    camera: { distance_m: 0.75 },
  },
  cameraSettings: { aperture: 'f/11', iso: '100', shutter: '1/200s', wb: 'Flash' },
  signalReliability: {
    overallSignalStrength: 0.91,
    signalsAvailable: ['catchlight_shape', 'shadow_direction', 'source_quality', 'fill_presence'],
    ambiguityFlags: {},
  },
  edgeCaseFlags: { blown_highlights: false, mixed_color_temperature: false, extreme_low_key: false },
  alternatives: [
    { name: 'Butterfly', gapLabel: 'Close alternative', tradeoff: 'Beauty dish on-axis gives similar flat look with more dimension' },
    { name: 'Clamshell', gapLabel: 'Viable option', tradeoff: 'Dish + bounce card — broader catchlight, more control' },
  ],
  patternCandidates: [],
  spaceCheck: { warnings: [], minWidthFt: 6, minDepthFt: 6, minCeilingFt: 7 },
  testSteps: [
    'Mount ring flash to lens — check all contacts seated',
    "Test fire — look for the donut catchlight in subject's eyes",
    'Shadow check — no directional shadows should appear on background wall',
    'Exposure test at f/11 — ring flash is powerful at close range',
    'Check for red-eye — ring flash can cause this; use modeling light to pre-constrict pupil',
  ],
  goodSigns: ['Donut catchlight centered in both eyes', 'Flat, shadowless background', 'Even skin tone front-to-back'],
  warnings: ['Avoid merging catchlights if subject is too close — stay 2+ ft', 'Red-eye risk — ask subject to look slightly off-axis'],
  quickFixes: [],
  skinToneAdjustments: null,
};

const DEMO_REF_IMAGE = {
  preview: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?w=600&q=80',
  file: null,
  serverPath: 'static/demo/ref_sample.jpg',
};

const DEMO_ANALYSIS = {
  classification: {
    lightingPattern: 'loop',
    mood: 'cinematic',
    confidence: 0.74,
    suggestedRecipe: null,
  },
  palette: {
    overall: [
      { hex: '#c9a07a', name: 'Warm Sand',    pct: 34 },
      { hex: '#4a3728', name: 'Deep Umber',   pct: 28 },
      { hex: '#f0e8d8', name: 'Cream Highlight', pct: 22 },
      { hex: '#1a1008', name: 'Near Black',   pct: 16 },
    ],
  },
  description: {
    subject: 'Solo portrait — woman, medium-warm skin tone, facing 3/4 left',
    referenceAnalysis: {
      image_read: {
        narrative: 'A dramatic 3/4 portrait with strong directional light from camera-left. Shadows fall cleanly across the far cheek with a defined loop shadow beneath the nose — classic loop lighting with a short shadow drop.',
        pose_notes: 'Subject turned slightly away, chin angled down — classic contemplative framing.',
        scene_description: 'Studio or controlled environment. Single dominant source, no apparent fill.',
        lighting_style: 'dramatic / chiaroscuro',
        likely_photographer: 'Yousuf Karsh / classic studio portraiture',
        notable_visual_devices: ['leading shadow line', 'eye catchlight at 10 o\u2019clock'],
      },
      lighting_read: {
        lighting_family: 'loop',
        source_quality: 'soft',
        source_direction: 'camera-left high',
        shadow_detail: 'Clean loop shadow drops from the nose at roughly 45°. Soft fill keeps shadow detail — jawline defined but not harsh.',
        contrast_level: 'high',
        color_temperature: '5500K — daylight balanced',
      },
      recreation_setup: {
        setup_family: 'single key + optional hair',
        modifier_suggestion: '90cm octabox or 70cm beauty dish with diffuser',
        light_count: 2,
        key_placement: '45° camera-left, elevated 15–20° above eye level',
        fill_strategy: 'No fill, or faint reflector at 1:8 ratio to hold shadow detail',
        background_strategy: 'Dark seamless or black vinyl — adds depth without distraction',
        focal_length: '85mm–135mm',
        aperture: 'f/2.0–f/2.8',
        setup_notes: [
          'Set key at 4–5 ft for tight control with the octabox.',
          'Flag the key light to prevent spill on the background.',
          'Hair light optional — grid spot behind subject at 1/8 power.',
        ],
      },
    },
  },
};

function _buildDemoInit(devModeUser) {
  if (!import.meta.env.DEV) return null;
  try {
    const params = new URLSearchParams(window.location.search);
    const demo = params.get('_demo');
    const base = { ...initialState, ...(devModeUser ? { user: devModeUser } : {}) };
    if (demo === 'results') {
      return { ...base, screen: 'results', result: DEMO_RESULT, apiResponse: {} };
    }
    if (demo === 'ref_eval') {
      // Use admin user so AdminCorrectionPanel renders; pass ?admin=0 to see user panel instead
      const adminUser = params.get('admin') === '0'
        ? (devModeUser || null)
        : { id: 'dev-admin', email: primaryAdminEmail(), username: 'Todd Willis' };
      return {
        ...base,
        user: adminUser,
        screen: 'ref_eval',
        referenceImage: DEMO_REF_IMAGE,
        referenceImages: [DEMO_REF_IMAGE],
        refAnalysis: DEMO_ANALYSIS,
      };
    }
    if (demo === 'symptom') {
      return { ...base, screen: 'symptom', symptomSlug: params.get('slug') || 'mixed-temperature' };
    }
    if (demo === 'ring_flash') {
      return { ...base, screen: 'results', result: DEMO_RING_RESULT, apiResponse: {} };
    }
    if (demo === 'analytics') {
      return { ...base, screen: 'analytics' };
    }
    if (demo === 'studio') {
      return { ...base, screen: 'day1_demo' };
    }
    if (demo === 'exec') {
      return { ...base, screen: 'exec' };
    }
  } catch { /* ignore */ }
  return null;
}

export function AppProvider({ children, devModeUser }) {
  const demoInit = _buildDemoInit(devModeUser);
  const init = demoInit || (devModeUser ? { ...initialState, user: devModeUser } : initialState);
  const [state, rawDispatch] = useReducer(reducer, init);

  // Haptic-enhanced dispatch wrapper — fires tactile feedback before state changes
  const dispatch = useCallback((action) => {
    switch (action.type) {
      case 'NAVIGATE':
      case 'GO_BACK':
      case 'NAVIGATE_SYMPTOM':
        navHaptic(); break;
      case 'SET_MOOD':
      case 'SET_SUBJECT_TYPE':
      case 'SET_ENVIRONMENT':
      case 'SET_SKIN_TONE':
      case 'SET_GEAR_MODE':
      case 'SET_MASTER_MODE':
      case 'SET_GEAR_PREFERENCE':
      case 'SET_APP_MODE':
      case 'SET_INTENT':
      case 'TOGGLE_MODIFIER':
      case 'SET_SHOOT_ROLE':
        selectHaptic(); break;
      case 'SET_RESULT':
        successHaptic(); break;
      case 'SET_ERROR':
        warnHaptic(); break;
      default: break;
    }
    rawDispatch(action);
  }, [rawDispatch]);

  return (
    <StateCtx.Provider value={state}>
      <DispatchCtx.Provider value={dispatch}>
        {children}
      </DispatchCtx.Provider>
    </StateCtx.Provider>
  );
}

export function useAppState() {
  return useContext(StateCtx);
}

export function useDispatch() {
  return useContext(DispatchCtx);
}

// ── Compatibility bridge ────────────────────────────────────────────────────
// Exported for Studio Matte wrappers (e.g. RoomPlannerWrapper) that need to
// provide minimal mock state to legacy screens without spinning up the full
// AppProvider + reducer. Not a new pattern — use only for legacy bridging.
export { StateCtx as _StateCtx, DispatchCtx as _DispatchCtx };
