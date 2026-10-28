// Real PHP-rendered view and browser events; HTTP/native operations are mocked.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const previewAsset = require('./preview-assets.cjs');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const root = path.resolve(__dirname,'../..');
  const output = process.env.VISUAL_OUTPUT || path.join(root,'professional/test-results/visual');
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN,args:['--no-sandbox']});
  const results=[];
  try {
    for (const width of [360,768,1440]) {
      const page = await browser.newPage({viewport:{width,height:1100}}); const errors=[]; page.on('pageerror',error => errors.push(error.message));
      let plan=null; let state='planned';
      await page.route('https://hestia.test/**',async route => {
        if (await previewAsset(route, root)) return;
        const request=route.request();
        if (request.method() === 'GET') { await route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'professional/business-preview.html'),'utf8')}); return; }
        const fields=new URLSearchParams(request.postData()); assert.equal(fields.get('token'),'PREVIEW_ONLY');
        const op=fields.get('op'), input=JSON.parse(fields.get('request')); let data;
        if (op==='plan') { plan={id:'a'.repeat(32),action:input.action,owner:input.owner,params:input.params,state:'planned',notes:['Plano ilustrativo. Os serviços e a fila são simulados neste teste.'],files:[],commands:[]}; data=plan; }
        else if (op==='apply') { assert.equal(input.password,'synthetic-password');assert.equal(input.code,'123456'); state='applied'; data={...plan,state:'queued'}; }
        else if (op==='rollback') { state='rolled-back';data={...plan,state:'queued'}; }
        else if (op==='history') data={plans:plan?[{...plan,state}]:[]};
        else if (op==='diagnose') data={dnssec_chain_validated:false,mail_delivery_tested:false};
        else data={coverage:'incomplete'};
        await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      });
      await page.goto('https://hestia.test/professional/business.php');
      const size=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth}));
      assert.ok(size.width<=size.viewport+1,`Overflow at ${width}`);
      await page.locator('#action').selectOption('resources');assert.equal(await page.locator('#resource-fields').isVisible(),true);assert.equal(await page.locator('#domain-fields').isVisible(),false);
      await page.locator('#action').selectOption('dns-ttl');await page.locator('#owner').fill('clientone');await page.locator('#domain').fill('example.com');await page.locator('#value').fill('600');
      await page.locator('#change-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('#plan-summary').textContent.includes('example.com'));
      assert.equal(await page.locator('#password').getAttribute('type'),'password');
      await page.screenshot({path:path.join(output,`business-${width}.png`),fullPage:true});
      await page.locator('#password').fill('synthetic-password');await page.locator('#code').fill('123456');await page.locator('#confirm').click();
      await page.waitForFunction(()=>document.querySelector('#business-status').textContent.includes('colocada na fila'));
      assert.equal(await page.locator('#password').inputValue(),''); assert.equal(await page.locator('#code').inputValue(),'');
      assert.ok((await page.locator('#history-list').textContent()).includes('Aplicado'));
      await page.getByRole('button',{name:'Revisar reversão'}).click();await page.locator('#password').fill('synthetic-password');await page.locator('#code').fill('654321');await page.locator('#confirm').click();
      await page.waitForFunction(()=>document.querySelector('#history-list').textContent.includes('Revertido'));
      assert.deepEqual(errors,[]);results.push({width,overflow:false,review:'passed',queue:'mocked',rollback:'mocked',js_errors:0});await page.close();
    }
  } finally {await browser.close();}
  fs.writeFileSync(path.join(output,'business-results.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify({status:'passed',results,native_services:'mocked'}));
})().catch(error=>{console.error(error);process.exit(1);});
