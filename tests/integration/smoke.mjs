import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,copyFile,rm,readdir,cp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import http from 'node:http';
const root=resolve(new URL('../../extension/',import.meta.url).pathname);
const temp=await mkdtemp(join(tmpdir(),'dictation-extension-test-'));
const profile=join(temp,'profile');const extension=join(temp,'extension');
const {mkdir}=await import('node:fs/promises');await mkdir(extension);
await cp(root,extension,{recursive:true});
const manifest=JSON.parse(await readFile(join(extension,'manifest.json'),'utf8'));
manifest.host_permissions.push('http://127.0.0.1/*','http://localhost/*'); // Test harness only; release uses activeTab.
await writeFile(join(extension,'manifest.json'),JSON.stringify(manifest));
await writeFile(join(extension,'background/index.js'),await readFile(join(extension,'background/index.js'),'utf8')+'\nglobalThis.__testRun=run;\n');
const mock=`<!doctype html><meta charset="utf-8"><form><div role="textbox" contenteditable="true" data-composer-markdown><p><br></p></div><button type="button" id="start" aria-label="听写"></button><button type="button" id="finish" aria-label="停止听写" hidden></button><button type="button" id="cancel" aria-label="取消听写" hidden></button><button type="button" id="transcribeSend" aria-label="转录并发送" hidden></button></form><button type="button" id="send" aria-label="Send prompt">Send</button><script>
window.sent=0;window.recorded=0;window.lastTrusted=false;window.stream=null;
const start=document.querySelector('#start'),finish=document.querySelector('#finish'),cancel=document.querySelector('#cancel');
start.onclick=async e=>{lastTrusted=e.isTrusted;stream=await navigator.mediaDevices.getUserMedia({audio:true});recorded++;start.hidden=true;finish.hidden=false;cancel.hidden=false;transcribeSend.hidden=false;};
function stop(){stream?.getTracks().forEach(t=>t.stop());start.hidden=false;finish.hidden=true;cancel.hidden=true;transcribeSend.hidden=true;}
finish.onclick=()=>{
const editor=document.querySelector('[data-composer-markdown]');
if(window.renderMode==='early'){editor.textContent='今天的工作已经完成。';setTimeout(stop,500);}
else if(window.renderMode==='late'){stop();setTimeout(()=>editor.textContent='今天的工作',20);setTimeout(()=>editor.textContent='今天的工作已经完成。',160);}
else {stop();setTimeout(()=>editor.textContent='今天的工作已经完成。',200);}
};cancel.onclick=stop;send.onclick=()=>sent++;transcribeSend.onclick=()=>sent++;
</script>`;
const server=http.createServer(async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');if(req.url.startsWith('/frame'))return res.end('<!doctype html><input id=frameTarget value=框><textarea id=frameArea></textarea>');
if(req.url.startsWith('/iframes'))return res.end('<!doctype html><input id=mainTarget value=主><iframe src="/frame"></iframe><iframe src="http://localhost:'+server.address().port+'/frame"></iframe>');
res.end('<!doctype html><meta charset="utf-8"><input id="target" value="开头结尾"><textarea id="area"></textarea><div id="editable" contenteditable="true">原文</div>');});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const chrome=spawn('google-chrome',['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-timer-throttling','--enable-unsafe-extension-debugging','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let stderr='';chrome.stderr.on('data',b=>stderr+=b);
const pause=ms=>new Promise(r=>setTimeout(r,ms));const sockets=[];
async function connect(url){const ws=new WebSocket(url);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});let id=0;const pending=new Map();const listeners=new Map();ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}else for(const fn of listeners.get(m.method)||[])fn(m.params);};sockets.push(ws);return {call:(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));}),on:(name,fn)=>listeners.set(name,[...(listeners.get(name)||[]),fn])};}
async function evaluate(c,expression){const r=await c.call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
try{
let port;for(let n=0;n<120;n++){try{port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{}if(chrome.exitCode!==null)throw Error(stderr.slice(-1000));await pause(100);}assert(port,'Chrome startup');const endpoint='http://127.0.0.1:'+port;
const version=await (await fetch(endpoint+'/json/version')).json();const browser=await connect(version.webSocketDebuggerUrl);
const {id:extensionId}=await browser.call('Extensions.loadUnpacked',{path:extension});
async function tab(url){const t=await(await fetch(endpoint+'/json/new?'+encodeURIComponent(url),{method:'PUT'})).json();return {id:t.id,cdp:await connect(t.webSocketDebuggerUrl)};}
const backend=await tab('about:blank');
backend.cdp.on('Fetch.requestPaused',p=>{backend.cdp.call('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/html; charset=utf-8'}],body:Buffer.from(mock).toString('base64')}).catch(()=>{});});
await backend.cdp.call('Fetch.enable',{patterns:[{urlPattern:'https://chatgpt.com/*',resourceType:'Document'}]});await backend.cdp.call('Page.navigate',{url:'https://chatgpt.com/'});await pause(300);
await tab('chrome-extension://'+extensionId+'/popup/popup.html');
let worker;for(let i=0;i<40;i++){const ts=(await browser.call('Target.getTargets')).targetInfos;const t=ts.find(t=>t.type==='service_worker' && t.url.includes(extensionId));if(t){worker=await connect('ws://127.0.0.1:'+port+'/devtools/page/'+t.targetId);break;}await pause(100);}assert(worker,'Extension service worker running');
const backendId=await evaluate(worker,"(async()=>{const t=await chrome.tabs.query({url:'https://chatgpt.com/*'});await chrome.storage.session.set({backendTabId:t[0].id});return t[0].id;})()");
const foreground=await tab('http://127.0.0.1:'+server.address().port+'/');
await foreground.cdp.call('Emulation.setFocusEmulationEnabled',{enabled:true}); // Stable headless window focus; frame focus still follows the active editor.
await pause(200);await foreground.cdp.call('Page.bringToFront');
const targetId=await evaluate(worker,"(async()=>{const t=await chrome.tabs.query({active:true,lastFocusedWindow:true});return t[0].id;})()");
const invoke=async action=>{await foreground.cdp.call('Page.bringToFront');return evaluate(worker,`__testRun(${JSON.stringify(action)},{id:${targetId}})`);};
const state=()=>evaluate(worker,"chrome.storage.session.get(null)");
async function overrideEditing(tabId,disabled){return evaluate(worker,`chrome.scripting.executeScript({target:{tabId:${tabId}},func:disabled=>{if(disabled){globalThis.testOriginalExec=document.execCommand;document.execCommand=()=>false;}else document.execCommand=globalThis.testOriginalExec;},args:[${disabled}]})`);}

await evaluate(foreground.cdp,"target.focus();target.setSelectionRange(2,2)");
const startResult=await invoke('toggle');assert.equal(startResult.ok,true,'start: '+JSON.stringify(startResult));
assert.equal((await state()).dictationSession.phase,'recording');
assert.equal(await evaluate(backend.cdp,'lastTrusted'),false,'DOM background click');
assert.equal((await invoke('toggle')).ok,true,'finish');
assert.equal(await evaluate(foreground.cdp,'target.value'),'开头今天的工作已经完成。结尾','insert at caret');
assert.equal(await evaluate(backend.cdp,'sent'),0,'never sent a chat message');
assert.equal(await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent"),'','draft cleared');
assert.equal((await state()).dictationSession,undefined,'session cleaned');
assert.equal(await evaluate(worker,'(async()=>{return (await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0].id;})()'),targetId,'foreground tab unchanged');
console.log('PASS background start/finish, DOM click, insertion, no chat send, cleanup, no foreground switch');
await foreground.cdp.call('Page.bringToFront');await evaluate(foreground.cdp,'target.focus()');
await foreground.cdp.call('Input.dispatchKeyEvent',{type:'rawKeyDown',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});
await foreground.cdp.call('Input.dispatchKeyEvent',{type:'keyUp',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});
assert.equal(await evaluate(foreground.cdp,'target.value'),'开头结尾','native Ctrl+Z restores pre-dictation value');
console.log('PASS actual Ctrl+Z undoes input insertion');

await evaluate(foreground.cdp,"target.focus();target.setSelectionRange(0,0)");assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));await evaluate(foreground.cdp,"target.value='用户修改的新文字'");assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));assert.equal(await evaluate(foreground.cdp,'target.value'),'用户修改的新文字');assert.equal((await state()).lastResult,'今天的工作已经完成。');assert.match((await state()).lastStatus,/焦点|内容或光标已改变/);console.log('PASS changed input preserved, transcript available for copying');
await foreground.cdp.call('Page.bringToFront');await evaluate(foreground.cdp,"area.focus();area.setSelectionRange(0,0)");assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));assert.equal((await invoke('cancel')).ok,true);assert.equal(await evaluate(backend.cdp,'stream.getAudioTracks()[0].readyState'),'ended');assert.equal(await evaluate(foreground.cdp,'area.value'),'');console.log('PASS cancel stops recording and does not insert');
await evaluate(foreground.cdp,"editable.focus();const selection=window.getSelection();const range=document.createRange();range.selectNodeContents(editable);range.collapse(false);selection.removeAllRanges();selection.addRange(range)");assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));assert.equal(await evaluate(foreground.cdp,'editable.textContent'),'原文今天的工作已经完成。');console.log('PASS contenteditable insertion');
await evaluate(worker,"chrome.storage.local.set({recordLimitMs:1500})");await evaluate(foreground.cdp,"area.value='';area.focus();area.setSelectionRange(0,0)");assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));for(let i=0;i<50 && (await state()).dictationSession;i++)await pause(100);assert.equal(await evaluate(foreground.cdp,'area.value'),'今天的工作已经完成。','recording limit transcribes instead of discarding');assert.equal((await state()).lastTiming.autoFinish,'limit');await evaluate(worker,"chrome.storage.local.remove('recordLimitMs')");console.log('PASS recording limit auto-finishes and transcribes');
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent='个人草稿'");await evaluate(foreground.cdp,'area.focus()');const refused=await invoke('toggle');assert.equal(refused.ok,false);assert.match(refused.error,/草稿/);assert.equal(await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent"),'个人草稿');console.log('PASS non-empty backend draft refused without overwrite');

// Guarded setter fallback, cancelled events, and application rewrite protection.
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent=''");
async function prepareArea(){await foreground.cdp.call('Page.bringToFront');await evaluate(foreground.cdp,"area.value='';area.focus();area.setSelectionRange(0,0)");}
await prepareArea();await overrideEditing(targetId,true);
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
assert.equal(await evaluate(foreground.cdp,'area.value'),'今天的工作已经完成。');
await overrideEditing(targetId,false);
console.log('PASS unsupported native editing falls back to setter');
await prepareArea();await evaluate(foreground.cdp,"area.addEventListener('beforeinput',e=>e.preventDefault(),{once:true})");
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');assert.equal(await evaluate(foreground.cdp,'area.value'),'');
assert.match((await state()).lastStatus,/阻止/);
await prepareArea();await evaluate(foreground.cdp,"area.addEventListener('input',()=>area.value='应用改写',{once:true})");
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');assert.equal(await evaluate(foreground.cdp,'area.value'),'应用改写');
console.log('PASS cancellation and application rewrites are preserved');
// A real textarea native edit keeps undo and emits one input notification.
await prepareArea();await evaluate(foreground.cdp,"window.inputCount=0;area.oninput=()=>inputCount++");
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
assert.equal(await evaluate(foreground.cdp,'inputCount'),1);
await foreground.cdp.call('Page.bringToFront');await evaluate(foreground.cdp,'area.focus()');
await foreground.cdp.call('Input.dispatchKeyEvent',{type:'rawKeyDown',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});
await foreground.cdp.call('Input.dispatchKeyEvent',{type:'keyUp',key:'z',code:'KeyZ',windowsVirtualKeyCode:90,modifiers:2});
assert.equal(await evaluate(foreground.cdp,'area.value'),'');
console.log('PASS textarea Ctrl+Z and single input notification');
// Keep the full text-quiet window for late chunks; count already observed quiet time.
await prepareArea();await evaluate(backend.cdp,"window.renderMode='late'");
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
assert.equal(await evaluate(foreground.cdp,'area.value'),'今天的工作已经完成。');
await prepareArea();await evaluate(backend.cdp,"window.renderMode='early'");
assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
const earlyTiming=(await state()).lastTiming;
assert(earlyTiming.settleMs<150,'early text avoids a fresh 250ms wait: '+JSON.stringify(earlyTiming));
console.log('PASS late text retained; early text reduces settle time to '+earlyTiming.settleMs+'ms');
await evaluate(backend.cdp,"window.renderMode='normal'");
// Model-aware draft clearing: empty paragraphs, cancellation, and failed cleanup ownership.
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').innerHTML='<p><br></p>'");
await prepareArea();assert.equal((await invoke('toggle')).ok,true);await invoke('cancel');
await overrideEditing(backendId,true);
await prepareArea();assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
assert((await state()).pendingDraftCleanup,'failed clear is recorded');
await overrideEditing(backendId,false);
await prepareArea();assert.equal((await invoke('toggle')).ok,true,'retry only known failed cleanup');await invoke('cancel');
assert.equal((await state()).pendingDraftCleanup,undefined);
await evaluate(worker,"chrome.storage.session.set({lastResult:'私人草稿'})");
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent='私人草稿'");
await prepareArea();assert.equal((await invoke('toggle')).ok,false,'matching lastResult alone must not clear');
assert.equal(await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent"),'私人草稿');
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent=''");
console.log('PASS whitespace drafts and scoped failed-cleanup retry; private drafts protected');
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent=''");
await overrideEditing(backendId,true);await prepareArea();assert.equal((await invoke('toggle')).ok,true);await invoke('toggle');
await overrideEditing(backendId,false);
const ownedText=(await state()).pendingDraftCleanup.text;
await backend.cdp.call('Page.bringToFront');await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').focus()");
await backend.cdp.call('Input.insertText',{text:'用户编辑'});
await evaluate(backend.cdp,`document.querySelector('[data-composer-markdown]').textContent=${JSON.stringify(ownedText)}`);
await prepareArea();assert.equal((await invoke('toggle')).ok,false,'trusted user edits revoke failed-cleanup ownership');
assert.equal(await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent"),ownedText);
await evaluate(backend.cdp,"document.querySelector('[data-composer-markdown]').textContent=''");
console.log('PASS user edits revoke automatic draft cleanup even when the text matches');

// Same-origin and authorized cross-origin frame documents, including focus/navigation changes.
await foreground.cdp.call('Page.navigate',{url:'http://127.0.0.1:'+server.address().port+'/iframes'});await pause(300);
async function frameAction(host,expression){return evaluate(worker,`chrome.scripting.executeScript({target:{tabId:${targetId},allFrames:true},world:'MAIN',func:(host,expression)=>location.hostname===host && !!document.querySelector('#frameTarget')?eval(expression):null,args:${JSON.stringify([host,expression])}})`);}
async function focusFrame(host){await foreground.cdp.call('Page.bringToFront');await frameAction(host,"frameTarget.focus();frameTarget.setSelectionRange(1,1)");}
for(const host of ['127.0.0.1','localhost']){
await focusFrame(host);assert.equal((await invoke('toggle')).ok,true,JSON.stringify(await state()));await invoke('toggle');
const values=await frameAction(host,'frameTarget.value');assert(values.some(v=>v.result==='框今天的工作已经完成。'),JSON.stringify(values));
}
await focusFrame('localhost');assert.equal((await invoke('toggle')).ok,true);
await evaluate(foreground.cdp,'mainTarget.focus()');await invoke('toggle');
assert.match((await state()).lastStatus,/焦点/);
await focusFrame('127.0.0.1');assert.equal((await invoke('toggle')).ok,true);
await evaluate(foreground.cdp,"document.querySelector('iframe').src='/frame?new'");await pause(150);await invoke('toggle');
assert.notEqual((await state()).lastStatus,'文字已填入原输入框。');
console.log('PASS same-origin and permitted cross-origin iframe insertion; focus/navigation guards');
// A second isolated extension has no cross-origin host grant. Never redirect into the parent.
const deniedPath=join(temp,'denied-extension');await cp(extension,deniedPath,{recursive:true});
const deniedManifest=JSON.parse(await readFile(join(deniedPath,'manifest.json'),'utf8'));
deniedManifest.host_permissions=deniedManifest.host_permissions.filter(x=>!x.includes('localhost'));
await writeFile(join(deniedPath,'manifest.json'),JSON.stringify(deniedManifest));
const {id:deniedId}=await browser.call('Extensions.loadUnpacked',{path:deniedPath});
await tab('chrome-extension://'+deniedId+'/popup/popup.html');
let deniedWorker;for(let i=0;i<40;i++){const info=(await browser.call('Target.getTargets')).targetInfos.find(t=>t.type==='service_worker'&&t.url.includes(deniedId));if(info){deniedWorker=await connect('ws://127.0.0.1:'+port+'/devtools/page/'+info.targetId);break;}await pause(100);}
assert(deniedWorker,'permission test worker');
let deniedReady=false;for(let i=0;i<50;i++){try{deniedReady=await evaluate(deniedWorker,'!!(chrome.storage?.session && globalThis.__testRun)');}catch{}if(deniedReady)break;await pause(100);}assert(deniedReady,'permission test APIs initialized');
await evaluate(deniedWorker,`chrome.storage.session.set({backendTabId:${backendId}})`);
await focusFrame('localhost');const recorded=await evaluate(backend.cdp,'recorded');
const deniedResult=await evaluate(deniedWorker,`__testRun('toggle',{id:${targetId}})`);
assert.equal(deniedResult.ok,false);assert.equal(await evaluate(backend.cdp,'recorded'),recorded);
assert.equal(await evaluate(foreground.cdp,'mainTarget.value'),'主');
console.log('PASS ungranted cross-origin iframe is refused without recording or parent insertion');

console.log(JSON.stringify({chrome:version.Browser,scope:'Real unpacked extension; mock ChatGPT UI, fake microphone, test-only localhost host permission. Real ChatGPT and shortcut registration require user trial.'}));
}catch(e){console.error(e);process.exitCode=1;}finally{for(const s of sockets)s.close();chrome.kill('SIGTERM');server.close();await pause(400);await rm(temp,{recursive:true,force:true}).catch(()=>{});}
