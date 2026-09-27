// Capture the pages in the states a reader actually meets. A screenshot of an
// empty console shows nothing about whether the tool works.
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
const PORT = 8941, BASE = `http://localhost:${PORT}`;
const proc = spawn('python3', ['-m','uvicorn','server.main:app','--port',String(PORT),'--log-level','warning'],
  { cwd: process.cwd(), stdio: 'ignore' });
for (let i=0;i<60;i++){ try { const r = await fetch(BASE+'/console'); if (r.ok) break; } catch {} await sleep(500); }
const b = await chromium.launch();

for (const [name, path, vp] of [
  ['landing-desktop','/',{width:1440,height:1000}],
  ['landing-mobile','/',{width:390,height:1000}],
  ['console-empty','/console',{width:1440,height:1000}],
  ['console-empty-mobile','/console',{width:390,height:1000}],
]) {
  const p = await b.newPage({ viewport: vp });
  await p.goto(BASE+path, { waitUntil:'networkidle' });
  await p.waitForTimeout(400);
  await p.screenshot({ path:`/tmp/opencode/${name}.png`, fullPage: true });
  await p.close();
}

// The working state: an example compiled, with a schema chosen and a real
// register in the output panel.
for (const [name, vp] of [['console-result',{width:1440,height:1000}],
                          ['console-result-mobile',{width:390,height:1000}]]) {
  const p = await b.newPage({ viewport: vp });
  await p.goto(BASE+'/console', { waitUntil:'networkidle' });
  await p.click("text=example: write path");
  await p.waitForFunction(() => /ACTIVE_AGENT_STATE/.test(
    document.getElementById('result')?.textContent || ''), null, { timeout: 20000 });
  await p.waitForTimeout(300);
  await p.screenshot({ path:`/tmp/opencode/${name}.png`, fullPage: true });
  await p.close();
}
// Dark mode is a first-class theme, not an afterthought: the tokens flip and
// the accent inverts, so it gets inspected rather than assumed.
for (const [name, path] of [['landing-dark','/'], ['console-dark','/console']]) {
  const p = await b.newPage({ viewport: {width:1440,height:1000}, colorScheme: 'dark' });
  await p.goto(BASE+path, { waitUntil:'networkidle' });
  if (path === '/console') {
    await p.click('text=example: write path');
    await p.waitForFunction(()=>/ACTIVE_AGENT_STATE/.test(
      document.getElementById('result')?.textContent || ''), null, {timeout:20000});
  }
  await p.waitForTimeout(300);
  await p.screenshot({ path:`/tmp/opencode/${name}.png`, fullPage: true });
  await p.close();
}
await b.close(); proc.kill();
console.log('shots written');
