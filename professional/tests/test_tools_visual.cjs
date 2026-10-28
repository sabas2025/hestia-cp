// Real PHP views and JavaScript, with explicit mocked HTTP/service responses.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const previewAsset=require('./preview-assets.cjs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
  const root=path.resolve(__dirname,'../..'),out=process.env.VISUAL_OUTPUT||path.join(root,'professional/test-results/visual');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BIN,args:['--no-sandbox']});const results=[];
  try {for(const width of [360,768,1440])for(const tool of ['editor','platform']){
    const page=await browser.newPage({viewport:{width,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));let saves=0,requests=0,renames=0,uploads=0;let listedName='index.txt';let uploaded=[];
    await page.route('https://hestia.test/**',async route=>{
      if(await previewAsset(route,root))return;
      const req=route.request();if(req.method()==='GET'){await route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,`professional/${tool}-preview.html`),'utf8')});return;}
      const fields=new URLSearchParams(req.postData());assert.equal(fields.get('token'),'PREVIEW_ONLY');const op=fields.get('op'),input=JSON.parse(fields.get('request'));let data;
      if(op==='domains')data={domains:['example.com']};
      else if(op==='files')data={path:input.path||'',entries:[{name:'assets',path:'assets',type:'directory',bytes:0,modified:1793000000},{name:listedName,path:listedName,type:'file',bytes:16,modified:1793000000,etag:'f'.repeat(64),editable:true,downloadable:true}],total:2,offset:0,next:null,limit:100};
      else if(op==='download')data={data:Buffer.from('downloaded bytes').toString('base64'),offset:0,total:16,etag:'f'.repeat(64),eof:true};
      else if(op==='rename'){assert.equal(input.etag,'f'.repeat(64));assert.equal(input.password,'synthetic-password');listedName=input.name;renames++;data={state:'renamed'};}
      else if(op==='upload-begin'){assert.equal(input.password,'synthetic-password');assert.equal(input.path,'sample.bin');assert.equal(input.total,300000);uploads++;uploaded=[];data={upload:'e'.repeat(32),chunk_bytes:262144};}
      else if(op==='upload-part'){assert.equal(input.offset,uploaded.reduce((sum,part)=>sum+part.length,0));uploaded.push(Buffer.from(input.data,'base64'));data={received:uploaded.reduce((sum,part)=>sum+part.length,0)};}
      else if(op==='upload-commit'){assert.equal(Buffer.concat(uploaded).length,300000);data={state:'uploaded'};}
      else if(op==='mkdir')data={state:'created'};
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
      const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'Baixar',exact:true}).click()]);
      assert.equal(download.suggestedFilename(),'index.txt');assert.equal(fs.readFileSync(await download.path(),'utf8'),'downloaded bytes');
      await page.getByRole('button',{name:'Renomear',exact:true}).click();
      await page.locator('#fm-name').fill('renamed.txt');await page.locator('#fm-password').fill('synthetic-password');await page.locator('#fm-code').fill('123457');await page.locator('#fm-action button[type=submit]').click();
      await page.waitForFunction(()=>document.querySelector('#editor-status').textContent.includes('Arquivo renomeado'));
      assert.equal(renames,1);assert.equal(await page.locator('#fm-password').inputValue(),'');
      await page.locator('#fm-upload').click();await page.locator('#fm-file').setInputFiles({name:'sample.bin',mimeType:'application/octet-stream',buffer:Buffer.alloc(300000,7)});
      await page.locator('#fm-password').fill('synthetic-password');await page.locator('#fm-code').fill('123458');await page.locator('#fm-action button[type=submit]').click();
      await page.waitForFunction(()=>document.querySelector('#editor-status').textContent.includes('Upload concluído'));
      assert.equal(uploads,1);assert.equal(uploaded.length,2);assert.equal(await page.locator('#fm-code').inputValue(),'');
      await page.locator('#fm-search').fill('not-found');assert.equal(await page.locator('#editor-files').innerText(),'Nenhum item nesta página.');await page.locator('#fm-search').fill('');

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
