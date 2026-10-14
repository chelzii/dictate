const $=id=>document.getElementById(id);
async function send(type,extra={}){const r=await chrome.runtime.sendMessage({type,...extra});if(!r?.ok)throw Error(r?.error || '扩展未响应');return r;}
function show(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
async function refresh(){
  const state=await send('state');
  const task=state.dictationSession;
  show(task?`当前：${task.phase} · 后台标签页 ${state.backendTabId}`:state.lastStatus || (state.backendTabId?'专用页已绑定，可以听写。':'先初始化一个专用 ChatGPT 听写页。'));
  $('result').value=state.lastResult || '';
  const t=state.lastTiming,sec=ms=>ms==null?'—':(ms/1000).toFixed(1)+' 秒';
  $('timing').textContent=t?`上次耗时：启动 ${sec(t.startupMs)}${t.coldStart?'（含打开 ChatGPT）':''} · 结束到填入 ${sec(t.stopToInsertMs)}（转写 ${sec(t.transcribeMs)}）`:'';
  for(const key of ['start','finish','cancel'])$(key+'Selector').value=state.selectors?.[key] || '';
  if(!state.nativeConnected)show('本机听写服务未连接，请检查本机服务安装。',true);
}
function button(id,fn){$(id).addEventListener('click',async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){show(e.message,true);}finally{b.disabled=false;}});}
button('prepare',async()=>{await send('prepare');window.close();});
button('bind',async()=>{await send('bind');await refresh();});
button('cancel',async()=>{await send('cancel');await refresh();});
button('copy',async()=>{if(!$('result').value)throw Error('还没有转写文字。');await navigator.clipboard.writeText($('result').value);show('已复制。');});
button('diagnose',async()=>{const r=await send('diagnose');$('diagnostic').textContent=JSON.stringify(r.diagnostic,null,2);});
button('saveSelectors',async()=>{const selectors={};for(const key of ['start','finish','cancel'])selectors[key]=$(key+'Selector').value.trim();await send('selectors',{selectors});show('按钮选择器已保存。');});
refresh().catch(e=>show(e.message,true));
