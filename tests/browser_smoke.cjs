/* Optional browser regression. npm install --no-save playwright, then node tests/browser_smoke.cjs.
   Can use PLAYWRIGHT_MODULE and BROWSER_EXECUTABLE to reuse an existing installation. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname,'..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(),'campus-browser-'));
const output = path.join(root,'output','qa');fs.mkdirSync(output,{recursive:true});
const child = spawn(process.env.PYTHON || 'python',['-u','app.py','--port','0','--db',path.join(temp,'browser.sqlite3')],{cwd:root,stdio:['ignore','pipe','pipe']});
let browser;
(async()=>{
  const url = await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('服务启动超时')),15000);
    child.stdout.on('data',chunk=>{const match=chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
    child.on('error',reject);child.on('exit',code=>{if(code)reject(new Error('服务退出 '+code));});
  });
  const executable=process.env.BROWSER_EXECUTABLE || (process.platform==='win32'?'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe':undefined);
  browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);await page.locator('.item-card').first().waitFor();
  const initial=await page.locator('.item-card').count();
  // Regression: localized labels must retain database status codes.
  await page.locator('select[name=status]').selectOption({label:'待认领'});
  const request=page.waitForResponse(r=>r.url().includes('/api/items?')&&r.request().method()==='GET');
  await page.getByRole('button',{name:'筛选',exact:true}).click();
  const filtered=await (await request).json();
  assert.equal(filtered.data.length,initial,'状态筛选应保留所有开放记录');
  await page.locator('.item-card').first().waitFor();
  await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
  async function login(username){
    await page.locator('#account-button').click();
    await page.locator(`[data-action=login][data-username=${username}]`).click();
    await page.locator('#modal').waitFor({state:'hidden'});
    await page.locator('#main h1').waitFor();
  }
  async function publish(kind){
    await page.locator('#main [data-action=publish]').first().click();
    const form=page.locator('#publish-form');
    await form.locator('[name=kind]').selectOption(kind);
    await form.locator('[name=category]').selectOption('证件');
    await form.locator('[name=title]').fill('浏览器回归黑色卡包');
    await form.locator('[name=location]').fill('回归图书馆');
    await form.locator('[name=color]').fill('黑色');
    await form.locator('[name=description]').fill('黑色卡包，内有校园卡。');
    await form.locator('[name=date_from]').fill('2026-10-26');
    await form.locator('[name=date_to]').fill('2026-10-26');
    await form.locator('[name=contact]').fill(kind==='lost'?'alice@browser.example.test':'bob@browser.example.test');
    if(kind==='found'){
      await form.locator('[name=secret_question]').fill('内侧手写的专属文字是什么？');
      await form.locator('[name=secret_answer]').fill('小星河');
      const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=','base64');
      await form.locator('[name=photo]').setInputFiles({name:'example.png',mimeType:'image/png',buffer:png});
    }
    const response=page.waitForResponse(r=>r.url().endsWith('/api/items')&&r.request().method()==='POST');
    await form.getByRole('button',{name:'发布信息',exact:true}).click();
    const result=await (await response).json();assert.ok(result.data?.id,JSON.stringify(result));
    await page.locator('#modal').waitFor({state:'hidden'});
    await page.locator('#main h1').filter({hasText:'我的发布'}).waitFor();
    return result.data.id;
  }
  await login('alice');const lostId=await publish('lost');
  await login('bob');const foundId=await publish('found');
  await login('alice');
  await page.locator(`.item-card[data-id="${lostId}"]`).click();
  await page.getByRole('button',{name:'智能匹配',exact:true}).last().click();
  await page.locator('.match-result').first().waitFor();
  await page.locator(`.match-result [data-id="${foundId}"]`).click();
  assert.ok(!(await page.locator('#modal-body').innerText()).includes('bob@browser.example.test'));
  await page.getByRole('button',{name:'这是我的，申请认领'}).click();
  const claimForm=page.locator('#claim-form');
  await claimForm.locator('[name=answer]').fill('小星河');
  await claimForm.locator('[name=contact]').fill('alice@claim.example.test');
  assert.equal(await claimForm.locator('[name=lost_item_id]').inputValue(),String(lostId));
  await claimForm.getByRole('button',{name:'提交核验申请'}).click();
  await page.locator('#modal').waitFor({state:'hidden'});
  await page.locator('#main h1').filter({hasText:'认领与交接'}).waitFor();
  await login('bob');
  await page.getByRole('button',{name:'核验通过',exact:true}).click();
  await page.getByRole('button',{name:'确认操作',exact:true}).click();
  await page.locator('#modal').waitFor({state:'hidden'});
  await page.getByText('失主联系方式：alice@claim.example.test').waitFor();
  await page.getByRole('button',{name:'已交接，确认结案'}).click();
  await page.getByRole('button',{name:'确认操作',exact:true}).click();
  await page.locator('#modal').waitFor({state:'hidden'});
  await page.locator('.pill.completed').waitFor();
  await login('admin');
  await page.locator('[data-view=admin]').click();
  await page.locator('#rule-form').waitFor();
  await page.locator('#rule-form [name=name]').fill('浏览器回归规则');
  await page.getByRole('button',{name:'发布新版本'}).click();
  await page.getByText('当前 v2').waitFor();
  await login('alice');
  await page.locator('nav [data-view=matching]').click();
  await page.getByRole('button',{name:'复算历史'}).first().click();
  await page.getByText(/与历史结果完全一致/).waitFor();
  await page.screenshot({path:path.join(output,'matching.png'),fullPage:true});
  await page.locator('nav [data-view=square]').click();
  await page.locator('.item-card').first().waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  assert.equal(overflow,false,'手机视图不得横向溢出');assert.deepEqual(errors,[],'不得出现页面 JavaScript 错误');
  console.log('PASS: browser publish/image/filter/match/private-claim/approve/handover/rules/replay/mobile; 0 page errors');
  fs.writeFileSync(path.join(output,'browser-result.json'),JSON.stringify({passed:true,lostId,foundId,pageErrors:errors,mobileOverflow:overflow},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();child.kill();
  const resolved=path.resolve(temp), parent=path.resolve(os.tmpdir())+path.sep;
  if(resolved.startsWith(parent)&&path.basename(resolved).startsWith('campus-browser-'))fs.rmSync(resolved,{recursive:true,force:true});
});
