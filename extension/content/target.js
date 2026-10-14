(() => {
  const BUILD='editing-2';
  if (globalThis.__backgroundDictationTarget?.build===BUILD) return;
  globalThis.__backgroundDictationTarget?.dispose?.();
  const snapshots = new Map();
  let statusNode,statusTimer;
  // Fallback progress bubble; background.js only uses it when the desktop panel is unavailable.
  function status(text, error = false, ttl = 0) {
    if (!statusNode?.isConnected) {
      statusNode = document.createElement('div');
      statusNode.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483647;padding:12px 18px;border-radius:10px;background:#132b28;color:white;font:14px system-ui;box-shadow:0 3px 20px #0003;pointer-events:none;max-width:420px;white-space:pre-wrap';
      document.documentElement.append(statusNode);
    }
    statusNode.textContent = text;
    statusNode.style.background = error ? '#8b2424' : '#132b28';
    clearTimeout(statusTimer);
    if (ttl) statusTimer = setTimeout(() => statusNode?.remove(), ttl);
  }
  function active() {
    let el = document.activeElement;
    while (el?.shadowRoot?.activeElement) el = el.shadowRoot.activeElement;
    return el;
  }
  function focused() {
    return document.hasFocus() && !active()?.matches('iframe,frame');
  }
  function capture(token) {
    if (!focused()) throw Error('输入焦点已改变，请重新点击目标输入框。');
    const el = active();
    if (!el || el.disabled || el.readOnly) throw Error('请先点击一个可以编辑的输入框。');
    if (el.matches('input,textarea')) {
      if (el.matches('input') && !['text','search','url','tel','email',''].includes(el.type)) throw Error('此输入框类型不支持听写。');
      if (typeof el.selectionStart !== 'number') throw Error('此输入框不支持光标定位；请使用文本框或多行输入框。');
      snapshots.set(token, {el, kind:'value', original:el.value, start:el.selectionStart, end:el.selectionEnd});
    } else {
      const editor = el.closest('[contenteditable="true"],[contenteditable=""],[contenteditable="plaintext-only"]');
      const sel = window.getSelection();
      if (!editor || !sel?.rangeCount || !editor.contains(sel.anchorNode) || !editor.contains(sel.focusNode)) throw Error('目前支持文本框和常规可编辑区域。');
      snapshots.set(token, {el:editor, kind:'editable', original:editor.textContent, range:sel.getRangeAt(0).cloneRange()});
    }
    return {ok:true};
  }
  function insert(token, text) {
    const s = snapshots.get(token);
    if (!s || !s.el.isConnected) throw Error('原输入框已关闭，请从扩展面板复制结果。');
    if (!focused()) throw Error('输入焦点已改变，文字已保留在扩展面板。');
    const current = active();
    if (current !== s.el && !s.el.contains(current)) throw Error('输入焦点已改变，文字已保留在扩展面板。');
    if (s.kind === 'value') {
      if (s.el.value !== s.original || s.el.selectionStart !== s.start || s.el.selectionEnd !== s.end) throw Error('输入内容或光标已改变，文字已保留在扩展面板。');
      const next = s.original.slice(0,s.start) + text + s.original.slice(s.end);
      if (s.el.maxLength >= 0 && next.length > s.el.maxLength) throw Error('转写结果超过输入框长度限制，请从扩展面板复制。');
      // Honor application cancellation once, before any native or fallback mutation.
      if (!s.el.dispatchEvent(new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data:text}))) throw Error('网页阻止了插入，请从扩展面板复制。');
      if (s.el.value !== s.original || s.el.selectionStart !== s.start || s.el.selectionEnd !== s.end) throw Error('网页处理插入时改变了内容或光标，文字已保留在扩展面板。');
      s.el.focus();
      let inputSeen=false;
      const observed=()=>{inputSeen=true;};
      s.el.addEventListener('input',observed);
      try { document.execCommand('insertText',false,text); }
      catch {} // Unsupported browser/editor: use the guarded setter fallback below.
      finally { s.el.removeEventListener('input',observed); }
      if (s.el.value === next) {
        // Native editing normally emits input and keeps the browser's undo history.
        if (!inputSeen) s.el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
      } else {
        // Do not overwrite partial native edits or an application's synchronous rewrite.
        if (s.el.value !== s.original || inputSeen) throw Error('网页改变了插入结果，文字已保留在扩展面板。');
        const proto = s.el.matches('textarea') ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto,'value').set.call(s.el,next);
        s.el.setSelectionRange(s.start+text.length,s.start+text.length);
        s.el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));
      }
    } else {
      if (s.el.textContent !== s.original) throw Error('编辑器内容已改变，文字已保留在扩展面板。');
      const sel = window.getSelection();
      if (!sel?.rangeCount) throw Error('编辑器选区已失效。');
      const now = sel.getRangeAt(0);
      if (now.compareBoundaryPoints(Range.START_TO_START,s.range) || now.compareBoundaryPoints(Range.END_TO_END,s.range)) throw Error('编辑器光标已改变，文字已保留在扩展面板。');
      if (!document.execCommand('insertText',false,text)) throw Error('编辑器不支持自动插入，请从扩展面板复制。');
    }
    snapshots.delete(token);
    return {ok:true};
  }
  const onKeyDown=event=>{
    if(event.key==='Escape' && event.isTrusted && snapshots.size){
      event.preventDefault();
      chrome.runtime.sendMessage({type:'cancel-target',token:[...snapshots.keys()].at(-1)}).catch(()=>{});
    }
  };
  document.addEventListener('keydown',onKeyDown,true);
  function dispose(){document.removeEventListener('keydown',onKeyDown,true);clearTimeout(statusTimer);statusNode?.remove();snapshots.clear();}
  globalThis.__backgroundDictationTarget = {build:BUILD,focused,capture,insert,status,dispose,forget:token=>snapshots.delete(token)};
})();
