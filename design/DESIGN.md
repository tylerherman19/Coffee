# Design system - Coffee Prices v3 (draft for approval)

Concept: "The city price board" - an editorial data directory for two
metros. Warm paper + ink + one persimmon accent. The data (prices,
distances, open state) is the visual content; chrome disappears.

## Color tokens (by job)
- --paper:   #FFF9ED  page background (existing warm paper, kept)
- --surface: #FFFFFF  interactive surfaces, inputs, sticky bars
- --ink:     #231D18  text, rules, fills (one step off old brown #2e1d16
             toward the refs' #181818; warm, not gray)
- --muted:   #6E6259  secondary text
- --line:    #E7DFCF  hairlines only (1px; 2px ink reserved for one rule:
             under the masthead)
- --accent:  #E45F35  persimmon: active states, key figures, the one
             wordmark block. Never behind body copy (fills only on
             small controls: toggles, buttons, markers).
- Hover wash on rows: color-mix(paper 55%, white) - flat, no shadow.

## Type (Fraunces display + DM Sans UI, already loaded)
Scale (px, desktop/mobile where they differ):
- wordmark:        Fraunces 650, 20px, -0.01em
- page title:      Fraunces 600, 32/26, -0.02em (was 70px: killed)
- shop name:       Fraunces 600, 17px
- price figure:    Fraunces 620, 19px, font-feature "tnum", right column
- body/UI:         DM Sans 400-500, 14.5px
- meta (distance, hood, open, counts): DM Sans 500, 12.5px
- labels:          DM Sans 600, 11px, +0.08em, caps - sparingly, only for
                   true labels (section markers), never decorative eyebrows
- all numerals tabular ("tnum"): prices, distances, counts, medians

## Spacing / radii / borders
- Scale: 4 8 12 16 24 40 64. Rows: 13px vertical. Shell gutters:
  clamp(18px, 4vw, 56px).
- Radius: 0 everywhere; 2px allowed on small controls only.
- No shadows. No gradients. Flat fills only.

## Grid
- Desktop >=1100px: 12-col, max 1240px. Left rail (200px, sticky): view
  switch (Near/Compare/Shops/Map as a vertical index with rules, not a
  pill row), metro switch, has-prices switch, filters. Content: 8 cols.
  Map view: full-bleed canvas, rail overlays as a floating panel.
- Tablet 768-1099: rail collapses to a top bar.
- Mobile <768 (primary): sticky compact masthead (wordmark + metro),
  bottom tab bar (kept), filters in one horizontal scroll row.
- The centered 860px single column is dead.

## Price visual language
- Right-aligned fixed figure column (72px) on every list row: Fraunces
  tabular 19px over an 11px muted drink label. Baseline-aligned with the
  shop name. $3.50 vs $7.25 reads at a glance by position + weight, no
  bars, no badges, no "DEAL" chips.
- Compare adds a real computed context line: "median $4.75 across N
  shops" plus per-row delta (+$0.50/-$1.25) in muted. Computed from real
  data only.

## Lists / rows
- Hairline-divided directory rows, no cards. Rank in muted tabular 12px.
- Hover: flat paper-white wash + price turns accent. No translate, no
  shadow. Selected: ink-left 2px rule + white wash.
- One meta line per row: "0.2 mi - Plymouth - Open now". No second line.

## Controls
- Metro: segmented two-option switch (square, 1px ink border, active =
  ink fill paper text) - pattern he has already approved.
- Has-prices: same switch family with a real on/off state label
  ("Priced only" / "All shops" as state text, not a badge).
- Drink picker on Compare: underline tabs in a scroll row, not boxed
  pills.

## Map
- Basemap: CARTO Positron (light, neutral) so the map belongs to the
  palette; attribution kept. Markers: 22px square ink chip w/ paper cup
  glyph; priced state accent; cluster: 26px ink, count in DM Sans 11px.
- Selected shop: marker scales 1.25 + ink fill; popup restyled to the
  same type rules (Fraunces name, tabular price, square "See menu").

## Motion tokens
- --dur-1 120ms (hover/press), --dur-2 200ms (view switches, filters),
  --dur-3 320ms (map<->list, detail open). Ease: cubic-bezier(.2,.6,.2,1).
- View switches: 200ms crossfade + 8px rise, shared masthead (no full
  repaint feel). List filtering: opacity + 6px settle, 15ms stagger,
  capped at first 12 rows. Metro switch: list crossfade, map pans.
- Location on: rows reorder with a 240ms FLIP-lite (opacity/transform),
  count ticks. All animation off under prefers-reduced-motion.
- CSS only; no animation library (brief allows, but nothing here needs
  more than transforms + opacity).

## Copy rules
- Plain factual lines: "Coffee near you", "52 shops - Twin Cities".
- Killed: all decorative eyebrows, "Every cup on the map", anything that
  explains the product to itself.

## States to design (Pass 8)
- Loading: skeleton rows (hairlines + figure placeholders), no spinner
  alone; geolocation asking: one quiet line "Finding you..."; denied:
  plain sentence + retry button; empty filter result: one line + clear
  control; error: plain sentence + retry.
