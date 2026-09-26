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

/** Start the real server and wait for it to answer. */
async function startServer() {
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
// Step 7 deliberately requests an unknown schema to prove it 404s; the browser
// logs that as a console error, so it must not be counted as an unexpected one.
const EXPECTED_404 = 'unknown schema';
page.on('console', m => {
  if (m.type() !== 'error') return;
  const t = m.text();
  if (/404 \(Not Found\)/.test(t) && m.location()?.url?.includes('/api/compile')) return;
  errors.push(t);
});
page.on('requestfailed', r => { if (!EXPECTED_404) failedReqs.push(r.url()); });
page.on('requestfailed', r => failedReqs.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));

console.log('\n1. page loads');
const resp = await page.goto(BASE, { waitUntil: 'networkidle' });
ok(resp.status() === 200, 'GET / returns 200', `status=${resp.status()}`);
ok((await page.title()).length > 0, 'title set', await page.title());

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
await page.selectOption('#schem', 'logistics');
await page.waitForTimeout(300);
const noteAfter = (await page.textContent('#schema-note')).trim();
ok(/Schema:/.test(noteAfter) && /logistics/.test(noteAfter), 'note switches to the chosen schema');
ok(/destination_address/.test(noteAfter), 'note lists the slots it tracks');
await page.click('#go');
await page.waitForFunction(() => /Gate 2/.test(document.getElementById('result').textContent), null, { timeout: 15000 });
const withSchema = await page.textContent('#result');
ok(/Gate 2/.test(withSchema), 'state table now shows a tracked value');
ok(!/No state tracked/i.test(withSchema), 'empty-state message is gone');

console.log('\n6. declared/inferred provenance tags appear');
ok(/declared|inferred/.test(withSchema), 'per-fact provenance tag rendered');

console.log('\n7. unknown schema is a visible 404, not a silent empty state');
const bad = await page.evaluate(async (base) => {
  const r = await fetch(base + '/api/compile', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ transcript: 'user: hi', entity_schema: 'nope' })
  });
  return { status: r.status, body: (await r.json()).detail || '' };
}, BASE);
ok(bad.status === 404, 'unknown schema -> 404', `status=${bad.status}`);
ok(/unknown schema/i.test(bad.body), 'error names the problem', bad.body.slice(0,60));

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
await page.waitForTimeout(1200);
const afterExample = await page.$eval('#schem', el => el.value);
ok(afterExample !== '', 'example auto-selected a schema', `chose "${afterExample}"`);
const exText = await page.textContent('#result');
ok(/Gate 2|Tower B|destination_address|Reduction/.test(exText), 'example produced a real result');

console.log('\n10. responsive: no horizontal overflow at 375px');
await page.setViewportSize({ width: 375, height: 900 });
await page.waitForTimeout(300);
const overflow = await page.evaluate(() =>
  document.documentElement.scrollWidth - document.documentElement.clientWidth);
ok(overflow <= 1, 'no horizontal overflow at 375px', `overflow=${overflow}px`);

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
