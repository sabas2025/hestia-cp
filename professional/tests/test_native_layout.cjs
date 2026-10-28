// Real PHP views/native styles under each controller's strict CSP; synthetic account only.
const fs = require('fs'), path = require('path'), assert = require('assert/strict');
const {execFileSync} = require('child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const root = path.resolve(__dirname, '../..');
  const php = process.env.PHP_BINARY || 'php';
  const output = process.env.VISUAL_OUTPUT || path.join(root, '.qa/native-layout');
  fs.mkdirSync(output, {recursive: true});
  const fixtures = {
    '/professional/': ['render_preview.php', [], 'overview'],
    '/professional/business.php': ['render_business_preview.php', [], 'business'],
    '/professional/editor.php': ['render_tools_preview.php', ['editor'], 'editor'],
    '/professional/platform.php': ['render_tools_preview.php', ['platform'], 'platform'],
    '/professional/twofactor.php': ['render_twofactor_preview.php', [], 'twofactor'],
  };
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_BIN, args: ['--no-sandbox']});
  let pages = 0;
  try {
    for (const theme of ['default', 'dark', 'professional']) for (const width of [360, 768, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 1000}});
      const errors = []; page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.route('https://hestia.test/**', async route => {
        const pathname = new URL(route.request().url()).pathname;
        if (route.request().method() !== 'GET') throw new Error('Read-only layout check attempted a write');
        if (fixtures[pathname]) {
          const [fixture, args] = fixtures[pathname];
          const html = execFileSync(php, ['-n', path.join(__dirname, fixture), ...args], {encoding: 'utf8', env: {...process.env, PREVIEW_THEME: theme}});
          const script = pathname.endsWith('twofactor.php') ? "'none'" : "'self'";
          await route.fulfill({contentType: 'text/html', body: html, headers: {
            'Content-Security-Policy': `default-src 'self'; script-src ${script}; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`,
            'Referrer-Policy': 'same-origin', 'Cache-Control': 'no-store, private',
          }});
          return;
        }
        const asset = path.resolve(root, 'web', '.' + pathname);
        assert.ok(asset.startsWith(path.join(root, 'web') + path.sep));
        assert.ok(fs.existsSync(asset), `Missing asset: ${pathname}`);
        const extension = path.extname(asset);
        const mime = {'.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.png': 'image/png'};
        await route.fulfill({contentType: mime[extension] || 'application/octet-stream', body: fs.readFileSync(asset)});
      });
      for (const [url, [, , section]] of Object.entries(fixtures)) {
        await page.goto('https://hestia.test' + url);
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.locator('main').count(), 1);
        assert.equal(await page.locator('h1').count(), 1);
        assert.equal(await page.locator('.app-header').count(), 1);
        assert.equal(await page.locator('.pro-sidebar').count(), 0);
        assert.equal(await page.locator('.pro-page-nav [aria-current="page"]').count(), 1);
        const layout = await page.evaluate(() => ({
          width: document.documentElement.scrollWidth, viewport: innerWidth,
          bar: getComputedStyle(document.querySelector('.top-bar')).position,
          card: getComputedStyle(document.querySelector('.pro-card')).backgroundColor,
        }));
        assert.ok(layout.width <= layout.viewport + 1, `Overflow: ${theme}/${width}/${section}`);
        assert.equal(layout.bar, 'fixed');
        if (theme === 'dark') assert.equal(layout.card, 'rgb(40, 40, 40)');
        if (section === 'twofactor') assert.equal(await page.locator('script').count(), 0);
        if (section === 'overview') {
          await page.locator('#pro-search').fill('banco');
          assert.equal(await page.locator('.pro-tool:visible').count(), 1);
          await page.locator('#pro-search').fill('');
        }
        if ((theme === 'default' && width === 1440) || (theme === 'dark' && width === 360)) {
          await page.screenshot({path: path.join(output, `${section}-${theme}-${width}.png`), fullPage: true});
        }
        assert.deepEqual(errors, [], `${theme}/${width}/${section}`);
        pages++;
      }
      await page.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({status: 'passed', pages, themes: 3, viewports: 3, csp_violations: 0, horizontal_overflow: false, vps_accessed: false, data: 'synthetic'}));
})().catch(error => { console.error(error); process.exit(1); });
