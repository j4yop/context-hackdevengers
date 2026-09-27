# Design System

<!-- impeccable:design-schema 1 -->

The committed visual world for contextgc. This records what the product already
looks like so it cannot drift; it is not a proposal. Where a value below is
wrong, change the CSS and this file together, not one of them.

Source of truth: `web/style.css`. Two documents, one stylesheet — the landing
page and the console are separate pages that must not become two products.

## Direction

An instrument panel, not a marketing page. The thing on screen is a measurement,
and the design's job is to make a number traceable to the turn that produced it.
That produces three commitments:

- **Provenance is visible.** Every fact carries where it came from (`declared`,
  `inferred`, `pinned`, `retired`) as a tag, not a tooltip.
- **Colour means severity, never decoration.** `--good` / `--warn` / `--bad` are
  the only semantic colours, and each has a paired background and border so it
  works as a filled surface.
- **The caveat travels with the claim.** A 0% reduction is shown as 0%, and a
  banner above it says the register cost more than it saved. A number that only
  reads well when it is favourable is not a measurement.

## Tokens

Declared once on `:root`, overridden once under
`@media (prefers-color-scheme: dark)`. There is no third theme and no inline
colour in either page.

### Surfaces and ink

| token | light | dark | used for |
|---|---|---|---|
| `--bg` | `#fbfbfd` | `#0c0d10` | page |
| `--panel` | `#fff` | `#14161a` | cards, header, footer |
| `--panel-2` | `#f7f8fa` | `#191c21` | inputs, code blocks, hover |
| `--line` | `#e4e7ec` | `#262a31` | card and section borders |
| `--line-2` | `#eef0f3` | `#1e2127` | internal rules, table rows |
| `--ink` | `#101828` | `#e8eaed` | body |
| `--ink-2` | `#475467` | `#a8b0be` | secondary prose |
| `--ink-3` | `#8a94a6` | `#8a93a3` | micro-labels, captions |

`--ink-3` is the one that fails silently: it was 3.6–4.1:1 on dark panels and was
lifted. Any new use of it must be checked at 4.5:1 against `--bg`, `--panel`
*and* `--panel-2`.

### Accent

| token | light | dark |
|---|---|---|
| `--accent` | `#2f5fe0` | `#7fa2ff` |
| `--accent-ink` | `#1c3f9e` | `#a8c0ff` |
| `--accent-bg` | `#eef3ff` | `#16203a` |
| `--accent-line` | `#c7d7fb` | `#2f4166` |
| `--on-accent` | `#fff` | `#0b1220` |

`--on-accent` exists because the dark accent is a *light* blue: white on it
measured 2.5:1. A light accent in a dark theme takes dark text. Never hard-code
`#fff` on an accent surface.

`--accent-line` exists for the same reason as `--good-line` / `--warn-line` /
`--bad-line`: the accent note's border was a hardcoded `#c7d7fb` sitting beside a
dark-theme `#16203a` surface.

### Semantic

Each severity is a triple — foreground, background, border — so it works as a
filled surface and as text.

| | light fg / bg / line | dark fg / bg / line |
|---|---|---|
| `--good` | `#0f7a52` / `#e9f7f0` / `#b6e3cd` | `#4ed7a0` / `#0f2620` / `#1d4a3a` |
| `--warn` | `#8a5a00` / `#fdf5e4` / `#f0dcae` | `#e8b765` / `#2a2113` / `#4d3d1c` |
| `--bad` | `#b42318` / `#fdefee` / `#f5c9c4` | `#f28b82` / `#2a1615` / `#4d2724` |

## Type

- **Inter** for everything, weights 400/500/600/700.
- **JetBrains Mono** for code, telemetry, identifiers and measured values —
  *only* for things that are code, data or measurement. It is not a costume for
  sounding technical. Never for prose.
- `--mono` falls back to `ui-monospace, SFMono-Regular, Menlo` so a font failure
  degrades to a monospace rather than to the system sans.

| role | size | line-height | tracking |
|---|---|---|---|
| hero `h1` | `clamp(30px, 5vw, 50px)` | 1.06 | −0.033em |
| section `h2` | `clamp(21px, 2.6vw, 27px)` | 1.3 | −0.028em |
| page `h2` (cta band) | 24px | 1.35 | −0.024em |
| `h3` | 16.5px | inherited | −0.018em |
| body | 15px | 1.55 | 0 |
| `code`, `pre` | 12.5–13px | 1.6 | 0 |
| micro-label (`.k`, `figcaption`, `th`) | 11px | 1.45 | 0.06em, uppercase |

Tracking never goes past −0.04em. Body measure caps at 64ch.

## Layout

- `--wrap` max-width 1200px, 20px gutters.
- The console is a two-column grid, `minmax(0,1fr) minmax(0,1.05fr)`, collapsing
  to one column at 940px. **`align-items: stretch`, never `start`**: the output
  panel is the point of the page, and pinned to its own height it sat as a 240px
  stub beside an 850px input.
- Sections carry more space above the heading than below it. 52–60px above a
  band, 8–10px below its lede.
- The landing page's four mechanisms are **hairline-separated rows**, not equal
  cards. Their content differs by an order of magnitude — a nine-line JSON block
  next to a two-line state register — and forcing them into equal boxes presents
  them as equal claims. Prose beside the code, collapsing to one column at 820px.
- The measured-results table is a table on wide screens and **one block per
  corpus below 760px**, every measurement naming itself via `data-label`. At 390px
  six columns rendered "Coding" as "Cod ing".

## Components

| component | shape |
|---|---|
| card | `--panel`, 1px `--line`, 14px radius. Elevation is a border, never a shadow. |
| button | 9px radius, 14px, weight 600. Primary fills `--accent` with `--on-accent`. |
| segmented control | `--panel-2` track, 3px inset, 6px radius; `aria-pressed` carries state. |
| input / textarea | `--panel-2`, 1px `--line`, 9–10px radius; `:focus` is a 2px `--accent` outline at −1px offset, inside the border. |
| stat tile | `--panel`, 13/14px padding, flex column, value pinned to the cell bottom so **all five values share one baseline** regardless of label wrap. |
| tag | 999px pill, 11px mono, semantic background. Only for provenance and status. |
| note | 10px radius, semantic triple, 13px. The banner is how a caveat reaches the reader. |
| code block | `--panel-2`, 1px `--line`, 10px radius, `pre-wrap` + `break-word`. Long identifiers wrap rather than widen the page. |
| primary CTA | 10px radius, 15px, fills `--accent`. Anchors and buttons share the `.btn` shape. |

## Rules that exist because they were violated

- **`[hidden] { display: none !important; }`** is declared globally. An author
  `display` on a component beats the UA stylesheet's `[hidden]` rule, and the
  empty state stayed on screen above a full result because of it.
- **Hover must be checked against specificity, not just order.** A generic
  `.btn:hover` won over `a.btn.primary:hover` and put dark ink on a dark panel
  at 1.2:1.
- **Micro-labels are uppercase and letterspaced; body copy never is.**
- **The header must stay one line at 320px.** Below 520px the wordmark shrinks
  and the nav tightens.
- **`.empty` is a flex column that offers a way forward** — a button that loads
  the example, not just an instruction to paste something.
- **Empty-state copy must not describe a spatial relationship.** It said "on the
  left" in a layout that stacks.
- **Stat values share a baseline.** A sublabel that wrapped in one cell and not
  another pushed its value out of line with the row.

## Surfaces

- **`/` — landing.** Persuade. Leads with the real problem, demonstrates with a
  real compile (39.6% smaller, the reversed upgrade retired), then the three
  corpora with `n`, then the mechanisms, then the limits, then the console CTA.
- **`/console` — the tool.** Operate. Input, controls, compiled output. The
  output panel carries the provenance tables, the metrics and the banners, and
  is the reason the page exists.

Both share the header, the footer and `web/style.css`. The primary CTA on the
landing page targets `/console`; the console's header carries a current-page
marker.

## Verification

Contrast is measured in a real browser against computed styles, not asserted
from the palette — the 2.5:1 and 1.2:1 failures were both invisible in a
screenshot and both real. `tests/browser/page.mjs` drives both surfaces, both
themes, and 320–1440px, and fails on any horizontal overflow, console error or
failed request.
