// NOT a test. A benchmark, run manually to compare two checkouts:
//   node measure-scroll.mjs   with BASE and LABEL set
// Prints a JSON line. Nothing asserts on it, and it is not in CI --
// a perf number is not a gate, it is evidence for a decision.
// Measures main-thread work while scrolling, so the change can be compared
// rather than described.
//
// Method: attach via CDP, read TaskDuration/ScriptDuration before and after a
// fixed 3s window of continuous programmatic scrolling, and report the
// delta. The delta is the main-thread time the browser spent working while the
// user was scrolling -- which is the thing "it feels janky" actually is.
//
// The two states differ in exactly one commit's worth of CSS/JS, so the number
// is attributable.
import { chromium } from 'playwright';
import { setTimeout as sleep } from 'node:timers/promises';

const BASE = process.env.BASE || 'http://localhost:8932';
const LABEL = process.env.LABEL || 'state';

const metric = async (cdp, name) => {
  const { metrics } = await cdp.send('Performance.getMetrics');
  return (metrics.find((m) => m.name === name) || {}).value || 0;
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const cdp = await page.context().newCDPSession(page);
await cdp.send('Performance.enable');
await page.goto(BASE + '/', { waitUntil: 'load' });
await sleep(1500);

const scrollFor = async (ms) => {
  const t0 = Date.now();
  await page.evaluate(async (duration) => {
    const start = Date.now();
    return new Promise((done) => {
      function tick() {
        window.scrollBy(0, 14);
        if (Date.now() - start < duration) requestAnimationFrame(tick);
        else done();
      }
      requestAnimationFrame(tick);
    });
  }, ms);
};

// Warm up so first-paint work is not counted as scroll cost.
await sleep(500);
await sleep(300);

const t0 = await metric(cdp, 'TaskDuration');
const s0 = await metric(cdp, 'ScriptDuration');
const l0 = await metric(cdp, 'LayoutDuration');
const r0 = await metric(cdp, 'RecalcStyleDuration');
const wall0 = Date.now();

await sleep(3000);
await sleep(200);

const t1 = await metric(cdp, 'TaskDuration');
const s1 = await metric(cdp, 'ScriptDuration');
const l1 = await metric(cdp, 'LayoutDuration');
const r1 = await metric(cdp, 'RecalcStyleDuration');
const wall = (Date.now() - wall0) / 1000;

const pct = (d) => ((d / wall) * 100).toFixed(1);
console.log(JSON.stringify({
  label: LABEL,
  wallSeconds: +wall.toFixed(2),
  mainThreadBusyPct: pct(t1 - t0),
  scriptPct: pct(s1 - s0),
  layoutPct: pct(l1 - l0),
  stylePct: pct(r1 - r0),
  taskSeconds: +(t1 - t0).toFixed(3),
}));

await browser.close();
