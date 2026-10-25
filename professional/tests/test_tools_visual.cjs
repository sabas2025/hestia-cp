// Real PHP views and JavaScript, with explicit mocked HTTP/service responses.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
  const root=path.resolve(__dirname,'../..'),out=process.env.VISUAL_OUTPUT||path.join(root,'professional/test-results/visual');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN,args:['--no-sandbox']});const results=[];
  try {for(const width of [360,768,1440])for(const tool of ['editor','platform']){
    const page=await browser.newPage({viewport:{width,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));let saves=0,requests=0;
    await page.route('https://hestia.test/**',async route=>{
      const req=route.request();if(req.method()==='GET'){await route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,`professional/${tool}-preview.html`),'utf8')});return;}
      const fields=new URLSearchParams(req.postData());assert.equal(fields.get('token'),'PREVIEW_ONLY');const op=fields.get('op'),input=JSON.parse(fields.get('request'));let data;
      if(op==='domains')data={domains:['example.com']};
      else if(op==='read')data={path:'index.txt',content:'<script>visible source only</script>',sha256:'a'.repeat(64),bytes:42};
      else if(op==='save'){assert.equal(input.sha256,'a'.repeat(64));assert.equal(input.password,'synthetic-password');assert.equal(input.code,'123456');saves++;data={state:'saved',revision:'b'.repeat(32),sha256:'c'.repeat(64)};}
      else if(op==='plan')data={id:'d'.repeat(32),action:input.action,owner:input.owner,notes:['Acompanhe a tarefa.'],reversible:false};
      else if(op==='apply'){assert.equal(input.password,'synthetic-password');assert.equal(input.code,'123456');requests++;data={state:'queued',id:input.id};}
      else if(op==='jobs')data={jobs:[{state:'succeeded',id:'e'.repeat(32)}]};
      else data={available:true};
      await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(`https://hestia.test/professional/${tool}.php`);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${tool} overflow at ${width}`);
    if(tool==='editor'){
      await page.locator('#editor-domains').click();await page.waitForFunction(()=>document.querySelector('#editor-domain').options.length===1);
      await page.locator('#editor-path').fill('index.txt');await page.locator('#editor-open').click();await page.waitForFunction(()=>!document.querySelector('#editor-content').disabled);
      assert.equal(await page.locator('#editor-content').inputValue(),'<script>visible source only</script>');
      await page.locator('#editor-content').fill('changed source');await page.locator('#editor-password').fill('synthetic-password');await page.locator('#editor-code').fill('123456');
      await page.locator('#editor-save button').click();await page.waitForFunction(()=>document.querySelector('#editor-status').textContent.includes('Arquivo salvo'));
      assert.equal(saves,1);assert.equal(await page.locator('#editor-password').inputValue(),'');assert.equal(await page.locator('#editor-code').inputValue(),'');
    }else{
      await page.locator('#platform-action').selectOption('docker-operation');assert.equal(await page.locator('#platform-protection').isVisible(),false);
      await page.locator('#docker-target').fill('app-one');await page.locator('#platform-plan button[type=submit]').click();await page.waitForFunction(()=>!document.querySelector('#platform-confirm').hidden);
      await page.locator('#platform-password').fill('synthetic-password');await page.locator('#platform-code').fill('123456');await page.locator('#platform-confirm button').click();
      await page.waitForFunction(()=>document.querySelector('#platform-status').textContent.includes('enfileirada'));assert.equal(requests,1);
      assert.equal(await page.locator('#platform-password').inputValue(),'');assert.equal(await page.locator('#platform-code').inputValue(),'');
      await page.getByRole('button',{name:'Atualizar tarefas'}).click();await page.waitForFunction(()=>document.querySelector('#platform-jobs').textContent.includes('succeeded'));
    }
    await page.screenshot({path:path.join(out,`${tool}-${width}.png`),fullPage:true});assert.deepEqual(errors,[]);results.push({tool,width,overflow:false,service:'mocked',js_errors:0});await page.close();
  }}finally{await browser.close();}
  console.log(JSON.stringify({status:'passed',results,native_services:'mocked'}));
})().catch(error=>{console.error(error);process.exit(1);});
