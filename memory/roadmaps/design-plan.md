# VolScope Design Plan — Apple HIG × IBKR Functional Density

**Created:** 2026-05-03
**Owner:** Operator
**Status:** companion to volscope-giga-master-plan.md
**Guiding principle:** *Apple-modern surface, hedge-fund density. Information glows; chrome disappears.*

---

## Why this plan exists

The Master Plan delivered FUNCTION (Mega-Scan, Data Validator, Workflow Cohesion, page refactors). Function without aesthetic discipline ages fast — fonts drift, colors multiply, paddings get inconsistent.

Two design references, deliberately different:

- **Apple Human Interface Guidelines** — typography ladder, generous whitespace, single-purpose elements, content over chrome
- **IBKR TWS / Trader Workstation** — information density, monospace numerics, tabular alignment, no decorative noise

VolScope is hedge-fund-grade — it MUST keep IBKR's density. But it should LOOK like macOS Sonoma, not Windows 95. This document specifies how.

---

## Section 1 — Tokens (the design API)

A small, locked palette and type system that ALL pages call into. No page introduces ad-hoc colors or font sizes.

### 1.1 Color tokens

The current `theme.py::COLORS` dict is the source of truth. Locked semantic roles:

| Token       | Hex        | Use                                          |
|-------------|------------|----------------------------------------------|
| `bg`        | `#0a0b0f`  | page background — near-black with cool tint  |
| `surface`   | `#12131a`  | sidebar, large panels                        |
| `card`      | `#151620`  | every card / container one level above       |
| `hover`     | `#181924`  | hover states only                            |
| `border`    | `#1e2038`  | barely-visible dividers                      |
| `text`      | `#e0e4ef`  | primary text                                 |
| `muted`     | `#8a8f9e`  | secondary text                               |
| `label`     | `#424666`  | tiny uppercase labels                        |
| `accent`    | `#00d4aa`  | primary signal — cheap, buy, long-vol edge   |
| `accent2`   | `#5b8cff`  | secondary signal — calm, info                |
| `warn`      | `#ff4466`  | danger — rich, alert, distribution           |
| `amber`     | `#ff9f43`  | warning — watch                              |
| `gold`      | `#ffd700`  | highlight — earnings, crowded                |

**Discipline rules:**
- A new feature MUST reuse a token. Adding a hex-literal in any `.py` file is a code-review block.
- Severity colors are STRICT: `accent`=cheap/long, `warn`=rich/short, `amber`=watch, `accent2`=info. Never mix.
- Translucent fills derive ONLY from the semantic palette — `{token}22` for 13% alpha cards, `{token}11` for 7% alpha banners.

### 1.2 Type ladder

| Class           | Family            | Weight | Size  | Use                            |
|-----------------|-------------------|--------|-------|--------------------------------|
| `display`       | DM Sans           | 700    | 22px  | page H1 (Command Center title) |
| `title`         | DM Sans           | 700    | 16px  | section H3                     |
| `body`          | DM Sans           | 400    | 13px  | prose                          |
| `caption`       | DM Sans           | 400    | 11px  | secondary explanations         |
| `mono-display`  | JetBrains Mono    | 700    | 18px  | KPI numbers                    |
| `mono-data`     | JetBrains Mono    | 600    | 12px  | table cells, ticker labels     |
| `mono-meta`     | JetBrains Mono    | 400    | 10px  | timestamps, footnotes          |
| `mono-label`    | JetBrains Mono    | 600    | 9px   | UPPERCASE eyebrow labels       |

**Rules:**
- Numbers always use JetBrains Mono with `font-feature-settings: 'tnum'` (tabular numerals — keeps columns aligned).
- Prose, controls, and chrome use DM Sans. Mixing the two within one block is intentional contrast, not accident.
- No font outside this ladder. If a place needs a different size, the ladder grows by explicit edit.

### 1.3 Spacing scale

Tokens in 4-pixel increments — Apple's standard:

```
xs   4px   inline gaps within a single info chunk
s    8px   between sibling cells in a card
m   12px   card internal padding · between adjacent cards
l   16px   between sections within a page
xl  20px   between major page regions
xxl 28px   page top margin
```

**Rule:** any padding/margin must be one of `{4,8,12,16,20,28}`px. No `padding: 14px` random values.

### 1.4 Radius scale

```
4px    pills, badges, tiny buttons
6px    inline cards (KPI tiles, edge rows)
8px    major cards (Discover cheapest/richest cards)
10px   hero blocks (Today's Best Setup)
```

### 1.5 Border discipline

- Cards: `1px solid border` plus a `3px solid {accent}` left-border for variant identity.
- Dividers: a single `border-top: 1px solid border` line. Never a stroke + glow.
- Hover: NO border change. Background tint only (`hover` token).

---

## Section 2 — Component patterns

Every recurring UI element is a NAMED PATTERN with a canonical implementation. Pages call the pattern; they do not reinvent it.

### 2.1 KPI Tile

```
┌──────────────────────────┐
│ MONO-LABEL               │   ← `mono-label` 9px uppercase, color=label
│ JetBrains Mono 18 BOLD   │   ← `mono-display` 18px 700, color=accent_for_role
│ caption text             │   ← `mono-meta` 10px, color=muted
└──────────────────────────┘
   3px left-border, role color
   bg=card, border=border
   padding=12px, radius=6px
```

**Used by:** Mega-Scan hero strip, Pre-Trade Greeks tiles, Portfolio Greeks/VaR row, Backtest universe strip.

### 2.2 Severity Badge

```
[● LABEL]    inline pill
```

- Background `{role}22` · text `{role}` · border-left `2px solid {role}`
- font: `mono-label` 9px UPPERCASE
- padding: 2px horizontal, 1px vertical
- radius: 3px

**Used by:** Vol Pulse, Edge Score, Earnings Watch, Data Quality, Alert cards. Severity → color: `info`→`muted`, `watch`→`accent2`, `warn`→`amber`, `alert`→`warn`.

### 2.3 Ranked Row

```
┌─────────────────────────────────────────────────────┐
│ #N    TICKER   SCORE   ▰▰▰▰░░░░░░    one-line ctx  │
│       (badge)   (mono-display)                       │
└─────────────────────────────────────────────────────┘
```

**Used by:** Mega-Scan rankings (6 tiles), Discover tabbed rankings, Top-Edges strip on Command Center. The bar visualisation is normalised to score range — full-width = max in current ranking.

### 2.4 Section Header

```
─────────────────────────────────
SECTION TITLE
─────────────────────────────────
```

- 16px DM Sans bold, color `text`
- bottom margin: 12px
- NO uppercase transform (was uppercase pre-Pillar 5; reverted)
- single icon prefix optional (`⚡`, `◈`, `▷`)

### 2.5 Empty State

```
┌──────────────────────────────────────┐
│ ▶ No data yet                         │
│                                       │
│ One-paragraph explanation of why      │
│ this page is empty and how to fix it. │
│                                       │
│ [▶ Action button]                     │
└──────────────────────────────────────┘
```

- bg=card, accent left-border
- icon prefix: `▶` for "do something", `ℹ` for "informational"
- ALWAYS include a CTA button when one exists — never just text

### 2.6 Action Button

| Variant     | Use                                | Visual                          |
|-------------|------------------------------------|---------------------------------|
| `primary`   | the ONE most-likely next action    | filled accent bg                |
| `secondary` | alternative actions                | outlined / muted                |
| `inline-link` | "▷ Pre-Trade for QQQ" deep links | text-only with arrow glyph      |

**Rule:** at most ONE primary button per visible region. Sidebar, page header, in-card actions are separate regions.

---

## Section 3 — Layout grammar

### 3.1 Page anatomy

Every page follows this skeleton:

```
┌──────────────────────────────────────────────────────┐
│ HEADER STRIP — title + meta + freshness badge         │
│ BREADCRUMB ROW — ◈ Page · Ticker ← from Source        │
├──────────────────────────────────────────────────────┤
│ HERO REGION — single most-important answer            │
│   (Today's Best Setup, Vol Pulse, KPI strip…)         │
├──────────────────────────────────────────────────────┤
│ SUPPORTING REGIONS — tabs or 2-3 column grid          │
├──────────────────────────────────────────────────────┤
│ DEEP-DIVE EXPANDERS — collapsed by default            │
└──────────────────────────────────────────────────────┘
```

### 3.2 Density principle

Apple's mistake (in financial UIs): too much whitespace dilutes density.
IBKR's mistake: zero whitespace = wall of numbers.

VolScope's split: **dense within a card, generous between cards.**

- Card internal padding: 12px (mono numbers tight)
- Between cards: 16px gap
- Between page regions: 20-28px

### 3.3 Responsive grid

CSS `auto-fit` minmax pattern, not fixed columns:

```css
display: grid;
grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
gap: 12px;
```

**Used by:** YOUR MARKETS cards, Mega-Scan hero strip, Pre-Trade Greeks tiles. At narrow viewports (`< 800px`) the grid collapses naturally.

---

## Section 4 — IBKR-style data discipline

### 4.1 Number formatting

- Prices: `$<integer>,<3-digit-thou-sep>.<2-decimal>` — `$1,234.56`
- IV percent: `<num>.1f%` — `22.4%`
- Deltas / vega / theta: signed: `+0.42`, `-1.23`, never bare `0.42`
- Counts: `<integer>,<3-digit-thou-sep>` — `12,345`
- N/A or missing: `—` (em-dash), never `N/A` or empty
- Tabular: `font-feature-settings: 'tnum'` always

### 4.2 Color semantics for numbers

- Profit / cheap / long-vol gain: `accent` (`#00d4aa`)
- Loss / rich / long-vol pain: `warn` (`#ff4466`)
- Neutral / context: `text` (white) or `muted` (grey)
- Above 50 / below 50 percentile: NOT green/red — only `accent2` highlights, since percentile alone isn't directional

### 4.3 Information hierarchy in tables

```
TICKER COMPANY      IV    Δ%    PERC  RANK  SECTOR
NVDA   NVIDIA       45.2  +3.1  78    72    Semis
```

- Ticker column: `text`, mono-data 600-weight
- Company: `muted`, mono-data 400-weight, smaller
- Numbers: tnum mono, role-colored
- Sector / metadata: rightmost, `muted`

---

## Section 5 — Iconography

A SMALL deliberate set, all unicode (no icon font dependency for core glyphs):

| Glyph | Meaning                                            |
|-------|----------------------------------------------------|
| ◈     | brand mark · current page · ticker badge          |
| ⚡     | command center · accent action                     |
| ▷     | trade · execute · open in pre-trade                |
| ◎     | mega-scan                                          |
| 📈    | vol view tab                                       |
| 💲    | price view tab                                     |
| ▣     | backtest                                           |
| 💎    | cheap                                              |
| 🔥    | rich                                               |
| ⚠     | alert · warning                                    |
| ●     | severity badge marker                              |
| ▲ ▼   | up / down — momentum, accumulation/distribution    |
| ↻     | refresh                                            |
| ✕     | dismiss · remove · close                           |
| ➕     | add                                                |
| 📥    | export                                             |
| 📅    | earnings · calendar                                |

Material Symbols are imported in CSS as fallback for Streamlit's chrome (chevrons, caret) — this fix landed in Pillar 5 to eliminate the `keyboard_→` literal-text bug.

---

## Section 6 — Motion

VolScope is a data-dense terminal. Motion should be invisible:

- **No** entrance animations (cards don't fade in)
- **No** scroll-linked effects
- **No** parallax
- Hover transitions: `120ms ease-out` background-color only
- Plotly chart resize: built-in transition — accept default
- Page navigation: instant (Streamlit rerun)

The single allowed animation: a 200ms green flash on a successful save (Toast).

---

## Section 7 — Accessibility floor

- Minimum text contrast: 4.5:1 against bg (the current palette satisfies this)
- All click targets ≥ 32×32 logical pixels
- All buttons have visible labels (no icon-only buttons except `✕` close)
- Color is NEVER the sole signal — severity badges include text label, not just color
- Keyboard shortcuts (`?` cheatsheet, `g d` Discover, etc.) survive — `keyboard_shortcuts.py` already implements

---

## Section 8 — Page-by-page application

How each page applies the system. Anti-drift checklist:

| Page         | KPI tiles | Section headers | Cards w/ accent | Tabs | Tabular nums |
|--------------|:---------:|:---------------:|:---------------:|:----:|:------------:|
| Command      |    ✓      |       ✓         |       ✓         |  -   |      ✓       |
| Discover     |    ✓ hero |       ✓         |       ✓         |  ✓   |      ✓       |
| Portfolio    |    ✓      |       ✓         |       ✓         |  -   |      ✓       |
| Mega-Scan    |    ✓      |       ✓         |       ✓         |  -   |      ✓       |
| Scope        |     -     |       ✓         |       ✓         |  ✓   |      ✓       |
| Scanner      |     -     |       -         |       -         |  -   |      ✓       |
| Heatmap      |     -     |       -         |       -         |  -   |      ✓       |
| Rotation     |     -     |       ✓         |       ✓         |  -   |      ✓       |
| Flow         |     -     |       ✓         |       ✓         |  -   |      ✓       |
| Pre-Trade    |    ✓      |       ✓         |       ✓         |  -   |      ✓       |
| Backtest     |    ✓ hero |       ✓         |       -         |  -   |      ✓       |

---

## Section 9 — Definition of Done (for Design)

This plan is COMPLETE when:

- [ ] All 6 component patterns documented + implemented (KPI tile, badge, ranked row, section header, empty state, action button)
- [ ] No hex literals in any `.py` file outside `theme.py` (grep audit clean)
- [ ] No font-size literals outside the 8-class ladder (grep audit clean)
- [ ] No padding/margin values outside `{4,8,12,16,20,28}`
- [ ] Page anatomy skeleton holds across all 11 pages
- [ ] Tabular nums set on every numeric column / KPI value
- [ ] Material Symbols import survives `make verify` runtime smoke

This document is the contract against which any future page-design PR is reviewed.

---

## Section 10 — What we deliberately are NOT building

| Idea                            | Why deferred                                  |
|---------------------------------|-----------------------------------------------|
| Light theme                     | Chartists work in dark; high-contrast toggle suffices |
| Custom font foundry             | DM Sans + JetBrains Mono are excellent and free |
| Iconography font                | Unicode + Material Symbols cover everything |
| Branded cursor                  | Friction without value                        |
| Animated splash screen          | First-paint speed > brand moment              |
| Theme builder UI                | One owner, one taste — no theming              |
| Customisable layouts            | Adds complexity; YAGNI                         |

---

## How this plan sequences with the Master Plan

- **Master Plan** delivered the structural changes (Pillars 1-5)
- **This Design Plan** documents the aesthetic system the structure already (mostly) follows
- New work uses BOTH plans as its constitution: function from Master, form from Design

When the two conflict, the Master Plan's quality gates (test count, verify PASS) win. Design quality is enforced by code review, not automated tests.
