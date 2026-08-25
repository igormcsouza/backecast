// Every episode gets a generated cover — no image upload or AI image model
// needed (see the "Backecast — Design system" reference page, Cover art
// section: "generated cover art, no upload needed. The episode id is
// hashed into a seeded PRNG that picks two colors from a curated
// frozen-green palette (one warm gold accent tossed in for variety),
// mixed from determinism, not chance." Regenerating the art for real would
// mean persisting a chosen seed on the episode — the admin review screen's
// "Regenerate" is greyed out until that lands (see the linked backend
// issue); this stays purely a deterministic function of the episode id so
// every visitor sees the same art for the same episode without storing
// anything.

const PALETTE = [
  "#1f6b4d", // deep green
  "#2f8f63", // core green
  "#5fbf8f", // light green
  "#7a9a4a", // olive
  "#c9932f", // gold
  "#3a7a6a", // teal-green
];

function hashSeed(seed: string): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

// Small mulberry32 PRNG so the same seed always yields the same sequence.
function mulberry32(seed: number) {
  let a = seed;
  return function random() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface CoverArt {
  gradient: string;
  waveform: number[];
}

export function generateCoverArt(seed: string, bars = 24): CoverArt {
  const random = mulberry32(hashSeed(seed || "backecast"));
  const colorA = PALETTE[Math.floor(random() * PALETTE.length)];
  let colorB = PALETTE[Math.floor(random() * PALETTE.length)];
  if (colorB === colorA) {
    colorB = PALETTE[(PALETTE.indexOf(colorA) + 2) % PALETTE.length];
  }
  const angle = Math.floor(random() * 60) + 150; // 150deg-210deg, top-to-bottom-ish
  const gradient = `linear-gradient(${angle}deg, ${colorA}, ${colorB})`;

  const waveform = Array.from({ length: bars }, () => 0.15 + random() * 0.85);

  return { gradient, waveform };
}
