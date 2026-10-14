// Minimal CDP helper for the launch test. Usage:
//   node cdp.mjs PORT load DIR          -> load an unpacked extension, print its id
//   node cdp.mjs PORT eval ID EXPR      -> evaluate EXPR in that extension's service worker
//   node cdp.mjs PORT pages             -> list page targets as JSON
const [port,command,...args]=process.argv.slice(2);
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function connect(url){
  const ws=new WebSocket(url);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let id=0;const pending=new Map();
  ws.onmessage=e=>{const m=JSON.parse(e.data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}};
  return {close:()=>ws.close(),call:(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));})};
}
const base=`http://127.0.0.1:${port}`;
const browser=await connect((await (await fetch(base+'/json/version')).json()).webSocketDebuggerUrl);
if(command==='load'){console.log((await browser.call('Extensions.loadUnpacked',{path:args[0]})).id);}
else if(command==='eval'){
  let worker;
  for(let i=0;i<50 && !worker;i++){worker=(await browser.call('Target.getTargets')).targetInfos.find(t=>t.type==='service_worker' && t.url.includes(args[0]));if(!worker)await pause(200);}
  if(!worker)throw Error('service worker not found');
  const sw=await connect(`ws://127.0.0.1:${port}/devtools/page/${worker.targetId}`);
  const r=await sw.call('Runtime.evaluate',{expression:args[1],awaitPromise:true,returnByValue:true});
  console.log(JSON.stringify(r.result.value ?? null));sw.close();
}
else if(command==='pages'){console.log(JSON.stringify((await browser.call('Target.getTargets')).targetInfos.filter(t=>t.type==='page').map(t=>t.url)));}
browser.close();
