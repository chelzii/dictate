(() => {
  // background.js sets a fresh build id per service-worker lifetime, so an
  // updated extension always replaces a stale script left in the tab.
  const BUILD=globalThis.__backgroundDictationBuild;
  if (BUILD && globalThis.__backgroundDictationPage?.build===BUILD) return;
  globalThis.__backgroundDictationPage?.dispose?.();
  const visible = el => !!el && !el.disabled && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  function buttons() { return [...document.querySelectorAll('button,[role="button"]')].filter(visible); }
  function label(el) { return [el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('data-testid'),el.textContent].filter(Boolean).join(' ').trim(); }
  const patterns = {
    start: /\b(dictate|start dictation|dictation-button|voice-input-button)\b|听写|语音输入|使用麦克风/i,
    finish: /\b(submit dictation|confirm dictation|stop dictation|finish dictation|stop recording|dictation-submit|dictation-stop|dictation-confirm)\b|提交听写|确认听写|结束听写|停止听写|完成听写|停止录音/i,
    cancel: /\b(cancel dictation|dictation-cancel|cancel recording)\b|取消听写|取消录音/i
  };
  const excluded = /start voice|voice mode|语音模式|语音对话|转录并发送|transcribe and send/i;
  // Scan visible buttons once and share the result between start/finish/cancel lookups.
  function scan() { return buttons().map(el => ({el,label:label(el)})); }
  function find(action, selectors={}, items=scan()) {
    if (selectors[action]) {
      const matches = [...document.querySelectorAll(selectors[action])].filter(visible);
      if (matches.length > 1) throw Error(`自定义 ${action} 选择器必须匹配唯一可用按钮，现在匹配 ${matches.length} 个。`);
      return matches[0] || null;
    }
    const isStart = text => patterns.start.test(text) && !patterns.finish.test(text) && !patterns.cancel.test(text);
    const matches = items.filter(({label:text}) => patterns[action].test(text) && !excluded.test(text) && (action !== 'start' || isStart(text)));
    if (matches.length === 1) return matches[0].el;
    if (matches.length > 1) throw Error(`找到多个 ${action} 按钮，请在扩展面板设置选择器。`);
    // Some ChatGPT builds label the recording controls simply Cancel / Submit.
    // Accept that pair only in a small shared recording control container,
    // with no Dictate button or visible composer and never a chat Send button.
    if (action !== 'start' && !items.some(({label:text}) => isStart(text))) {
      const name=el=>(el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || '').trim();
      const cancels=items.filter(({el})=>/^(cancel|取消|取消录音)$/i.test(name(el))).map(i=>i.el);
      const finishes=items.filter(({el})=>/^(submit|confirm|done|提交|确认|完成)$/i.test(name(el)) && !/send-button|composer-submit/i.test(el.getAttribute('data-testid') || '')).map(i=>i.el);
      const composer=editor();
      const pairs=[];
      for(const c of cancels)for(const f of finishes){
        let container=c.parentElement;
        while(container && !container.contains(f))container=container.parentElement;
        if(container && container!==document.body && container.querySelectorAll('button,[role="button"]').length<=6 && !(composer && visible(composer) && container.contains(composer)))pairs.push({cancel:c,finish:f});
      }
      if(pairs.length===1)return pairs[0][action];
    }
    return null;
  }
  function editor() { return document.querySelector('form [data-composer-markdown][contenteditable="true"]') || document.querySelector('#prompt-textarea') || document.querySelector('form [role="textbox"][contenteditable="true"]') || document.querySelector('[contenteditable="true"][data-placeholder]') || document.querySelector('textarea[placeholder]'); }
  function text() { const el=editor(); return el ? ('value' in el ? el.value : el.innerText || el.textContent || '') : null; }
  function point(action,selectors) {
    const el=find(action,selectors);
    if (!el) throw Error(`未找到 ChatGPT ${action} 听写按钮。请检查专用页已登录、使用普通聊天，并在面板查看诊断。`);
    el.scrollIntoView({block:'center',inline:'center'});
    const r=el.getBoundingClientRect();
    return {x:r.x+r.width/2,y:r.y+r.height/2,label:label(el)};
  }
  function click(action,selectors) {
    const el=find(action,selectors);
    if(!el)throw Error(`未找到 ${action} 听写按钮。`);
    if(/转录并发送|transcribe and send/i.test(label(el)))throw Error('拒绝点击会发送聊天消息的按钮。');
    el.click();
    return {label:label(el)};
  }
  function state(selectors) {
    const items=scan();
    return {text:text(),start:!!find('start',selectors,items),finish:!!find('finish',selectors,items),cancel:!!find('cancel',selectors,items),visibility:document.visibilityState,focus:document.hasFocus()};
  }
  const signature = st => JSON.stringify([st.text,st.start,st.finish,st.cancel]);

  // Event-driven waiting: resolve as soon as the page's dictation state changes,
  // instead of the service worker polling on a fixed interval. Page timers are
  // throttled in hidden tabs, so the caller also races its own short timeout.
  let observer=null,waiter=null,lastCheck=0,trailing=0;
  function settle(st) {
    const current=waiter;if(!current)return;
    waiter=null;clearTimeout(current.timeout);clearTimeout(trailing);trailing=0;
    observer?.disconnect();observer=null;
    current.resolve(st);
  }
  function check() {
    if(!waiter)return;
    lastCheck=performance.now();
    let st;
    try{st=state(waiter.selectors);}catch(e){settle({error:e.message});return;}
    if(signature(st)!==waiter.since)settle(st);
  }
  function onMutation() {
    // Cap work at one state scan per 40 ms; a trailing check catches the last burst.
    if(performance.now()-lastCheck>=40)check();
    else if(!trailing)trailing=setTimeout(()=>{trailing=0;check();},40);
  }
  function waitChange(since, selectors={}, maxMs=1000) {
    if(waiter)settle(state(waiter.selectors));
    return new Promise(resolve=>{
      waiter={since,selectors,resolve,timeout:setTimeout(()=>settle(state(selectors)),maxMs)};
      observer=new MutationObserver(onMutation);
      observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-label','data-testid','disabled','hidden','class','aria-hidden','data-state']});
      check();
    });
  }
  function inspect() {
    return {url:location.href,visibility:document.visibilityState,focus:document.hasFocus(),editorFound:!!editor(),buttons:buttons().map(el=>({label:label(el),testId:el.getAttribute('data-testid')}))};
  }
  function clear(expected) {
    const el=editor();
    if (!el || text()!==expected) return false;
    el.focus();
    if ('value' in el) {
      const proto=el.matches('textarea')?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto,'value').set.call(el,'');
      el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));
    } else {
      const sel=window.getSelection(); const range=document.createRange();range.selectNodeContents(el);sel.removeAllRanges();sel.addRange(range);
      document.execCommand('delete');
    }
    return text()?.trim()==='';
  }
  function dispose() { if(waiter)settle({disposed:true}); }
  globalThis.__backgroundDictationPage={build:BUILD,point,click,state,waitChange,inspect,clear,dispose};
})();
