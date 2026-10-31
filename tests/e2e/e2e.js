// Browser end-to-end check. Usage: node e2e.js http://127.0.0.1:PORT/   (needs the `playwright` package)
const { chromium } = require('playwright');
const U = process.argv[2];
const must = (c, m) => { if (!c) throw new Error('FAILED: ' + m); };
const api = (path, body) => fetch(U + 'api/' + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Assembly-Site': '1' }, body: JSON.stringify(body) } : {}).then((r) => r.json());
const mk = (f) => api('captures', { kind: 'question', apply: true, fields: Object.assign({ lens: 'law', trust: 'owner', sensitivity: 'private', intake: 'scan', region: 'Niagara', cadence: 'daily', origin: 'internal' }, f) });

(async () => {
  await mk({ text: 'What zoning applies to 676 King St W?' });
  await mk({ text: 'Which councils changed short-term rental bylaws this week?' });
  await mk({ text: 'File the 2025 assessment roll for Fort Erie', intake: 'file', region: 'Erie', cadence: 'once' });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 900 } });
  const errs = [];
  p.on('pageerror', (e) => errs.push(e.message));
  p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text()); });

  // map: every stage, deep link to a substage, unbuilt stages offer no actions
  await p.goto(U + '#/'); await p.waitForSelector('.scard');
  must((await p.locator('.scard').count()) === 14, '14 stage cards');
  await p.click('.scard.dispatch .chip.link:has-text("Digest")'); await p.waitForSelector('#sub-digest.here');
  must((await p.locator('#sub-assess .actions a').count()) === 0, 'unbuilt substage has no action links');

  // notes: comment with markup stays literal, star, flag, resolve
  await p.goto(U + '#/r/Q-0001'); await p.waitForSelector('textarea[placeholder="Add a comment"]');
  await p.fill('textarea[placeholder="Add a comment"]', 'check <b>parcel</b> @ann'); await p.click('button:has-text("Post")');
  await p.waitForSelector('.cm .txt');
  must((await p.textContent('.cm .txt')).includes('<b>parcel</b>'), 'comment markup rendered as text');
  await p.click('button:has-text("Star")'); await p.waitForSelector('text=Starred');
  await p.click('button:has-text("Resolve thread")'); await p.waitForSelector('details.resolved');

  // bundles: ready / manual; hold; preview with confirm; write
  await p.goto(U + '#/bundles'); await p.waitForSelector('.bundle');
  must((await p.locator('.bundle').count()) === 2, 'two bundles');
  must((await p.locator('.pill.rd-manual').count()) === 1, 'filing question is manual');
  const niagara = p.locator('.bundle').filter({ hasText: 'Niagara' });
  await niagara.locator('button:has-text("Preview dispatch")').click(); await p.waitForSelector('text=Dispatch preview');
  must((await p.locator('button:has-text("Write 2 task documents")').isDisabled()), 'write is disabled until confirmed');
  await p.check('.card.inner input[type=checkbox]'); await p.click('button:has-text("Write 2 task documents")');
  await p.waitForSelector('text=Dispatch result');
  must((await p.locator('.pill.answered').count()) === 2, 'two task documents written');

  // workbench reflects it; inbox page loads; records search and CSV link
  await p.goto(U + '#/dispatch'); await p.waitForSelector('.nextup .next');
  await p.goto(U + '#/inbox'); await p.waitForSelector('h1');
  await p.goto(U + '#/records?q=zoning'); await p.waitForSelector('.row');
  must((await p.locator('.row').count()) === 1, 'search finds one record');
  must((await p.locator('a:has-text("Export CSV")').getAttribute('href')).includes('q=zoning'), 'CSV export keeps the search');

  // keyboard: g then b opens bundles
  await p.goto(U + '#/'); await p.waitForSelector('.scard'); await p.keyboard.press('g'); await p.keyboard.press('b'); await p.waitForSelector('.bundle');

  // phone layout: bundle table becomes cards
  await p.setViewportSize({ width: 390, height: 800 }); await p.reload(); await p.waitForSelector('.bundle');
  must((await p.locator('.bundle table thead').first().isHidden()), 'table header hidden on phone');
  must((await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)), 'no horizontal scroll on phone');

  must(errs.length === 0, 'no console errors: ' + JSON.stringify(errs));
  await b.close();
  console.log('e2e ok');
})().catch((e) => { console.error(e.message); process.exit(1); });
