// The root compatibility manifest exists only on previously installed machines.
const ASSET_ROOT=chrome.runtime.getManifest().background.service_worker.startsWith('extension/')?'extension/':'';
const SESSION_KEY='dictationSession';
const WATCHDOG='dictation-watchdog';
// A fresh id per service-worker lifetime; the page script re-injects itself when it differs.
const BUILD=crypto.randomUUID();
// Quiet window after the transcript appears, guarding against a trailing editor update.
const STABLE_MS=250;
// An idle dictation button with an empty editor for this long means nothing was recognised.
const EMPTY_MS=1500;
// Recordings end automatically at this length and are transcribed, never discarded.
// Tests may shorten it (daemon settings.json recordLimitMs, or chrome.storage.local.recordLimitMs).
const RECORD_LIMIT_MS=8*60*1000;
let limitTimer;
let configuredLimitMs=0;  // test-only override sent by the daemon
async function recordLimit(){
  if(configuredLimitMs>0)return configuredLimitMs;
  const {recordLimitMs}=await chrome.storage.local.get('recordLimitMs');return recordLimitMs>0?recordLimitMs:RECORD_LIMIT_MS;
}
const CHATGPT_URL='https://chatgpt.com/';
let busy=false;
let cancelRequested=false;
let cleaning=false;
let closeRequested=false;
let sleepOperation;
// In-memory copy of the running session; it carries timing marks not yet persisted.
let activeSession;
let wakeCancel=()=>{};
let cancelSignal=new Promise(()=>{});
const ownedBackendTabs=new Set();
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let settingsCache;
function settings(){return settingsCache??=chrome.storage.local.get(['selectors']).then(v=>({selectors:{},...v}));}
chrome.storage.onChanged.addListener((changes,area)=>{if(area==='local' && changes.selectors)settingsCache=undefined;});
async function session(){return (await chrome.storage.session.get(SESSION_KEY))[SESSION_KEY];}
async function save(s){await chrome.storage.session.set({[SESSION_KEY]:s});}
async function badge(text,color='#176b55'){await Promise.all([chrome.action.setBadgeText({text}),chrome.action.setBadgeBackgroundColor({color})]);}
function requestCancel(){cancelRequested=true;wakeCancel();}
async function injectPage(tabId){
  await chrome.scripting.executeScript({target:{tabId},func:build=>{globalThis.__backgroundDictationBuild=build;},args:[BUILD]});
  await chrome.scripting.executeScript({target:{tabId},files:[ASSET_ROOT+'content/chatgpt-page.js']});
}
async function page(tabId,method,...args){
  for(let attempt=0;;attempt++){
    const result=await chrome.scripting.executeScript({target:{tabId},func:async(build,method,args)=>{
      try {const api=globalThis.__backgroundDictationPage;if(api?.build!==build)return {stale:true};return {ok:true,value:await api[method](...args)};}catch(e){return {ok:false,error:e.message};}
    },args:[BUILD,method,args]});
    const r=result[0]?.result;
    // Inject only when missing or outdated, instead of on every call.
    if(r?.stale && !attempt){await injectPage(tabId);continue;}
    if(!r?.ok)throw Error(r?.error || (r?.stale?'听写页面脚本未就绪。':'无法读取 ChatGPT 页面。'));
    return r.value;
  }
}
const signature=st=>JSON.stringify([st.text,st.start,st.finish,st.cancel]);
// Next page state that differs from `st`, or null if nothing changed within `ms`.
// The page pushes changes via MutationObserver; the local timer bounds the wait
// because timers inside a hidden tab may be throttled.
async function nextState(tabId,selectors,st,ms){
  const changed=await Promise.race([page(tabId,'waitChange',signature(st),selectors,1000).catch(()=>null),pause(ms).then(()=>null)]);
  if(changed?.error)throw Error(changed.error);
  const now=changed && !changed.disposed?changed:await page(tabId,'state',selectors);
  return signature(now)===signature(st)?null:now;
}
async function waitFor(tabId,selectors,done,timeoutMs,timeoutMessage,{cancellable=true,initial}={}){
  const deadline=Date.now()+timeoutMs;
  let st=initial || await page(tabId,'state',selectors);
  while(!done(st)){
    if(cancellable && cancelRequested)throw Error('听写已取消。');
    if(Date.now()>deadline)throw Error(timeoutMessage);
    const next=await Promise.race([nextState(tabId,selectors,st,400),...(cancellable?[cancelSignal]:[])]);
    if(next)st=next;
  }
  return st;
}
async function target(s,method,...args){
  if(s.sink==='desktop')return;
  const result=await chrome.scripting.executeScript({target:{tabId:s.targetTabId,documentIds:[s.targetDocumentId]},func:(method,args)=>{
    try{const api=globalThis.__backgroundDictationTarget;if(!api)throw Error('原网页已刷新。');return {ok:true,value:api[method](...args)};}catch(e){return {ok:false,error:e.message};}
  },args:[method,args]});
  if(!result[0]?.result?.ok)throw Error(result[0]?.result?.error || '原输入页面已失效。');
  return result[0].result.value;
}
// The desktop panel already shows progress; the in-page bubble is only a fallback without the native host.
async function toast(s,text,error=false,ttl=0){
  if(!nativePort)await target(s,'status',text,error,ttl).catch(()=>{});
}
async function click(tabId,action,selectors){
  return page(tabId,'click',action,selectors);
}
function mark(s,name,at=Date.now()){(s.t??={})[name]=at;}
function reportTiming(s,outcome,error){
  const t=s?.t;if(!t)return;
  const span=(a,b)=>t[a] && t[b]?t[b]-t[a]:undefined;
  const entry={at:new Date().toISOString(),outcome,sink:s.sink || 'web',coldStart:!!t.opened,...(t.autoFinish?{autoFinish:t.autoFinish}:{}),
    startupMs:span('key','recording'),openPageMs:span('opened','pageReady'),recordMs:span('recording','stopKey'),
    transcribeMs:span('finishClick','text'),settleMs:span('text','stable'),insertMs:span('stable','inserted'),stopToInsertMs:span('stopKey','inserted'),
    ...(t.trace?{trace:t.trace}:{}),
    ...(error?{error}:{})};
  chrome.storage.session.set({lastTiming:entry}).catch(()=>{});
  try{nativePort?.postMessage({type:'timing',entry});}catch{}
}
async function cleanup(s){
  cleaning=true;
  try{
    clearTimeout(limitTimer);
    await Promise.all([target(s,'forget',s.id).catch(()=>{}),chrome.alarms.clear(WATCHDOG),chrome.storage.session.remove(SESSION_KEY)]);
  }finally{cleaning=false;}
}
async function abort(s,message){
  const cancelled=message==='听写已取消。';
  if(s){
    if(s.clickedStart){
      try{
        const {selectors}=await settings();
        const st=await page(s.backendTabId,'state',selectors);
        if(st.cancel || st.finish){
          await click(s.backendTabId,'cancel',selectors);
          await waitFor(s.backendTabId,selectors,st=>!st.cancel && !st.finish,2000,'录音界面尚未退出',{cancellable:false});
        }
      }catch{
        message+=' 无法确认录音已停止，请打开专用 ChatGPT 页手动停止。';
      }
    }
    await toast(s,message,true);
    await cleanup(s);
    reportTiming(s,cancelled?'cancelled':'error',cancelled?undefined:message);
  }
  await Promise.all([publishStatus(cancelled?'cancelled':'error',message,cancelled,{fix:cancelled?undefined:fixFor(message)}),badge('!', '#a02e2e')]);
}
// What a click on the error panel should do: problems inside the ChatGPT page are fixed
// there; the text itself is always recoverable from the panel history.
function fixFor(message){
  if(/没有识别到/.test(message))return;
  if(/焦点|窗口|标签页|插入|本机/.test(message))return 'copy';
  if(/ChatGPT|听写页|草稿|按钮|麦克风|录音|登录|超时/.test(message))return 'open-backend';
}
async function publishStatus(phase,status,ok=true,extra={}){
  if(closeRequested && !['closing','sleeping'].includes(phase))return;
  const fields=Object.fromEntries(Object.entries(extra).filter(([,v])=>v!==undefined));
  try{nativePort?.postMessage({type:'status',phase,status,ok,...fields});}catch{}
  await chrome.storage.session.set({lastStatus:status});
}
async function start(tab,desktopTarget,keyAt){
  await publishStatus('starting','正在准备后台 ChatGPT 听写页，请等待录音提示。');
  const t={key:keyAt};
  const config=await settings();
  let {backendTabId}=await chrome.storage.session.get('backendTabId');
  let backend=backendTabId?await chrome.tabs.get(backendTabId).catch(()=>null):null;
  if(!backend){
    if(!(await chrome.storage.local.get('backendInitialized')).backendInitialized)throw Error('先打开扩展面板，初始化并绑定专用 ChatGPT 听写页。');
    // Cold start (first use, after closing, or after Chrome restarts): say why it takes longer.
    t.opened=Date.now();
    await publishStatus('starting','正在打开 ChatGPT 听写页…',true,{detail:'正在打开 ChatGPT…'});
    backend=await createBackendTab();backendTabId=backend.id;ownedBackendTabs.add(backendTabId);
    await chrome.storage.session.set({backendTabId});
    const deadline=Date.now()+30000;let ready=false;
    while(Date.now()<deadline){
      if(cancelRequested)throw Error('听写已取消。');
      try{
        const st=await page(backendTabId,'state',config.selectors);
        if(st.start && st.text!==null){ready=true;break;}
      }catch{}
      await Promise.race([pause(300),cancelSignal]);
    }
    if(!ready)throw Error('后台听写页未就绪，请确认 ChatGPT 登录状态。');
    t.pageReady=Date.now();
  }
  backend=await chrome.tabs.get(backendTabId);
  if(!desktopTarget && !tab?.id)throw Error('无法取得当前标签页。');
  if(!desktopTarget && tab.id===backendTabId)throw Error('请在其他网页的输入框中使用快捷键。');
  if(!/^https:\/\/chatgpt\.com(?:\/|$)/.test(backend.url || ''))throw Error('绑定的听写页已关闭或离开 ChatGPT，请重新绑定。');
  if(backend.discarded || backend.frozen)throw Error('听写页已休眠，请手动打开一次恢复后重试。');
  const s={id:crypto.randomUUID(),backendTabId,phase:'starting',startedAt:Date.now(),t};
  if(desktopTarget){s.sink='desktop';s.desktopTarget=desktopTarget;}else{
    const injected=await chrome.scripting.executeScript({target:{tabId:tab.id},files:[ASSET_ROOT+'content/target.js']});
    s.targetTabId=tab.id;s.targetDocumentId=injected[0].documentId;
    if(!s.targetDocumentId)throw Error('无法取得目标文档标识。');
  }
  await save(s);activeSession=s;
  // Independent setup steps run concurrently. allSettled keeps every write finished
  // before a failure reaches abort(), so the session is never left half-saved.
  const steps=await Promise.allSettled([
    page(backendTabId,'state',config.selectors),
    target(s,'capture',s.id),
    chrome.storage.local.set({backendInitialized:true}),
    badge('…'),
    chrome.tabs.update(backendTabId,{autoDiscardable:false})
  ]);
  const failed=steps.find(r=>r.status==='rejected');if(failed)throw failed.reason;
  const initial=steps[0].value;
  if(initial.text===null)throw Error('专用 ChatGPT 页没有输入编辑器，请确认已登录并进入普通聊天。');
  if(initial.text.trim())throw Error('专用听写页有未清空的草稿，请处理后再试；工具不会覆盖它。');
  if(!initial.start || initial.finish || initial.cancel)throw Error('听写页不是空闲状态，或按钮未识别。请查看面板诊断。');
  if(cancelRequested)throw Error('听写已取消。');
  await toast(s,'正在启动 ChatGPT 后台听写…');
  s.clickedStart=true;await save(s);
  await click(backendTabId,'start',config.selectors);
  mark(s,'startClick');
  await waitFor(backendTabId,config.selectors,st=>st.finish || st.cancel,12000,'12 秒内未确认进入听写状态。请检查麦克风权限，或在面板设置结束/取消按钮选择器。');
  mark(s,'recording');
  s.phase='recording';
  const limitMs=await recordLimit();
  // The timer ends the recording on time; the alarm is a fallback if the worker was suspended.
  clearTimeout(limitTimer);limitTimer=setTimeout(()=>autoFinish(s.id),limitMs);
  await Promise.all([save(s),publishStatus('recording','现在可以讲话，按 F9 结束，F8 取消。',true,{limitMs}),badge('REC'),toast(s,'正在听写 · F9 结束 · F8 取消'),
    chrome.alarms.create(WATCHDOG,{delayInMinutes:Math.max(.5,limitMs/60000+.5)})]);
}
async function finish(s,keyAt,reason){
  activeSession=s;
  clearTimeout(limitTimer);
  const {selectors}=await settings();
  mark(s,'stopKey',keyAt);
  s.phase='transcribing';
  // Stop the recording first: everything else can happen while ChatGPT transcribes.
  const clicking=click(s.backendTabId,'finish',selectors);
  const detail=reason==='limit'?`已到 ${Math.round(await recordLimit()/60000)} 分钟上限，自动结束并转写`:undefined;
  if(reason)(s.t??={}).autoFinish=reason;
  await Promise.all([save(s),publishStatus('transcribing','正在等待 ChatGPT 返回文字，F8 可以取消。',true,{detail}),badge('…'),toast(s,'ChatGPT 正在转写…')]);
  await clicking;
  mark(s,'finishClick');
  const ready=st=>st.start && !st.finish && !st.cancel && (st.text || '').trim();
  const timeout='转写等待超时。请查看专用听写页；若已有文字，可手动复制。';
  const deadline=Date.now()+90000;
  // Page states after stopping, for the timing log: [ms, start, finish, cancel, text length].
  const trace=s.t.trace=[];let last='';
  // While transcribing, ChatGPT hides the dictation button. If it comes back with an empty
  // editor, nothing was recognised: report that instead of waiting for the full timeout.
  let emptySince=0;
  const nothing=st=>st.start && !st.finish && !st.cancel && !(st.text || '').trim();
  const traced=st=>{
    const sig=signature(st);if(sig!==last && trace.length<12){last=sig;trace.push([Date.now()-s.t.finishClick,+st.start,+st.finish,+st.cancel,(st.text || '').length]);}
    emptySince=nothing(st)?emptySince || Date.now():0;
    return ready(st) || (emptySince && Date.now()-emptySince>=EMPTY_MS);
  };
  let st=await waitFor(s.backendTabId,selectors,traced,90000,timeout);
  if(!ready(st))throw Error('没有识别到语音，请靠近麦克风再说一次。');
  mark(s,'text');
  for(let next;(next=await nextState(s.backendTabId,selectors,st,STABLE_MS));){
    if(cancelRequested)throw Error('听写已取消。');
    st=ready(next)?next:await waitFor(s.backendTabId,selectors,ready,deadline-Date.now(),timeout,{initial:next});
  }
  mark(s,'stable');
  const transcript=st.text;
  if(cancelRequested || closeRequested)throw Error('听写已关闭。');
  await chrome.storage.session.set({lastResult:transcript,lastResultAt:Date.now()});
  let status='文字已填入原输入框。';let failed=false;
  try{
    if(s.sink==='desktop'){
      const inserted=await nativeRequest({type:'insert',text:transcript,target:s.desktopTarget});
      if(!inserted.ok)throw Error(inserted.error);
    }else{
      const currentTab=await chrome.tabs.query({active:true,lastFocusedWindow:true});
      if(currentTab[0]?.id!==s.targetTabId)throw Error('当前标签页已改变，转写结果已保留在扩展面板。');
      await target(s,'insert',s.id,transcript);
    }
    mark(s,'inserted');
    await toast(s,'听写已填入',false,3000);
  }catch(e){status=e.message;failed=true;await toast(s,status,true);}
  await Promise.all([publishStatus(failed?'error':'done',status,!failed,{fix:failed?'copy':undefined}),badge(failed?'COPY':'✓',failed?'#966000':'#176b55')]);
  reportTiming(s,failed?'error':'done',failed?status:undefined);
  await Promise.all([page(s.backendTabId,'clear',transcript).catch(()=>{}),cleanup(s)]);
}
// Reaching the recording limit finishes and transcribes instead of discarding.
async function autoFinish(id){
  const s=await session();
  if(s?.id!==id || s.phase!=='recording')return;
  if(busy){setTimeout(()=>autoFinish(id),500);return;}
  await run('toggle',null,null,Date.now(),'limit');
}
// Chrome started in the background by the daemon has no window yet; a minimized,
// unfocused window keeps the user's input window focused.
async function createBackendTab(){
  const windows=await chrome.windows.getAll({windowTypes:['normal']});
  if(windows.length)return chrome.tabs.create({url:CHATGPT_URL,active:false});
  const created=await chrome.windows.create({url:CHATGPT_URL,focused:false,state:'minimized'});
  return created.tabs[0];
}
// From the panel: show the dedicated page so the user can log in, clear a draft, etc.
async function openBackend(){
  const {backendTabId}=await chrome.storage.session.get('backendTabId');
  let tab=backendTabId?await chrome.tabs.get(backendTabId).catch(()=>null):null;
  if(!tab){
    tab=await chrome.tabs.create({url:CHATGPT_URL,active:true});
    await chrome.storage.session.set({backendTabId:tab.id});
    await chrome.storage.local.set({backendInitialized:true});
  }
  await chrome.tabs.update(tab.id,{active:true});
  await chrome.windows.update(tab.windowId,{focused:true,state:'normal'});
  return {ok:true};
}
async function run(action,tab,desktopTarget,keyAt=Date.now(),reason){
  if(closeRequested)return {ok:false,error:'正在关闭听写，请稍候。'};
  if(busy){if(action==='cancel'){requestCancel();await publishStatus('cancelling','正在取消当前任务…');}else{const current=await session();await publishStatus(current?.phase || 'starting','当前任务正在处理中，请等待；F8 可以取消。');}return {ok:false,error:'正在启动或转写，请稍候；取消请求会在当前操作后处理。'};}
  busy=true;cancelRequested=false;
  cancelSignal=new Promise(resolve=>{wakeCancel=()=>resolve(null);});
  try{
    const s=await session();
    if(action==='cancel'){
      if(s)await abort(s,'听写已取消。');else await publishStatus('cancelled','当前没有进行中的听写。');
      return {ok:true};
    }
    if(s?.phase==='recording')await finish(s,keyAt,reason);
    else if(s)throw Error('上次任务尚未完成，请点击取消，再重新开始。');
    else await start(tab,desktopTarget,keyAt);
    return {ok:true};
  }catch(e){
    const saved=await session();
    await abort(saved && activeSession?.id===saved.id?activeSession:saved,e.message);return {ok:false,error:e.message};
  }
  finally{busy=false;cancelRequested=false;activeSession=undefined;}
}
async function sleepDictation(){
  if(sleepOperation)return sleepOperation;
  closeRequested=true;requestCancel();
  sleepOperation=(async()=>{
    await chrome.storage.local.set({dictationSleeping:true});
    await publishStatus('closing','正在停止听写并关闭专用页。');
    const retire=async()=>{
      const {backendTabId}=await chrome.storage.session.get('backendTabId');
      if(backendTabId){
        const tab=await chrome.tabs.get(backendTabId).catch(()=>null);
        if(tab && (ownedBackendTabs.has(backendTabId) || [tab.url,tab.pendingUrl].some(url=>/^https:\/\/chatgpt\.com(?:\/|$)/.test(url || '')))){await chrome.tabs.remove(backendTabId);ownedBackendTabs.delete(backendTabId);}
      }
    };
    try{
      await retire();
      while(busy){await retire();await pause(50);}
      // Starting may have created a new page while the close request was arriving.
      await retire();
      const remaining=await session();if(remaining)await cleanup(remaining);
      await chrome.alarms.clear(WATCHDOG);
      await chrome.storage.session.remove('backendTabId');
      await badge('');
      await publishStatus('sleeping','听写已关闭，按 F9 重新打开。');
      return {ok:true};
    }catch(e){
      closeRequested=false;await chrome.storage.local.set({dictationSleeping:false});
      await publishStatus('error','关闭未完成：'+e.message,false);return {ok:false,error:e.message};
    }
  })();
  try{return await sleepOperation;}finally{sleepOperation=null;}
}
async function resumeAndRun(action,tab,desktopTarget,keyAt){
  if(sleepOperation)return {ok:false,error:'正在关闭听写，请稍候。'};
  if(action==='toggle'){
    closeRequested=false;await chrome.storage.local.set({dictationSleeping:false});
  }else if((await chrome.storage.local.get('dictationSleeping')).dictationSleeping)return {ok:true};
  return run(action,tab,desktopTarget,keyAt);
}
chrome.commands.onCommand.addListener(async(command,tab)=>{
  const keyAt=Date.now();
  if(!tab)tab=(await chrome.tabs.query({active:true,lastFocusedWindow:true}))[0];
  await resumeAndRun(command==='cancel-dictation'?'cancel':'toggle',tab,undefined,keyAt);
});
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(sender.id!==chrome.runtime.id)return;
  if(sender.tab){
    if(message.type!=='cancel-target')return;
    (async()=>{
      const s=await session();
      if(!s || sender.tab.id!==s.targetTabId || sender.documentId!==s.targetDocumentId || message.token!==s.id)throw Error('取消请求与当前输入文档不匹配。');
      return run('cancel');
    })().then(respond).catch(e=>respond({ok:false,error:e.message}));
    return true;
  }
  if(!sender.url?.startsWith(chrome.runtime.getURL('')))return;
  (async()=>{
    switch(message.type){
      case 'state': return {ok:true,...await chrome.storage.session.get(['backendTabId',SESSION_KEY,'lastStatus','lastResult','lastResultAt','lastTiming']),...await settings(),commands:await chrome.commands.getAll(),nativeConnected:!!nativePort};
      case 'prepare': {
        if(await session())throw Error('请先结束或取消当前听写。');
        const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:true});
        await chrome.storage.local.set({backendInitialized:true});
        await chrome.storage.session.set({backendTabId:tab.id,lastStatus:'在新打开的专用页登录，并手动试一次听写授权麦克风；清空草稿后即可使用。'});
        return {ok:true};
      }
      case 'bind': {
        if(await session())throw Error('请先结束或取消当前听写。');
        const tab=(await chrome.tabs.query({active:true,currentWindow:true}))[0];
        if(!/^https:\/\/chatgpt\.com(?:\/|$)/.test(tab?.url || ''))throw Error('先在一个专用 ChatGPT 空白聊天页打开此面板，再点击绑定。');
        await chrome.storage.local.set({backendInitialized:true});
        await chrome.storage.session.set({backendTabId:tab.id,lastStatus:'已绑定。确保草稿为空，在任意常规输入框中按 F9。'});
        return {ok:true};
      }
      case 'cancel': return run('cancel');
      case 'selectors': await chrome.storage.local.set({selectors:message.selectors});return {ok:true};
      case 'diagnose': {
        const {backendTabId}=await chrome.storage.session.get('backendTabId');
        if(!backendTabId)throw Error('请先绑定专用页。');
        return {ok:true,diagnostic:await page(backendTabId,'inspect')};
      }
      default: throw Error('未知操作。');
    }
  })().then(respond).catch(e=>respond({ok:false,error:e.message}));
  return true;
});
chrome.alarms.onAlarm.addListener(async alarm=>{
  if(alarm.name!==WATCHDOG)return;
  const s=await session();
  if(s?.phase==='recording')return autoFinish(s.id);
  if(busy){requestCancel();return;}
  if(s)await run('cancel');
});

// The native host owns global F9/F8 and desktop insertion. No private web API is replayed.
let nativePort;
const nativePending=new Map();
// Reconnect quickly with backoff; the alarm is only a fallback for when the worker was suspended.
const RECONNECT_ALARM='native-reconnect';
let reconnectDelay=1000,reconnectTimer;
function scheduleReconnect(){
  clearTimeout(reconnectTimer);
  reconnectTimer=setTimeout(connectNative,reconnectDelay);
  reconnectDelay=Math.min(reconnectDelay*2,30000);
  chrome.alarms.create(RECONNECT_ALARM,{delayInMinutes:1});
}
function nativeRequest(message){
  if(!nativePort)return Promise.reject(Error('本机听写服务未连接，文字已保留在扩展面板。'));
  const requestId=crypto.randomUUID();
  return new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{nativePending.delete(requestId);reject(Error('本机文字插入超时，结果已保留。'));},10000);
    nativePending.set(requestId,{resolve,reject,timeout});
    try{nativePort.postMessage({...message,requestId});}catch(e){clearTimeout(timeout);nativePending.delete(requestId);reject(e);}
  });
}
function connectNative(){
  if(nativePort)return;
  clearTimeout(reconnectTimer);
  try{
    const port=chrome.runtime.connectNative('com.chelizi.chatgpt_dictation');nativePort=port;
    chrome.storage.local.get('dictationSleeping').then(state=>{
      closeRequested=!!state.dictationSleeping;
      try{port.postMessage({type:'mode',sleeping:closeRequested});}catch{}
    });
    port.onDisconnect.addListener(()=>{
      const error=chrome.runtime.lastError?.message || '本机服务断开';
      if(nativePort===port)nativePort=null;
      for(const pending of nativePending.values()){clearTimeout(pending.timeout);pending.reject(Error(error));}
      nativePending.clear();scheduleReconnect();
    });
    port.onMessage.addListener(message=>{
      if(message.type==='hello'){reconnectDelay=1000;configuredLimitMs=0;chrome.alarms.clear(RECONNECT_ALARM);return;}
      if(message.type==='config'){configuredLimitMs=Number(message.recordLimitMs) || 0;return;}
      if(message.type==='insert-result'){
        const pending=nativePending.get(message.requestId);if(!pending)return;
        clearTimeout(pending.timeout);nativePending.delete(message.requestId);pending.resolve(message);return;
      }
      if(message.type!=='desktop-command' || !['toggle','cancel','sleep','open-backend'].includes(message.action))return;
      (async()=>{
        const result=message.action==='sleep'?await sleepDictation():message.action==='open-backend'?await openBackend():await resumeAndRun(message.action,null,message.target,message.keyAt);
        port.postMessage({type:'command-result',requestId:message.requestId,action:message.action,...result});
      })().catch(()=>{});
    });
  }catch{nativePort=null;scheduleReconnect();}
}
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name===RECONNECT_ALARM)connectNative();});
chrome.runtime.onStartup.addListener(connectNative);
connectNative();
