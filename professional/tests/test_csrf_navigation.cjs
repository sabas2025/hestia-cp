// Actual PHP response headers and Chromium navigation, without mocked browser routes.
// Authentication is the explicit test-only bootstrap in test_http.py; the CSRF
// probe includes the unchanged native guard at strictness 1 and performs no action.
const assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
  const base=process.argv[2];
  assert.match(base,/^http:\/\/127\.0\.0\.1:\d+$/);
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN,args:['--no-sandbox']});
  const paths=['/professional/','/professional/business.php','/professional/platform.php','/professional/editor.php','/professional/twofactor.php'];
  try {
    const page=await browser.newPage({extraHTTPHeaders:{'X-Test-User':'admin','X-Test-Context':'admin','X-Test-Role':'admin'}});
    for(const path of paths){
      const source=base+path;
      let response=await page.goto(source);
      assert.equal(response.status(),200,`source ${path}`);
      // DOM injection supplies a harmless test link; the page's real response
      // policy determines Referer. No per-link referrer override is used.
      await page.evaluate(()=>{const link=document.createElement('a');link.id='csrf-navigation-test';link.href='/csrf-probe.php';link.textContent='Test navigation';document.body.prepend(link);});
      [response]=await Promise.all([page.waitForResponse(base+'/csrf-probe.php'),page.locator('#csrf-navigation-test').click()]);
      assert.equal(response.status(),200,`same-origin navigation from ${path}`);
      const result=await response.json();assert.equal(result.state,'accepted');assert.equal(result.referer,source);
      await page.goto(source);
      await page.evaluate(()=>{const form=document.createElement('form');form.id='csrf-post-test';form.method='POST';form.action='/csrf-probe.php';const button=document.createElement('button');button.textContent='Test submission';form.append(button);document.body.prepend(form);});
      [response]=await Promise.all([page.waitForResponse(base+'/csrf-probe.php'),page.locator('#csrf-post-test button').click()]);
      assert.equal(response.status(),200,`same-origin form from ${path}`);
      assert.equal((await response.json()).origin,base);
      await page.goto(source);
      const external=base.replace('127.0.0.1','localhost')+'/external-target.php';
      await page.evaluate(url=>{const link=document.createElement('a');link.id='external-navigation-test';link.href=url;link.textContent='External test';document.body.prepend(link);},external);
      [response]=await Promise.all([page.waitForResponse(external),page.locator('#external-navigation-test').click()]);
      assert.equal(response.status(),200);assert.equal((await response.json()).referer,'',`external privacy from ${path}`);
    }
    await page.close();
  }finally{await browser.close();}
  console.log(JSON.stringify({status:'passed',pages:paths.length,native_csrf_policy:1,external_referer:'absent'}));
})().catch(error=>{console.error(error);process.exit(1);});
