/* Browser interaction only, with explicitly synthetic native-main wire files.
 * Usage: node this-file.mjs SUCCESS_WIRE CANCEL_WIRE OUTPUT_DIR
 * Requires Playwright; PLAYWRIGHT_MODULE may point to an installed package. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const {chromium} = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [successPath,cancelPath,outputDir] = process.argv.slice(2);
if (!outputDir) throw new Error('success wire, cancel wire and output directory required');
const staticDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../static');
const success = fs.readFileSync(successPath,'utf8').replace(/^[\s\S]*?(?=T25 REQUEST 1 )/,'');
const cancel = fs.readFileSync(cancelPath,'utf8').replace(/^[\s\S]*?(?=T25 REQUEST 1 )/,'');
const cut = cancel.indexOf('T25 CONTROL 1 ');
assert.ok(cut > 0);
const caps = 'T25 CAPABILITIES stream=1 text_max=1 cancel=1 prefix=1 profile=1 timeout=1 identity=1\n';
const session = /session=([0-9a-f]{16})/.exec(cancel)[1];
fs.mkdirSync(outputDir,{recursive:true});
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({viewport:{width:1600,height:1000},acceptDownloads:true,reducedMotion:'reduce'});
const errors = [];let assertions = 0;
const check = (value,message) => {assert.ok(value,message);assertions++;};
await context.route('http://localhost:8765/**',async route=>{
  const url = new URL(route.request().url());
  if (url.pathname==='/api/bootstrap') return route.fulfill({contentType:'application/json',body:'{"token":"synthetic-browser-test"}'});
  const relative = url.pathname==='/'?'index.html':url.pathname.slice(1);
  const file = path.resolve(staticDir,relative);
  if (!file.startsWith(staticDir+path.sep) || !fs.existsSync(file)) return route.fulfill({status:404,body:'not found'});
  const types = {'.html':'text/html','.js':'application/javascript','.json':'application/json','.css':'text/css','.svg':'image/svg+xml'};
  await route.fulfill({contentType:types[path.extname(file)] || 'application/octet-stream',body:fs.readFileSync(file)});
});
await context.addInitScript(({success,cancelStart,cancelEnd,caps})=>{
  window.syntheticUART={writes:[],requests:0,signals:null};
  Object.defineProperty(navigator,'serial',{value:{requestPort:async()=>{
    let receive;
    return {getInfo:()=>({usbVendorId:0x10c4,usbProductId:0xea60}),open:async()=>{},
      setSignals:async signals=>{window.syntheticUART.signals=signals},close:async()=>{},
      readable:new ReadableStream({start(controller){receive=controller},cancel(){}}),
      writable:new WritableStream({write(bytes){
        const command=new TextDecoder().decode(bytes).trimEnd();window.syntheticUART.writes.push(command);
        let raw;
        if (!command) raw=caps+'T25 READY\n';
        else if (command.startsWith(':timeout ')) raw='T25 CONFIG 1 timeout_ticks='+(BigInt(command.slice(9))*125000000n).toString(16).padStart(16,'0')+' \n'+caps+'T25 READY\n';
        else if (command.startsWith(':prefix ')) raw='T25 CONFIG 1 prefix=000000000000000'+command.at(-1)+' \n'+caps+'T25 READY\n';
        else if (command.startsWith(':cancel ')) raw=cancelEnd;
        else raw=++window.syntheticUART.requests===1?success:cancelStart;
        setTimeout(()=>receive.enqueue(new TextEncoder().encode(raw)),25);
      }})};
  }}});
},{success,cancelStart:cancel.slice(0,cut),cancelEnd:cancel.slice(cut),caps});
const page = await context.newPage();page.on('pageerror',error=>errors.push(error.message));
try {
  await page.goto('http://localhost:8765/');
  await page.locator('#run-button').click();await page.locator('#connect-confirm').click();
  await page.waitForFunction(()=>document.getElementById('connection-label').textContent==='板端服务就绪');
  check(JSON.stringify(await page.evaluate(()=>window.syntheticUART.signals))===JSON.stringify({dataTerminalReady:false,requestToSend:false}),'connect does not pulse reset');
  await page.locator('#prompt').fill('hello');await page.locator('#max-new').fill('2');
  await page.locator('#run-button').click();
  await page.waitForFunction(()=>document.getElementById('result-state').textContent==='板端请求完成');
  await page.locator('[data-view="performance"]').click();
  check(await page.locator('.profile-row').count()===8,'request profile displayed');
  check((await page.locator('#profile-caption').innerText()).includes('本次请求'),'request phase label');
  await page.locator('#profile-phase').selectOption('PREFILL');
  check((await page.locator('#profile-caption').innerText()).includes('本次输入处理'),'prefill phase label');
  await page.locator('#profile-phase').selectOption('CUMULATIVE');
  check((await page.locator('#profile-caption').innerText()).includes('启动以来'),'cumulative phase label');
  check((await page.locator('#performance-stats').innerText()).includes('当前位流未提供'),'old bitstream PMU is not shown as zero measurements');
  await page.screenshot({path:path.join(outputDir,'performance-1600.png'),fullPage:true});
  await page.locator('[data-view="demo"]').click();
  const downloaded=page.waitForEvent('download');await page.locator('#export-button').click();
  const download=await downloaded;const exportPath=path.join(outputDir,'SYNTHETIC_BROWSER_EXPORT.json');await download.saveAs(exportPath);
  const exported=JSON.parse(fs.readFileSync(exportPath,'utf8'));
  check(exported.complete && exported.profiles.REQUEST.length===8 && exported.prefix.captured===1,'manual export carries enhanced metadata');
  // It is a UI test artifact, not a live board measurement. Keep this explicit
  // even though the live UI itself naturally labels its transport as live.
  exported.source='fixture';exported.fixture=true;exported.fixture_note='Playwright fake USB serial with synthetic native-main model data';
  fs.writeFileSync(exportPath,JSON.stringify(exported,null,2)+'\n');
  await page.locator('#timeout-seconds').fill('600');await page.locator('#timeout-apply').click();
  await page.waitForFunction(()=>window.syntheticUART.writes.includes(':timeout 600')&&!document.getElementById('timeout-apply').disabled);
  await page.locator('#prefix-enabled').uncheck();
  await page.waitForFunction(()=>window.syntheticUART.writes.includes(':prefix 0')&&!document.getElementById('prefix-enabled').disabled);
  await page.locator('#run-button').click();
  await page.waitForFunction(()=>!document.getElementById('cancel-button').disabled&&!document.getElementById('cancel-button').hidden);
  check(await page.locator('#run-button').isDisabled(),'second request waits while generating');
  await page.locator('#cancel-button').click();
  check(await page.locator('#cancel-button').isDisabled(),'only one pending cancellation');
  await page.waitForFunction(()=>document.getElementById('connection-label').textContent==='板端服务就绪');
  check((await page.evaluate(()=>window.syntheticUART.writes)).includes(':cancel '+session),'cancel binds the board session');
  check((await page.locator('#result-text').innerText()).includes('ERROR'),'aborted request is not a success');
  for (const width of [1600,390]) {
    await page.setViewportSize({width,height:width===390?844:1000});
    check(await page.evaluate(()=>document.documentElement.scrollWidth)===width,'no horizontal overflow at '+width);
    await page.screenshot({path:path.join(outputDir,`controls-${width}.png`),fullPage:true});
  }
  check(errors.length===0,'no browser script errors: '+errors.join('; '));
  console.log(JSON.stringify({status:'PASS',assertions,scope:'FAKE_USB_UI_AND_SYNTHETIC_NATIVE_MAIN_WIRE_ONLY',board_performance:false},null,2));
} finally {await context.close();await browser.close();}
