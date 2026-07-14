# Pilgrimage Atlas Design System

## Product character

A calm, editorial travel workspace with map-atlas cues: trustworthy, source-forward, and practical rather than gamified. The interface must make uncertainty, provenance, and user confirmation visible without feeling bureaucratic.

## Semantic color tokens

| Token | Light | Purpose |
|---|---:|---|
| `canvas` | `#f4f1e9` | warm page background |
| `surface` | `#fffdf8` | primary panels |
| `surface-strong` | `#ffffff` | raised controls and cards |
| `ink` | `#17231f` | primary text |
| `ink-muted` | `#51615a` | secondary text |
| `line` | `#d5ddd7` | borders and dividers |
| `primary` | `#164d44` | primary actions and active state |
| `primary-hover` | `#0f3c35` | hover/pressed state |
| `primary-soft` | `#dcebe4` | selected surface |
| `accent` | `#b93625` | priority and route emphasis |
| `warning` | `#8a570e` | needs-confirmation states |
| `danger` | `#9f2f2f` | destructive/error states |

Never convey status by color alone; pair tokens with text and a consistent Lucide outline icon.

## Typography

- UI/body: system sans stack with Japanese and Chinese fallbacks; 16px minimum on mobile, 1.55 line height.
- Editorial display: system serif stack for the primary page title only.
- Scale: 12 / 14 / 16 / 18 / 24 / 32 / 48, with tabular figures for time, distance, and price.
- Long text measure: 60–72 characters on desktop, 35–60 on mobile.

## Layout and interaction

- Mobile-first at 375px; enhance at 768px, 1024px, and 1440px.
- 4px base and 8px spacing rhythm; 16px mobile gutters and 24–32px desktop gutters.
- Maximum content width 1600px. At 1180px and wider, the core planning workspace uses three persistent zones: 320px conversation, flexible map/itinerary canvas, and 320px context/version inspector. Below that, zones become labelled tabs without losing state.
- Default planning geography is Area and canonical VisitPlace. Raw SceneEvidence is an explicit drill-down with visible counts, never the default marker set.
- Route A and Route B remain a visually separated compatibility section below the workspace until old consumers migrate; they must not determine the primary navigation hierarchy.
- Every interactive control is at least 44×44px with an 8px gap and visible 3px focus ring.
- Use one primary call to action per state. Confirmations must be explicit and reversible until external navigation.
- Motion is 150–250ms and limited to opacity/transform. Respect `prefers-reduced-motion`.
- Preserve scroll/input state; avoid nested scrolling on mobile and horizontal overflow everywhere.

## Surface language

- 12–20px radii, one subtle shadow scale, crisp 1px borders.
- Atlas/grid motifs may appear as low-contrast CSS backgrounds, never behind dense text.
- No emoji as structural icons, no decorative glass blur, no invented third-party imagery, no animation without state meaning.

## Accessibility and responsive acceptance

- WCAG AA text contrast, semantic landmarks/headings, skip link, visible labels, inline recovery errors, `aria-live` for async status.
- Keyboard order matches the visual flow. Icon-only controls require accessible names.
- Test desktop at 1440×900 and mobile at 375×812, including 200% text, reduced motion, and no horizontal scrolling.
