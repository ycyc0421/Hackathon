/* Independent browser checks using current main and a real isolated backend. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('D:/hackson/tmp/followup-browser-tools/node_modules/playwright');
const [url, repo, out] = process.argv.slice(2);
fs.mkdirSync(out, {recursive:true});
const checks=[], requests=[], responses=[], pageErrors=[], pending=[], cases=[];
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const save=(name,obj)=>fs.writeFileSync(path.join(out,name),JSON.stringify(obj,null,2)+'\n');
const check=(test,name,passed,actual=null)=>checks.push({test,name,passed:!!passed,actual});
async function main(){
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},acceptDownloads:true});
 const page=await context.newPage();let current='startup';
 page.on('pageerror',e=>pageErrors.push({test:current,message:e.message}));
 page.on('request',r=>{
  if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/v1/checks'){
   const bytes=r.postDataBuffer(), name=current+'-request.multipart';
   if(bytes)fs.writeFileSync(path.join(out,name),bytes);
   requests.push({test:current,url:r.url(),method:r.method(),headers:r.headers(),body_file:bytes?name:null,
                 body_capture:bytes?'browser':'Chromium omitted multipart file body; see server audit'});
  }
 });
 page.on('response',r=>{
  if(/\/api\/v1\/checks(?:\/|$)/.test(new URL(r.url()).pathname)){
   const tag=current;
   pending.push((async()=>{try{responses.push({test:tag,url:r.url(),method:r.request().method(),http_status:r.status(),body:await r.json()});}catch(e){responses.push({test:tag,url:r.url(),read_error:e.message});}})());
  }
 });
 async function fresh(test){current=test;await page.goto(url+'/?mock=0',{waitUntil:'networkidle'});await page.locator('input[type=file]').waitFor({state:'attached'});}
 const fixture=path.join(repo,'docs/fixtures/edi/multi-item.edi');const source=fs.readFileSync(fixture);
 const invoice=fs.readFileSync(path.join(repo,'docs/fixtures/edi/invoice.edi'));
 try {
  current='preflight';await fresh(current);
  check(current,'real backend mode',await page.getByText('真实后端',{exact:true}).count()>0);
  const accept=await page.locator('input[type=file]').getAttribute('accept');
  check(current,'EDI allowed and TXT excluded',accept.includes('.edi')&&!accept.includes('.txt'),accept);

  await fresh('source-preview');
  await page.locator('input[type=file]').setInputFiles({name:'MULTI.EDI',mimeType:'application/octet-stream',buffer:source});
  const sourceBlock=page.locator('.file-item .edi-source').first();
  await sourceBlock.getByRole('button',{name:'查看原文',exact:true}).click();
  await sourceBlock.locator('pre').waitFor();
  const preview=await sourceBlock.locator('pre').textContent();
  check(current,'exact text preview preserves separators/escaping/newlines',preview===source.toString('utf8'));
  check(current,'HTML-looking text creates no script or b nodes',await sourceBlock.locator('pre script,pre b').count()===0);
  const widths=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  check(current,'390px viewport has no horizontal overflow',widths.document<=widths.viewport&&widths.body<=widths.viewport,widths);
  const [download]=await Promise.all([page.waitForEvent('download'),sourceBlock.getByRole('button',{name:'下载原件',exact:true}).click()]);
  await download.saveAs(path.join(out,'MULTI.EDI.download'));
  check(current,'download byte identity',fs.readFileSync(path.join(out,'MULTI.EDI.download')).equals(source));
  await page.screenshot({path:path.join(out,'source-preview-390.png'),fullPage:true});

  await fresh('txt-rejected');
  await page.locator('input[type=file]').setInputFiles({name:'INVOICE.txt',mimeType:'text/plain',buffer:invoice});
  await page.waitForTimeout(300);
  const txtText=await page.locator('.page').innerText();
  check(current,'TXT has explicit rejection',/不支持/.test(txtText)&&/INVOICE\.txt/.test(txtText),txtText);
  check(current,'rejected TXT cannot submit',await page.getByRole('button',{name:'开始检查',exact:true}).isDisabled());

  await fresh('bad-utf8-preview');
  const bad=Buffer.from([0xc3,0x28]);
  await page.locator('input[type=file]').setInputFiles({name:'SYNTHETIC-BAD-UTF8.edi',mimeType:'application/octet-stream',buffer:bad});
  const badBlock=page.locator('.file-item .edi-source').first();
  await badBlock.getByRole('button',{name:'查看原文',exact:true}).click();
  await badBlock.locator('.edi-source-error').waitFor();
  check(current,'bad UTF-8 produces explicit preview error',/无法预览/.test(await badBlock.innerText()));
  const [badDownload]=await Promise.all([page.waitForEvent('download'),badBlock.getByRole('button',{name:'下载原件',exact:true}).click()]);
  await badDownload.saveAs(path.join(out,'SYNTHETIC-BAD-UTF8.edi.download'));
  check(current,'bad UTF-8 download preserves original bytes',fs.readFileSync(path.join(out,'SYNTHETIC-BAD-UTF8.edi.download')).equals(bad));
  await page.screenshot({path:path.join(out,'bad-utf8-preview.png'),fullPage:true});

  async function uploadCase(test,files,expectedStatus){
   await fresh(test);
   await page.locator('input[type=file]').setInputFiles(files);
   await page.getByRole('button',{name:'开始检查',exact:true}).click();
   let final=null;
   const deadline=Date.now()+90000;
   while(Date.now()<deadline){
    await page.waitForTimeout(150);
    final=responses.filter(x=>x.test===test&&x.method==='GET'&&x.body?.task_id&&['COMPLETED','PARTIAL','FAILED'].includes(x.body.status)).at(-1);
    if(final)break;
   }
   if(!final)throw new Error(test+' no terminal GET response');
   const task=final.body;
   await page.waitForTimeout(400);
   const text=await page.locator('.page').innerText();save(test+'-page-text.json',{text});
   check(test,'real terminal task status',task.status===expectedStatus,task.status);
   check(test,'explicit unsupported file state',task.documents.some(d=>d.file_name==='INVOICE.EDI'&&d.process_status==='UNSUPPORTED'),task.documents);
   check(test,'uppercase filename retained',task.documents.some(d=>d.file_name==='INVOICE.EDI'));
   check(test,'EDI declared dependency and failure visible',text.includes('不支持')&&(/失败|未能处理/.test(text)),text);
   check(test,'no false global approval',!/(?:已通过校验|校验通过|本票已合规)/.test(text));
   check(test,'source actions retained after terminal failure',await page.locator('.edi-source').getByRole('button',{name:'下载原件',exact:true}).count()>0);
   const terminalSource=page.locator('.edi-source').last();
   const [terminalDownload]=await Promise.all([page.waitForEvent('download'),terminalSource.getByRole('button',{name:'下载原件',exact:true}).click()]);
   await terminalDownload.saveAs(path.join(out,test+'.EDI.download'));
   check(test,'terminal file-status source download retains bytes',fs.readFileSync(path.join(out,test+'.EDI.download')).equals(invoice));
   await page.screenshot({path:path.join(out,test+'-upload.png'),fullPage:true});
   cases.push({test,task_id:task.task_id,status:task.status,documents:task.documents,summary:task.summary});
   return task;
  }
  const ediInput={name:'INVOICE.EDI',mimeType:'application/octet-stream',buffer:invoice};
  await uploadCase('edi-only',ediInput,'FAILED');
  await page.getByRole('button',{name:'差异',exact:true}).click();
  await page.getByRole('heading',{name:'差异比对',exact:true}).waitFor();
  check('edi-only','diff page displays failure',/检查失败/.test(await page.locator('.page').innerText()));
  await page.screenshot({path:path.join(out,'edi-only-diff.png'),fullPage:true});
  await page.getByRole('button',{name:'报告',exact:true}).click();
  await page.waitForTimeout(450);
  const reportText=await page.locator('.page').innerText();save('edi-only-report-text.json',{text:reportText});
  check('edi-only','report preserves failure',/失败/.test(reportText),reportText);
  await page.screenshot({path:path.join(out,'edi-only-report.png'),fullPage:true});

  const pdf=path.join(repo,'docs/fixtures/edi/synthetic-packing-list.pdf');
  const mixed=await uploadCase('mixed-pdf-edi',[ediInput,{name:path.basename(pdf),mimeType:'application/pdf',buffer:fs.readFileSync(pdf)}],'PARTIAL');
  check('mixed-pdf-edi','text PDF actually extracted',mixed.documents.some(d=>d.file_name==='synthetic-packing-list.pdf'&&d.process_status==='EXTRACTED'),mixed.documents);
  check('mixed-pdf-edi','partial warning visible',/未包含全部文件/.test(await page.locator('.page').innerText()));
  const refreshBefore=await page.locator('.edi-source').count();
  await page.reload({waitUntil:'networkidle'});
  check('refresh','no fake source reconstructed after refresh',refreshBefore>0&&await page.locator('.edi-source').count()===0);
  check('refresh','no page crash',pageErrors.length===0,pageErrors);
 } finally {
  await Promise.allSettled(pending);
  save('checks.json',checks);save('requests.json',requests);save('responses.json',responses);save('cases.json',cases);save('page-errors.json',pageErrors);
  save('summary.json',{frontend_and_backend_commit:'d223d7cfe94acccc60b96656f2f93f866b63e087',evidence:'real Chromium browser -> Vite proxy -> isolated current-main FastAPI; no response mocking',
   checks:checks.length,failed:checks.filter(x=>!x.passed),cases,page_errors:pageErrors,
   limits:['EDI successful parsing not supported/tested','no OCR invoked','not production UI acceptance','one synthetic UTF-8 negative input','refresh resets in-memory task/File; candidate source-download API not integrated']});
  console.log(JSON.stringify({checks:checks.length,failed:checks.filter(x=>!x.passed),http_tasks:cases.length,page_errors:pageErrors.length}));
  await browser.close();
 }
 if(checks.some(x=>!x.passed))process.exitCode=1;
}
main().catch(e=>{save('execution-error.json',{message:e.message,stack:e.stack});console.error(e);process.exitCode=1;});
