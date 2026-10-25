/* DOM adapter for the ChatGPT web model picker observed 2026-10-24.
 * No API interception, conversation reading, or message sending.
 */
(() => {
  'use strict';
  const norm = s => String(s || '').normalize('NFKC').trim().toLowerCase().replace(/[\s_-]+/g,'');
  const labels = {
    none:['即时','Instant','无','None'], minimal:['极低','Minimal'], low:['轻度','低','Light','Low'],
    medium:['中','中等','Medium'], high:['高','High'],
    xhigh:['极高','Extra high','Extra-high','Very high','Xhigh'], max:['Max'], ultra:['Ultra']
  };
  const canonical = text => Object.keys(labels).find(k=>labels[k].some(v=>norm(v)===norm(text)));
  function visible(e) {
    if (!e || !e.isConnected || e.closest('[inert],[aria-hidden="true"],[data-active="false"]')) return false;
    const r = e.getBoundingClientRect();
    return r.width>0 && r.height>0 && getComputedStyle(e).visibility!=='hidden';
  }
  const all = (selector, root=document) => [...root.querySelectorAll(selector)].filter(visible);
  const unique = items => items.length===1 ? items[0] : null;
  const wait = ms => new Promise(r=>setTimeout(r,ms));
  function clickElement(e) {
    const rect=e.getBoundingClientRect();
    const opts={bubbles:true,cancelable:true,button:0,buttons:1,pointerId:1,pointerType:'mouse',isPrimary:true,clientX:rect.x+rect.width/2,clientY:rect.y+rect.height/2};
    e.dispatchEvent(new PointerEvent('pointerdown',opts));
    e.dispatchEvent(new PointerEvent('pointerup',{...opts,buttons:0}));
    e.dispatchEvent(new MouseEvent('click',{...opts,buttons:0}));
  }
  function trigger() {
    return unique(all('button[data-codex-intelligence-trigger="true"]')) ||
      unique(all('button[aria-label="选择 ChatGPT 模型"],button[aria-label="Choose ChatGPT model"],button[aria-label="Select ChatGPT model"]'));
  }
  function mode() {
    const selected = all('button[aria-pressed="true"],[role="tab"][aria-selected="true"],[role="radio"][aria-checked="true"]');
    const modes = selected.map(e=>norm(e.textContent)).map(s=>['工作','work'].includes(s)?'work':['聊天','chat'].includes(s)?'chat':null).filter(Boolean);
    if (new Set(modes).size===1) return modes[0];
    const editors=all('[contenteditable="true"],textarea');
    if (editors.some(e=>/chatgpt\s*work|使用.*工作/i.test((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')))) return 'work';
    if (editors.some(e=>/询问\s*ChatGPT|Ask\s*ChatGPT/i.test((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('data-placeholder')||'')))) return 'chat';
    // Existing ChatGPT Work conversations identify their composer navigation controls.
    const t=trigger();
    if(t && visible(document.querySelector('[aria-label="使用 ChatGPT Work"]'))) return 'work';
    return null; // Never guess a mode from the URL: both modes can use /c/…
  }
  let busy=false, lastInput=0, epoch=0, lastKey='', failures=0, retryAt=0;
  // No on-page widget: the page stays untouched, and every state goes to the
  // desktop app, which owns the single "自动检测并调整" switch.
  let report={mode:'—',state:'等待',detail:'正在连接本机程序'};
  function show(state,detail,m=mode(),extra) {
    report={mode:m==='chat'?'聊天':m==='work'?'工作':'未识别',state,detail,...extra};
  }
  for(const event of ['pointerdown','keydown','input']) document.addEventListener(event,e=>{
    if(e.isTrusted) {lastInput=Date.now();epoch++;}
  },true);
  function ownMenu(t) {
    return unique(all('[role="menu"]').filter(e=>e.getAttribute('aria-labelledby')===t.id));
  }
  function selectedModel(menu) {
    // The picker retains an inert model list in its simple view. Read selected state
    // there, but only click after making that list visible.
    const rows=[...menu.querySelectorAll('[role="menuitemradio"][aria-checked="true"]')];
    return rows.length===1?rows[0].textContent.trim():null;
  }
  function readEffort(menu) {
    const keyboard=unique(all('[data-reasoning-slider="true"]',menu));
    if(keyboard) {
      const ids=(keyboard.getAttribute('aria-describedby')||'').split(/\s+/);
      for(const id of ids) {
        const el=document.getElementById(id);
        if(el?.getAttribute('role')==='status') {
          const s=el.textContent.split(/[,，]/)[0].trim();
          if(canonical(s)) return canonical(s);
        }
      }
    }
    const checked=all('[role="menuitemradio"][aria-checked="true"]',menu);
    return checked.map(e=>canonical(e.textContent)).find(Boolean)||null;
  }
  async function enforce(preset, expectedMode) {
    const initialEpoch=epoch, url=location.href, initialFocus=document.activeElement;
    let changed=false, previous='';
    const t=trigger();
    if(!t || t.disabled || t.getAttribute('aria-disabled')==='true') throw Error('未找到可用的模型按钮，请等待页面加载');
    function guard() {
      if(epoch!==initialEpoch || document.hidden || location.href!==url || mode()!==expectedMode || !t.isConnected || !visible(t)) throw Error('页面或用户操作发生变化，本轮已取消');
    }
    async function step(fn) {guard();fn();await wait(220);guard();}
    let opened=false;
    async function getMenu() {
      guard();
      let menu=ownMenu(t);
      if(!menu) {await step(()=>clickElement(t));opened=true;menu=ownMenu(t);}
      if(!menu) throw Error('模型菜单未打开；网页结构可能已变化');
      return menu;
    }
    async function close() {
      // Only close a menu we opened, and never close after user takes over.
      if(opened && epoch===initialEpoch && location.href===url && t.isConnected) {
        const menu=ownMenu(t);
        if(menu) menu.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true}));
        await wait(100);
        if(initialFocus?.isConnected && initialFocus!==document.body) initialFocus.focus({preventScroll:true});
      }
    }
    try {
      let menu=await getMenu();
      let current=selectedModel(menu);
      if(!current) throw Error('无法读取当前模型；停止操作');
      const beforeEffort=readEffort(menu);
      previous=`${current} · ${labels[beforeEffort]?.[0]||'—'}`;
      if(norm(current)!==norm(preset.model)) {
        changed=true;
        const toggle=unique(all('[data-model-picker-view-toggle="true"]',menu));
        if(toggle) await step(()=>clickElement(toggle));
        menu=await getMenu();
        const target=unique(all('[role="menuitemradio"]',menu).filter(e=>norm(e.textContent)===norm(preset.model)));
        if(!target) throw Error(`此模式未提供模型 ${preset.model}`);
        if(target.getAttribute('aria-disabled')==='true' || target.hasAttribute('disabled') || target.querySelector('[data-icon="lock"]') || /locked|已锁定/.test(target.getAttribute('aria-label')||'')) throw Error('目标模型未解锁或不可用');
        await step(()=>clickElement(target));
        menu=await getMenu();
        current=selectedModel(menu);
        if(norm(current)!==norm(preset.model)) throw Error('模型变更未确认，可能受套餐或使用限额限制');
      }
      if(readEffort(menu)!==preset.effort) {
        changed=true;
        // If the model list remains open, toggle back into the simple slider view.
        if(!unique(all('[data-reasoning-slider="true"]',menu))) {
          const toggle=unique(all('[data-model-picker-view-toggle="true"]',menu));
          if(toggle) await step(()=>clickElement(toggle));
          menu=await getMenu();
        }
        const keyboard=unique(all('[data-reasoning-slider="true"]',menu));
        const slider=menu.querySelector('[role="slider"]');
        if(!keyboard || !slider) throw Error('未找到思考强度滑块；网页结构可能已变化');
        const min=Number(slider.getAttribute('aria-valuemin')), max=Number(slider.getAttribute('aria-valuemax'));
        const original=Number(slider.getAttribute('aria-valuenow'));
        if(!Number.isFinite(min)||!Number.isFinite(max)||!Number.isFinite(original)||max-min>12) throw Error('无法读取强度范围');
        async function key(name) {
          await step(()=>{keyboard.focus({preventScroll:true});keyboard.dispatchEvent(new KeyboardEvent('keydown',{key:name,code:name,bubbles:true,cancelable:true}));});
        }
        let found=false;
        // Use the announced label, not the internal effort code: Chat's max can
        // display Extra high while Work uses xhigh for the same visible label.
        for(let i=0;i<=max-min;i++) await key('ArrowLeft');
        for(let i=min;i<=max;i++) {
          menu=await getMenu();
          if(readEffort(menu)===preset.effort) {found=true;break;}
          if(i<max) await key('ArrowRight');
        }
        if(!found) {
          for(let i=0;i<=max-min;i++) await key('ArrowLeft');
          for(let i=min;i<original;i++) await key('ArrowRight');
          throw Error(`目标模型不支持 ${labels[preset.effort]?.join(' / ')||preset.effort}，已恢复原强度`);
        }
      }
      menu=await getMenu();
      if(norm(selectedModel(menu))!==norm(preset.model)||readEffort(menu)!==preset.effort) throw Error('设置未通过选中状态复核');
      return {text:`${preset.model} · ${labels[preset.effort][0]}`,changed,previous};
    } finally {await close();}
  }
  let confirmed=null, lastAudit=0;
  async function tick() {
    if(busy || document.hidden) return;
    busy=true;
    try {
      let response;
      try {response=await chrome.runtime.sendMessage({type:'sync',report});}
      catch {show('连接失败','请安装本机 EXE，并在扩展更新后刷新网页');return;}
      if(response?.error || !response?.config) {show('未连接',response?.error||'本机程序未响应');return;}
      const cfg=response.config, m=mode();
      const k=location.href+'|'+m+'|'+JSON.stringify(cfg);
      if(k!==lastKey) {lastKey=k;failures=0;retryAt=0;confirmed=null;}
      if(!cfg.enabled) {show('已暂停','设置程序已关闭“自动检测并调整”',m);return;}
      if(m && !cfg[m]?.enabled) {show('已暂停',`设置程序已关闭“应用${m==='chat'?'聊天':'工作'}预设”`,m);return;}
      if(!m) {show('等待','无法确认聊天 / 工作模式；为避免误改暂不操作');return;}
      if(failures>=3) {show('需要检查','连续三次失败，已停止重试。点击两次状态提示，或用扩展按钮重新检测',m);return;}
      if(Date.now()<retryAt || Date.now()-lastInput<1800) return;
      if(all('[data-testid="stop-button"],button[aria-label="停止生成"],button[aria-label="Stop generating"]').length) {show('等待','回复生成中，结束后调整',m);return;}
      if(all('[role="menu"],[role="dialog"]').length) return;
      const t=trigger();
      if(!t) {show('等待','未找到模型选择器，请确认已登录且页面已加载',m);return;}
      const stamp=t.getAttribute('data-selected-reasoning-effort')+'|'+t.textContent;
      // Audit hidden model selection once a minute; any visible change, navigation,
      // preset change or fresh trigger forces an immediate check.
      if(confirmed?.node===t && confirmed.stamp===stamp && Date.now()-lastAudit<60000) return;
      const result=await enforce(cfg[m],m);
      confirmed={node:trigger(),stamp:trigger()?.getAttribute('data-selected-reasoning-effort')+'|'+trigger()?.textContent};
      lastAudit=Date.now();failures=0;
      show('已确认',result.text,m,result.changed?{changed:true,previous:result.previous,applied:result.text}:undefined);
    } catch(e) {
      if(/本轮已取消/.test(e.message)) {confirmed=null;retryAt=Date.now()+3000;show('等待','被你的操作或页面切换打断，3 秒后自动重试');}
      else {failures++;retryAt=Date.now()+30000;show('无法调整',`${e.message} · 第 ${failures}/3 次失败，30 秒后重试`);}
    } finally {busy=false;}
  }
  chrome.runtime.onMessage.addListener((m,s,reply)=>{
    if(m.type==='retry') {failures=0;retryAt=0;confirmed=null;lastInput=0;reply({ok:true});void tick();}
  });
  show('等待','正在连接本机程序');
  setInterval(()=>void tick(),3000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden) void tick();});
  void tick();
})();
