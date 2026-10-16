// Run with PLAYWRIGHT_MODULE and CHROME_BIN pointing to local development tools.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const root = path.resolve(__dirname, '../..');
  const output = process.env.VISUAL_OUTPUT || path.join(root, 'professional/test-results/visual');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ['--no-sandbox']});
  const reports = [];
  try {
    for (const width of [360, 768, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 1100}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto('file://' + path.join(root, 'professional/preview.html'));
      await page.waitForLoadState('load');
      const size = await page.evaluate(() => ({viewport: innerWidth, document: document.documentElement.scrollWidth}));
      assert.ok(size.document <= size.viewport + 1, `Horizontal overflow at ${width}`);
      assert.equal(await page.locator('h1').textContent(), 'Visão geral');
      await page.locator('#pro-search').fill('banco');
      assert.equal(await page.locator('.pro-tool:visible').count(), 1);
      await page.locator('#pro-search').fill('não existe esta ferramenta');
      assert.equal(await page.locator('#pro-empty').isVisible(), true);
      await page.locator('#pro-search').fill('');
      assert.equal(await page.locator('.pro-tool:visible').count(), 6);
      assert.equal(await page.locator('a[href="/list/user/"]').isVisible(), true);
      assert.deepEqual(errors, []);
      await page.screenshot({path: path.join(output, `dashboard-${width}.png`), fullPage: true});
      reports.push({viewport: width, horizontal_overflow: false, search: 'passed', empty_state: 'passed', js_errors: 0});
      await page.close();
    }
  } finally { await browser.close(); }
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(reports, null, 2));
  console.log(JSON.stringify({status: 'passed', viewports: reports.length, reports}, null, 2));
})().catch(error => { console.error(error); process.exit(1); });
