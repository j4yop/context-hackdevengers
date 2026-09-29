# Browser tests

Real browser, real page. Static checks missed a broken site before and a
scroll-performance problem after, so both are driven rather than audited.

| file | in CI | what it is |
|---|---|---|
| `page.mjs` | yes | the page boots, renders, and makes its network calls |
| `scroll.mjs` | yes | the scroll path defers work: header blur drops while scrolling, off-screen sections are `content-visibility: auto`, the canvas caps its frame rate and stops when the tab is hidden, and content still renders at the bottom |
| `shots.mjs` | no | screenshots |
| `measure-scroll.mjs` | no | benchmark, not a test. Prints main-thread time during a 3s scroll |
| `measure-idle.mjs` | no | benchmark, not a test. Prints main-thread time while idle |

## Why there is no `loading="lazy"` here

The ask was lazy loading. There is nothing to lazy load: the site is markup,
CSS and inline JS with **zero** `<img>`, `<video>`, `<iframe>`, external
`<script>`, `url()` or `@import`. `loading="lazy"` on an image that does not
exist is a no-op that reads like a fix.

For a page made of text the equivalent lever is `content-visibility: auto` with
`contain-intrinsic-size`, and the two halves are only correct together — without
the intrinsic size every skipped section lays out at zero height, the page
collapses to the first screen, and the scrollbar starts lying.

The scroll cost that did exist:

* `backdrop-filter: blur(14px)` on a `position: sticky` header. A sticky element
  with a backdrop filter re-rasterises the blurred backdrop for **every** scroll
  frame. The blur is now applied at rest and traded for an opaque fill while
  `.is-scrolling` is set, so it costs nothing during the movement it was
  making expensive.
* a `requestAnimationFrame` loop that rescheduled itself from inside its own
  callback, forever, at the display refresh rate, with an O(n²) link pass —
  3,570 pairs at 85 nodes. It now runs at 30fps, stops on `visibilitychange`,
  and `resize` no longer rebuilds every node on every resize event.
* ten `transition: all` declarations, replaced with explicit property lists.
  `all` animates layout-affecting properties nobody intended to animate.

## Measured

Headless Chromium, 1280×800, 3s window, `TaskDuration` from CDP. Two checkouts
differing only in this commit:

| | before | after | |
|---|---|---|---|
| idle main-thread | 6.5% | **3.1%** | 53% less |
| scrolling main-thread | 5.9% | **4.8%** | 19% less |

A synthetic scroll on a fast machine understates it; the cost scales with pixel
ratio and blur radius, both of which are higher on a real display.
