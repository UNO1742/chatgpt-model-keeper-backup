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
  // Latest model / effort lists read from the page, with the mode they belong
  // to. Sticky across states so the card can copy the page even while a retry
  // is pending.
  let pageLists={models:[],efforts:[],forModel:'',mode:null};
  function show(state,detail,m=mode(),extra) {
    const keep=pageLists.mode===m?{models:pageLists.models,efforts:pageLists.efforts,forModel:pageLists.forModel}:{};
    report={mode:m==='chat'?'聊天':m==='work'?'工作':'未识别',state,detail,...keep,...extra};
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
  // Pro / Ultra stay out of the presets even when the page offers them: they are
  // the expensive tiers this tool is meant to keep the user away from.
  const blockedModel = name => /(?:^|[^a-z0-9])(pro|ultra)(?:[^a-z0-9]|$)/i.test(String(name||''));
  function harvestModels(menu) {
    // The picker keeps its full list in the DOM even while the simple slider
    // view is showing, so this needs no extra clicking.
    const names=[];
    for(const row of menu.querySelectorAll('[role="menuitemradio"]')) {
      if(row.getAttribute('aria-disabled')==='true' || row.hasAttribute('disabled')) continue;
      if(row.querySelector('[data-icon="lock"]') || /locked|已锁定/i.test(row.getAttribute('aria-label')||'')) continue;
      const name=String(row.textContent||'').replace(/\s+/g,' ').trim();
      if(!name || name.length>60 || blockedModel(name) || names.includes(name)) continue;
      names.push(name);
    }
    return names.slice(0,16);
  }
  // The levels a model really supports, in slider order. Read straight from the
  // tick labels when they carry text; otherwise sweep the real slider once and
  // keep the answer on disk, so every later adjustment is a single move instead
  // of another sweep the user has to watch.
  const effortCache=new Map();
  let storedEfforts={},triedEfforts={},storeReady=null;
  function readyStore() {
    if(!storeReady) storeReady=(async()=>{
      try {
        const got=await chrome.storage.local.get(['efforts','effortTried']);
        storedEfforts=(got&&got.efforts)||{};
        triedEfforts=(got&&got.effortTried)||{};
      } catch {}
      return storedEfforts;
    })();
    return storeReady;
  }
  function rememberEfforts(key,list) {
    effortCache.set(key,list);
    if((storedEfforts[key]||[]).join('|')===list.join('|')) return;
    storedEfforts={...storedEfforts,[key]:list};
    try {chrome.storage.local.set({efforts:storedEfforts});} catch {}
  }
  // Marks that the ladder of this model has already been walked once. The walk
  // is the only way to see levels the page does not print, so it is allowed
  // exactly once per model instead of on every single correction.
  function markTried(key) {
    if(triedEfforts[key]) return;
    triedEfforts={...triedEfforts,[key]:1};
    try {chrome.storage.local.set({effortTried:triedEfforts});} catch {}
  }
  // Some builds print the level names under the slider. Reading those costs no
  // movement at all, so it is always tried before the slider is touched.
  function tickEfforts(menu) {
    const fromTicks=[...new Set([...menu.querySelectorAll('[class*="Tick-"]')]
      .map(e=>canonical(String(e.textContent||'').trim())).filter(Boolean))];
    return fromTicks.length>1?fromTicks:null;
  }
  async function enforce(preset, expectedMode) {
    const initialEpoch=epoch, url=location.href, initialFocus=document.activeElement;
    let previous='';
    const t=trigger();
    if(!t || t.disabled || t.getAttribute('aria-disabled')==='true') throw Error('未找到可用的模型按钮，请等待页面加载');
    function guard() {
      if(epoch!==initialEpoch || document.hidden || location.href!==url || mode()!==expectedMode || !t.isConnected || !visible(t)) throw Error('页面或用户操作发生变化，本轮已取消');
    }
    async function step(fn,ms=220) {guard();fn();await wait(ms);guard();}
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
      const beforeModel=selectedModel(menu);
      if(!beforeModel) throw Error('无法读取当前模型；停止操作');
      const beforeEffort=readEffort(menu);
      previous=`${beforeModel} · ${labels[beforeEffort]?.[0]||'—'}`;
      // Decide "was this a correction?" from the page as the user left it. A
      // learning sweep below moves the slider around, and that must never turn
      // into a bubble about something the user did not do.
      const changed=norm(beforeModel)!==norm(preset.model) || beforeEffort!==preset.effort;
      let current=beforeModel, models=harvestModels(menu);
      if(norm(current)!==norm(preset.model)) {
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
        models=harvestModels(menu)||models;
      }
      // The simple view holds the reasoning slider; the model list view does not.
      if(!unique(all('[data-reasoning-slider="true"]',menu))) {
        const toggle=unique(all('[data-model-picker-view-toggle="true"]',menu));
        if(toggle) await step(()=>clickElement(toggle));
        menu=await getMenu();
      }
      // The levels of the model we ended up on. A different model can offer a
      // shorter slider, so this is read after the switch, not before.
      const key=`${expectedMode}|${current}`;
      await readyStore();
      const stops=()=>{
        const s=menu.querySelector('[role="slider"]');
        const min=Number(s?.getAttribute('aria-valuemin')),max=Number(s?.getAttribute('aria-valuemax'));
        return Number.isFinite(min)&&Number.isFinite(max)&&max>min?[min,max]:[NaN,NaN];
      };
      // A remembered list is only trusted while the slider still has the same
      // number of stops and the stop we are standing on still says the same
      // thing. Reading it moves nothing.
      const knownList=()=>{
        const [min,max]=stops();
        if(!Number.isFinite(min)) return null;
        const ticks=tickEfforts(menu);
        if(ticks&&ticks.length===max-min+1) {rememberEfforts(key,ticks);return ticks;}
        const list=storedEfforts[key];
        if(!list) return null;
        if(list.length!==max-min+1) return null;
        const at=Number(menu.querySelector('[role="slider"]')?.getAttribute('aria-valuenow')),here=readEffort(menu);
        if(here&&Number.isFinite(at)&&list[at-min]!==here) return null;
        return list;
      };
      // What this page really offers, kept module-level so a failure below still
      // reaches the card and stops it from offering an impossible level again.
      pageLists={models,efforts:knownList()||[],forModel:current,mode:expectedMode};
      if(readEffort(menu)!==preset.effort) {
        const [min,max]=stops();
        if(!unique(all('[data-reasoning-slider="true"]',menu)) || !Number.isFinite(min) || max-min>12) throw Error('未找到思考强度滑块；网页结构可能已变化');
        async function press(name,ms=130) {
          await step(()=>{
            const keyboard=unique(all('[data-reasoning-slider="true"]',menu));
            if(!keyboard) throw Error('思考强度滑块已关闭');
            keyboard.focus({preventScroll:true});
            keyboard.dispatchEvent(new KeyboardEvent('keydown',{key:name,code:name,bubbles:true,cancelable:true}));
          },ms);
          menu=await getMenu();
        }
        const value=()=>Number(menu.querySelector('[role="slider"]')?.getAttribute('aria-valuenow'));
        const order=Object.keys(labels), rank=id=>order.indexOf(String(id||''));
        const startAt=value(), startHere=readEffort(menu), count=max-min+1;
        let found=false, ladder=null;
        if(!knownList() && !triedEfforts[key]) {
          // First time this model's slider is seen and the page does not print
          // its level names, so the ladder has to be walked once - there is no
          // other way to see the stops. Start with the nearer end, cross the
          // whole slider in one direction reading every stop, then come to the
          // target from that end. One change of direction at most, once ever.
          markTried(key);
          const down=startAt-min<=max-startAt;
          const first=down?'ArrowLeft':'ArrowRight', last=down?'ArrowRight':'ArrowLeft';
          const side=[startHere];
          for(let i=0;i<count;i++) {
            if(down?value()<=min:value()>=max) break;
            await press(first,90);
            const id=readEffort(menu);
            if(id&&!side.includes(id)) side.push(id);
          }
          const across=[];
          for(let i=0;i<count;i++) {
            if(down?value()>=max:value()<=min) break;
            await press(last,90);
            const id=readEffort(menu);
            if(id&&!across.includes(id)) across.push(id);
          }
          // side runs away from the far end; across runs away from the near one,
          // so a level on both sides of the turning point shows up twice.
          const asc=[];
          for(const id of (down?[...side].reverse().concat(across):[...across].reverse().concat(side))) if(!asc.includes(id)) asc.push(id);
          if(asc.length===count) ladder=asc;
          // We are on the far end now: step to the target, still one direction.
          const back=last==='ArrowRight'?'ArrowLeft':'ArrowRight';
          if(!ladder||ladder.includes(preset.effort)) {
            for(let i=0;i<count;i++) {
              if(readEffort(menu)===preset.effort) break;
              if(back==='ArrowRight'?value()>=max:value()<=min) break;
              await press(back,100);
            }
          }
          found=readEffort(menu)===preset.effort;
        } else {
          // Levels run in a fixed order, so the direction is known without
          // knowing the exact list: walk one stop at a time and stop there.
          const dir=rank(preset.effort)>rank(startHere)?'ArrowRight':'ArrowLeft';
          const back=dir==='ArrowRight'?'ArrowLeft':'ArrowRight';
          for(let i=0;i<count&&!found;i++) {
            if(dir==='ArrowRight'?value()>=max:value()<=min) break;
            await press(dir);
            if(readEffort(menu)===preset.effort) found=true;
          }
          if(!found) {
            // Either this model lacks the level or the page orders its stops the
            // other way round. Crossing once settles both and, if the page does
            // print its names, hands back the real list.
            for(let i=0;i<count&&!found;i++) {
              if(back==='ArrowRight'?value()>=max:value()<=min) break;
              await press(back);
              if(readEffort(menu)===preset.effort) found=true;
            }
          }
        }
        if(ladder) {rememberEfforts(key,ladder);pageLists={...pageLists,efforts:ladder};}
        if(!found) {
          // Put the slider back where the user left it, one direction, and say
          // what this model actually offers.
          for(let i=0;i<count;i++) {
            const at=value();
            if(!Number.isFinite(at)||at===startAt) break;
            await press(at>startAt?'ArrowLeft':'ArrowRight');
          }
          const list=ladder||knownList()||[];
          const only=list.map(id=>labels[id]?.[0]||id).join(' / ');
          throw Error(`目标模型只支持 ${only||'其他强度'}，已恢复原强度`);
        }
      }
      menu=await getMenu();
      if(norm(selectedModel(menu))!==norm(preset.model)||readEffort(menu)!==preset.effort) throw Error('设置未通过选中状态复核');
      // The full list is only visible in the model view, so refresh it from
      // whichever view is on screen now.
      const names=harvestModels(menu);
      if(names.length) {models=names;pageLists={...pageLists,models:names};}
      return {text:`${preset.model} · ${labels[preset.effort][0]}`,changed,previous};
    } finally {await close();}
  }
  let confirmed=null, lastAudit=0, corrections=0;
  // Corrections are rare: push one immediately instead of waiting for the next
  // 3 s poll, otherwise the bubble shows up noticeably late.
  async function flush() {try {await chrome.runtime.sendMessage({type:'sync',report});} catch {}}
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
      show('已确认',result.text,m,result.changed?{changed:true,previous:result.previous,applied:result.text,seq:++corrections}:undefined);
      if(result.changed) void flush();
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
