// Drive the real page in a real browser. Static checks missed a broken site last
// time; this asserts the rendered DOM and the actual network calls.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

// `server.main` is only importable from the repository root.
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

const PORT = Number(process.env.PORT || 8914);
const BASE = process.env.BASE || `http://localhost:${PORT}`;
// The landing page and the console are separate documents now. `HOME` is the
// marketing surface; `CONSOLE` is the tool. Hardcoding one and assuming they are
// the same page is what let the console's controls outlive the split untested.
const HOME = `${BASE}/`;
const CONSOLE = `${BASE}/console`;

/** Start the real server and wait for it to answer. */
async function startServer() {
  // Refuse to start if the port is already taken, rather than spawning and
  // racing for it. A server left over from an earlier run answers /api/health
  // and every route this test probes, so the suite then measures the OLD code
  // and reports it as a failure of whatever was just changed. That happened
  // twice here: once looking like `/console` was broken, once looking like the
  // schema evidence had not been wired up. Both were a stale process, and both
  // cost more time than this check.
  if (!process.env.BASE) {
    const busy = await fetch(BASE + '/api/health').then(() => true).catch(() => false);
    if (busy) {
      throw new Error(
        `port ${PORT} is already answering. A previous run left its server up, and\n` +
        `this run would silently measure that one instead of the current code.\n\n` +
        `  lsof -nP -iTCP:${PORT} -sTCP:LISTEN   # find it\n` +
        `  pkill -f "port ${PORT}"                # or stop it and re-run\n\n` +
        `Or set BASE to test an already-running deployment.`
      );
    }
  }
  const proc = spawn(
    'python3',
    ['-m', 'uvicorn', 'server.main:app', '--port', String(PORT), '--log-level', 'warning'],
    { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'] }
  );
  let log = '';
  proc.stdout.on('data', (d) => { log += d; });
  proc.stderr.on('data', (d) => { log += d; });
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(BASE + '/api/health');
      if (r.ok) return { proc, log: () => log };
    } catch { /* not up yet */ }
    await sleep(500);
  }
  proc.kill();
  throw new Error('server did not start:\n' + log);
}
const fails = [];
const ok = (cond, label, extra='') => {
  console.log(`  ${cond ? 'PASS' : 'FAIL'}  ${label}${extra ? '  ' + extra : ''}`);
  if (!cond) fails.push(label);
};

async function main() {
const server = process.env.BASE ? null : await startServer();
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [], failedReqs = [];
page.on('pageerror', e => errors.push(String(e)));
// No filtering. Every console error on the main page is unexpected, because the
// one request that is meant to fail now happens on a separate page.
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('requestfailed', r => failedReqs.push(`${r.method()} ${r.url()}`));
page.on('requestfailed', r => failedReqs.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));

console.log('\n1. the landing page and the console are separate surfaces');
const home = await page.goto(HOME, { waitUntil: 'networkidle' });
ok(home.status() === 200, 'GET / returns 200', `status=${home.status()}`);
ok((await page.title()).length > 0, 'title set', await page.title());

// The landing page must not be the console. Both directions: a landing page that
// is secretly a tool is confusing, and a console link that 404s is worse.
const homeText = await page.textContent('body');
ok(!/Paste a transcript on the left/i.test(homeText),
   'landing page is not the console');
const consoleLink = await page.getAttribute('a.btn.primary', 'href');
ok(consoleLink === '/console', 'primary CTA points at the console', String(consoleLink));
const stylesheet = await page.evaluate(() =>
  getComputedStyle(document.body).getPropertyValue('--accent').trim());
ok(stylesheet !== '', 'the shared stylesheet actually applied',
   `--accent: ${stylesheet}`);

const resp = await page.goto(CONSOLE, { waitUntil: 'networkidle' });
ok(resp.status() === 200, 'GET /console returns 200', `status=${resp.status()}`);
ok(await page.isVisible('#src'), 'console has the input');
ok((await page.title()).includes('Console'), 'console title says so', await page.title());
const backLink = await page.getAttribute('header nav a[href="/"]', 'href');
ok(backLink === '/', 'console links back to the overview');

console.log('\n1b. the landing page states measurements, not adjectives');
// A percentage with no n next to it is advertising, and this project's whole
// argument is that it does not do that. Checked against the text a reader sees.
const landingText = await (await fetch(HOME)).text();
for (const [label, re] of [
  ['coding reduction', /66\.5%/],
  ['airline reduction', /59\.0%/],
  ['retail reduction', /62\.5%/],
  ['sample sizes', /40 transcripts/],
  ['precision confidence intervals', /CI 90/],
  ['honest write-path limit', /34% of declared keys/],
]) ok(re.test(landingText), `landing page quotes the ${label}`);

ok(!/has been benchmarked against real agent traces/i.test(landingText),
   'the "not benchmarked yet" claim is gone -- it was false, and the numbers above refute it');
ok(!/Nothing here is benchmarked/i.test(landingText), 'and no variant of it survives');

// Every internal link must resolve. A 404 in the primary path is the one bug a
// screenshot cannot show.
for (const href of ['/console', '/style.css']) {
  const r = await fetch(BASE + href);
  ok(r.ok, `${href} resolves`, `status=${r.status}`);
}


console.log('\n2. schema picker is populated from /api/schemas');
// <option> is never "visible" to Playwright, so wait on the count instead.
await page.waitForFunction(
  () => document.querySelectorAll('#schem option').length > 1, null, { timeout: 10000 });
const opts = await page.$$eval('#schem option', os => os.map(o => ({v:o.value, t:o.textContent.trim()})));
ok(opts.length >= 4, 'schema options rendered', `${opts.length} options`);
ok(opts[0].v === '', 'first option is the empty default');
console.log('       ' + opts.map(o => o.v || '(none)').join(', '));

console.log('\n3. empty default is explained, not silently blank');
const noteVisible = await page.isVisible('#schema-note');
const noteText = noteVisible ? (await page.textContent('#schema-note')).trim() : '';
ok(noteVisible, 'schema note visible before any run');
ok(/no entity schema is selected|ships an empty entity schema/i.test(noteText), 'note explains the empty default');

console.log('\n4. clicking Compile with no schema shows an honest empty state');
await page.fill('#src', 'user: deliver order ORD-1 to Tower B, Flat 402\nuser: change the address to Gate 2 security entrance\nuser: thanks');
await page.click('#go');
await page.waitForSelector('#result:not([hidden])', { timeout: 15000 });
const resText = await page.textContent('#result');
ok(/No state tracked/i.test(resText), 'state panel says no state tracked (not "nothing found")');
ok(/no entity schema is selected/i.test(resText), 'and says why');
ok(/Reduction/i.test(resText), 'metrics still rendered');

console.log('\n5. selecting a schema makes state tracking actually work');
// Take the expected slots from the API rather than naming one. Hardcoding a slot
// name meant this test broke the moment a schema's slots were corrected by
// measurement, which is exactly the sort of coupling that makes a test get
// deleted instead of fixed.
const catalog = await (await fetch(BASE + '/api/schemas')).json();
const pick = catalog.schemas.find((s) => s.entities.length > 0);
ok(!!pick, 'the catalog offers a schema with slots to track',
   pick ? `${pick.name}: ${pick.entities.join(', ')}` : 'none');
await page.selectOption('#schem', pick.name);
await page.waitForTimeout(300);
const noteAfter = (await page.textContent('#schema-note')).trim();
ok(/Schema:/.test(noteAfter) && noteAfter.includes(pick.name), 'note switches to the chosen schema');
ok(
  pick.entities.some((slot) => noteAfter.includes(slot)),
  'note lists the slots it tracks',
  `expected one of ${pick.entities.join(', ')}`
);
await page.click('#go');
await page.waitForFunction(() => /Gate 2/.test(document.getElementById('result').textContent), null, { timeout: 15000 });
const withSchema = await page.textContent('#result');
ok(/Gate 2/.test(withSchema), 'state table now shows a tracked value');
ok(!/No state tracked/i.test(withSchema), 'empty-state message is gone');

console.log('\n5b. an unmeasured schema says so, in the picker');
// `devtools` shipped describing itself as the schema the benchmarks run on,
// having matched nothing in any of the three corpora. The API now carries the
// evidence and the picker must surface it, or a caller adopts untested patterns
// believing they were derived.
{
  const unmeasured = catalog.schemas.find((s) => s.measured === false);
  ok(!!unmeasured, 'the catalog marks at least one schema as unmeasured',
     unmeasured ? unmeasured.name : 'none');
  if (unmeasured) {
    await page.selectOption('#schem', unmeasured.name);
    await page.waitForTimeout(300);
    const txt = await page.textContent('#schema-note');
    ok(/not measured/i.test(txt), `selecting ${unmeasured.name} says it is unmeasured`);
    await page.selectOption('#schem', pick.name);
    await page.waitForTimeout(300);
    const measuredTxt = await page.textContent('#schema-note');
    ok(!/not measured/i.test(measuredTxt),
       'and a measured schema is not tarred with it');
  }
}

console.log('\n6. declared/inferred provenance tags appear');
ok(/declared|inferred/.test(withSchema), 'per-fact provenance tag rendered');

console.log('\n7. unknown schema is a visible 404, not a silent empty state');
// In its own page, on purpose. This step makes the server return 404, and the
// browser logs that as a console error -- which used to leak into the "no page
// errors" assertion below. Filtering the console by message text was fragile
// enough that it passed locally and failed against the live deployment, where
// the message is worded differently. A deliberate failure should not be
// something other assertions have to filter around.
{
  const probe = await browser.newPage();
  // Navigate first: a fetch from about:blank is cross-origin from a null origin,
  // which the CORS policy correctly refuses.
  await probe.goto(BASE + '/api/health', { waitUntil: 'domcontentloaded' });
  const bad = await probe.evaluate(async (base) => {
    const r = await fetch(base + '/api/compile', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ transcript: 'user: hi', entity_schema: 'nope' })
    });
    return { status: r.status, body: (await r.json()).detail || '' };
  }, BASE);
  ok(bad.status === 404, 'unknown schema -> 404', `status=${bad.status}`);
  ok(/unknown schema/i.test(bad.body), 'error names the problem', bad.body.slice(0, 60));
  await probe.close();
}

console.log('\n8. mode toggle + write-path toggle');
await page.click('#m-cache');
ok(await page.getAttribute('#m-cache', 'aria-pressed') === 'true', 'cache_friendly toggles on');
await page.click('#m-compact');
await page.check('#teach');
ok(await page.isVisible('#teach-row'), 'teaching the protocol reveals its explanation');
const proto = await page.evaluate(async (base) => {
  const r = await fetch(base + '/api/protocol-instruction', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ transcript: 'user: deliver to Tower B' })
  });
  return (await r.json()).instruction || '';
}, BASE);
ok(/contextgc-state/.test(proto), 'protocol instruction endpoint returns real text');

console.log('\n9. "load an example" picks a matching schema');
await page.selectOption('#schem', '');
await page.click('text=example: read path');
// Wait for the compile to land rather than sleeping. A fixed wait passed
// locally against localhost and failed intermittently against the deployed
// site, where the round trip is a network call and 1.2s is a guess.
await page.waitForFunction(
  (previous) => {
    const box = document.getElementById('result');
    return box && !box.hidden && box.textContent !== previous;
  },
  await page.textContent('#result').catch(() => ''),
  { timeout: 20000 }
);
await page.waitForFunction(
  () => /current_file = "|cabin_class = "|destination_address = "|active_reservation = "/
    .test(document.getElementById('result').textContent),
  null,
  { timeout: 20000 }
).catch(() => {});
const afterExample = await page.$eval('#schem', el => el.value);
ok(afterExample !== '', 'example auto-selected a schema', `chose "${afterExample}"`);
const exText = await page.textContent('#result');
ok(/ACTIVE_AGENT_STATE/.test(exText), 'example produced a state register');
ok(
  /current_file = "|cabin_class = "|destination_address = "|active_reservation = "/
    .test(exText),
  'example actually tracked a value',
  exText.slice(0, 120).replace(/\s+/g, ' ')
);
ok(!/No state tracked/.test(exText), 'example did not fall through to an empty state');

// Two defects a screenshot of the empty console could not show, both of which
// shipped: an author `display` on .empty beat the UA stylesheet's [hidden] rule,
// so "Paste a transcript" stayed on screen above a full result; and the stat read
// `authority_ratio`, a telemetry field that does not exist -- the engine
// deliberately calls it `declared_share` -- so the cell rendered "NaN%".
const live = await page.evaluate(() => ({
  emptyHidden: document.getElementById('empty').hidden,
  text: document.getElementById('result').textContent,
}));
ok(live.emptyHidden, 'the empty state is gone once a result is rendered');
ok(!/NaN|undefined/.test(live.text), 'no NaN or undefined leaked into a stat',
   (live.text.match(/\S*(NaN|undefined)\S*/) || [''])[0]);

console.log('\n10. responsive: no horizontal overflow at any phone width');
// Checked in the state the previous steps leave the page in, not on a fresh
// load: a fresh load fit fine locally while the post-interaction state overflowed
// by 5px in CI. A responsive check that only ever sees one state is decoration.
await page.setViewportSize({ width: 375, height: 900 });
await page.waitForTimeout(300);
const measure = () => page.evaluate(() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > vw + 0.5 || r.left < -0.5)) {
      bad.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}` +
        `${el.className ? '.' + String(el.className).split(' ')[0] : ''} ` +
        `[${Math.round(r.left)}..${Math.round(r.right)}]`);
    }
  }
  return { over: document.documentElement.scrollWidth - vw, bad: bad.slice(0, 6) };
});
const widths = [320, 360, 375, 414, 768];
const overflowing = [];
for (const w of widths) {
  await page.setViewportSize({ width: w, height: 900 });
  await page.waitForTimeout(250);
  const r = await measure();
  if (r.over > 1) overflowing.push(`${w}px:+${r.over}px ${r.bad.join(' ')}`);
}
ok(overflowing.length === 0, 'no horizontal overflow at 320/360/375/414/768px',
   overflowing.join(' | ') || 'all clean');
await page.setViewportSize({ width: 375, height: 900 });

console.log('\n11. no console errors / failed requests');
ok(errors.length === 0, 'no page errors', errors.slice(0,2).join(' | '));
ok(failedReqs.length === 0, 'no failed requests', failedReqs.slice(0,2).join(' | '));

await page.screenshot({ path: '/tmp/opencode/site.png', fullPage: true });
console.log('\nscreenshot -> /tmp/opencode/site.png');
await browser.close();
if (server) server.proc.kill();
console.log(fails.length ? `\n${fails.length} FAILURE(S): ${fails.join('; ')}` : '\nALL UI CHECKS PASSED');
process.exit(fails.length ? 1 : 0);
}

main().catch((err) => {
  console.error('\nFAIL  the run did not finish: ' + (err && err.message ? err.message : err));
  console.error('      a timeout here usually means the page stopped initialising,');
  console.error('      not that one assertion was merely false.');
  process.exit(1);
});
