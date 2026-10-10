// Browser harness for the actual extension webview JS, against an isolated QA API.
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
(async()=>{
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    let token;
    await page.exposeFunction('hostBridge',async message=>{
      try {
        let endpoint=message.path,method=message.method||'GET';
        if(message.type==='login'){endpoint='/auth/login';method='POST';}
        if(message.type==='logout'){endpoint='/auth/logout';method='POST';}
        const response=await fetch((process.env.QA_API||'http://127.0.0.1:8765')+endpoint,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:message.body?JSON.stringify(message.body):undefined});
        const data=response.status===204?null:await response.json();
        if(!response.ok)throw new Error(data.detail||String(response.status));
        if(message.type==='login'){token=data.access_token;return {id:message.id,result:{signedIn:true}};}
        if(message.type==='logout')token=undefined;
        return {id:message.id,result:data};
      }catch(error){return {id:message.id,error:error.message};}
    });
    await page.setContent('<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body><div id="app"></div></body></html>');
    await page.addStyleTag({content:fs.readFileSync(path.join(root,'extension/media/style.css'),'utf8')});
    await page.addScriptTag({content:'window.acquireVsCodeApi=()=>({postMessage:async m=>window.dispatchEvent(new MessageEvent("message",{data:await window.hostBridge(m)}))});'});
    await page.addScriptTag({path:path.join(root,'extension/media/app.js')});
    await page.getByLabel('Email address',{exact:true}).fill('admin@example.com');
    await page.getByLabel('Password',{exact:true}).fill(process.env.QA_PASSWORD||'LocalQa123!');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:'Assignment readiness'}).waitFor();
    fs.mkdirSync(path.join(root,'test-results'),{recursive:true});
    await page.screenshot({path:path.join(root,'test-results/overview.png'),fullPage:true});
    await page.getByRole('button',{name:'Report bug',exact:true}).click();
    await page.getByLabel('Title',{exact:true}).fill('QA checkout error '+Date.now());
    await page.getByLabel('Description',{exact:true}).fill('Checkout crashes when submitting an empty basket in this QA scenario.');
    await page.getByLabel('Steps to reproduce',{exact:true}).fill('Empty the basket, then submit checkout.');
    await page.getByLabel('Environment and version').fill('Synthetic browser QA');
    await page.getByLabel('Component',{exact:true}).fill('checkout');
    await page.getByRole('heading',{name:'Possible duplicates'}).waitFor({timeout:30000});
    await page.getByRole('button',{name:'Submit bug',exact:true}).click();
    await page.getByRole('heading',{name:'Audit history'}).waitFor();
    await page.getByLabel('Assign to',{exact:true}).selectOption({label:'Developer (developer)'});
    await page.getByLabel('Status',{exact:true}).selectOption('In Progress');
    await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await page.getByRole('heading',{name:'Audit history'}).waitFor();
    await page.getByLabel('Add a comment',{exact:true}).fill('Verified UI comment posting.');
    await page.getByRole('button',{name:'Post comment',exact:true}).click();
    await page.getByText('Verified UI comment posting.',{exact:true}).waitFor();
    await page.screenshot({path:path.join(root,'test-results/bug-detail.png'),fullPage:true});
    for(const section of ['Team','Notifications','Settings','Admin']){
      await page.getByRole('button',{name:section,exact:true}).click();
      await page.getByRole('heading',{name:section,exact:true}).waitFor();
    }
    await page.getByRole('heading',{name:'User administration'}).waitFor();
    if(errors.length)throw new Error(errors.join('\n'));
    console.log('Webview smoke passed: login, overview, duplicate check, submit, assign, transition, comment, team, notifications, settings, admin.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
