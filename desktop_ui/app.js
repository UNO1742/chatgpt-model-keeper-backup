import * as originalSlider from './original_component.js';
const view=new URLSearchParams(location.search).get('view')||'settings';
const isOrb=view==='orb',isPanel=view==='settings',isToast=view==='toast';
const $=s=>document.querySelector(s);
$('#orb').hidden=!isOrb;$('#card').hidden=!isPanel;$('#toast').hidden=!isToast;
const sliderInstances={},sliderLoads={},mountedStops={};
let bridge,release=null,models={chat:[],work:[]},efforts={chat:[],work:[]},orbLoading=false;
function notice(s){if(isPanel)$('#status').textContent=s;}
function request(action,data){bridge.request(JSON.stringify({action,data}));}
function setTheme(theme){document.documentElement.dataset.theme=theme;for(const t of ['light','dark'])$('#theme-'+t).setAttribute('aria-pressed',String(t===theme));}
// Extension row keeps a placeholder action button. Wiring the real install flow is
// reserved for a later release; installed state only flips the label to "卸载".
let extensionInstalled=false;
function renderExtensionAction(){const button=$('#extension-action');if(!button)return;const label=extensionInstalled?'卸载':'安装';button.textContent=label;button.dataset.state=extensionInstalled?'installed':'idle';button.setAttribute('aria-label',label+'浏览器扩展');}
function setExtensionInstalled(value){extensionInstalled=!!value;renderExtensionAction();}
window.setExtensionInstalled=setExtensionInstalled;
function closeMenus(){for(const mode of ['chat','work']){$('#'+mode+'-model-menu').hidden=true;$('#'+mode+'-model').setAttribute('aria-expanded','false');}}
function selectedModel(mode,value){const trigger=$('#'+mode+'-model');trigger.value=value;$('#'+mode+'-model-value').textContent=value;for(const option of $('#'+mode+'-model-menu').children){const selected=option.value===value;option.setAttribute('aria-selected',String(selected));option.querySelector('.check').textContent=selected?'✓':'';}}
function buildModels(mode,value){const menu=$('#'+mode+'-model-menu');const entries=[...models[mode]];if(value&&!entries.includes(value))entries.unshift(value);menu.replaceChildren(...entries.map(name=>{const option=document.createElement('button');option.type='button';option.className='model-option no-drag itemBase-Uk8vyp rounded-xl text-default group itemInteractive-A3p9wI flex flex-col';option.setAttribute('role','option');option.value=name;option.tabIndex=-1;const row=document.createElement('div');row.dataset.menuRowContent='true';row.className='flex w-full min-w-0 items-center gap-1.5';const label=document.createElement('span');label.className='flex-1 min-w-0 truncate';label.textContent=name;const check=document.createElement('span');check.className='check';check.setAttribute('aria-hidden','true');row.append(label,check);option.append(row);option.onclick=()=>{selectedModel(mode,name);closeMenus();$('#'+mode+'-model').focus();};return option;}));selectedModel(mode,value);}
function openMenu(mode,keyboard=false){const trigger=$('#'+mode+'-model'),menu=$('#'+mode+'-model-menu');const wasOpen=!menu.hidden;closeMenus();if(wasOpen)return;trigger.setAttribute('aria-expanded','true');menu.hidden=false;if(keyboard)(menu.querySelector('[aria-selected=true]')||menu.firstElementChild)?.focus();}
const EFFORT_ORDER=['none','low','medium','high','xhigh','max','ultra'];
// When the page does not offer the saved level, show the closest one it does
// offer instead of jumping to the top of the range.
function nearestEffort(items,value){const want=EFFORT_ORDER.indexOf(value);if(want<0)return items.length-1;let best=items.length-1,gap=Infinity;items.forEach((item,index)=>{const offset=Math.abs(EFFORT_ORDER.indexOf(item[0])-want);if(offset<gap){gap=offset;best=index;}});return best;}
function renderEffort(mode,value){const slider=$('#'+mode+'-effort'),items=efforts[mode];if(!items.length)return;const index=nearestEffort(items,value);const [id,label]=items[index];slider.dataset.effort=id;slider.setAttribute('aria-valuemin','0');slider.setAttribute('aria-valuemax',String(items.length-1));slider.setAttribute('aria-valuenow',String(index));slider.setAttribute('aria-valuetext',label);$('#'+mode+'-rail-labels').querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));}
async function selectEffort(mode,value){renderEffort(mode,value);const instance=sliderInstances[mode]||await sliderLoads[mode];if(instance)instance.select(value);}
function buildEfforts(mode,value){const items=efforts[mode],slider=$('#'+mode+'-effort');$('#'+mode+'-rail-labels').replaceChildren(...items.map(([id,label])=>{const button=document.createElement('button');button.textContent=label.split(' / ')[0];button.title=label;button.onclick=()=>{selectEffort(mode,id);slider.focus();};return button;}));renderEffort(mode,value);const stops=items.map(item=>item[0]).join(',');
  // The page can report a shorter range than the built-in one, so the mounted
  // slider is only reused when it has the same number of stops.
  if(sliderInstances[mode]&&mountedStops[mode]===stops){sliderInstances[mode].select(slider.dataset.effort);return;}
  if(sliderInstances[mode]){try{sliderInstances[mode].dispose();}catch{}delete sliderInstances[mode];delete sliderLoads[mode];}
  mountedStops[mode]=stops;
  sliderLoads[mode]=originalSlider.mount(slider,{options:items,selected:slider.dataset.effort,onChange:id=>renderEffort(mode,id)}).then(instance=>{sliderInstances[mode]=instance;instance.select(slider.dataset.effort);return instance;}).catch(error=>{notice('原始滑条加载失败：'+error.message);throw error;});}
let listsKey='',baseModels={chat:[],work:[]},baseEfforts={chat:[],work:[]},pageLists={},effortLabels={},currentConfig=null;
function learnLabels(source){for(const mode of ['chat','work'])for(const pair of (source?.[mode]||[]))effortLabels[pair[0]]=pair;}
// The card copies the page: when the extension reported the real model list and
// thinking levels, those win over the built-in fallback. Levels are only taken
// over for the model they were measured on.
function resolveLists(config){
  const result={models:{chat:[],work:[]},efforts:{chat:[],work:[]}};
  for(const mode of ['chat','work']){
    const page=pageLists[mode],chosen=config?.[mode]?.model||'';
    const names=page?.models?.length?page.models.slice():baseModels[mode].slice();
    let stops=page?.efforts?.length&&(!page.model||page.model===chosen)?page.efforts.slice():baseEfforts[mode].map(item=>item[0]);
    stops=stops.filter(id=>effortLabels[id]);
    if(stops.length<2)stops=baseEfforts[mode].map(item=>item[0]);
    result.models[mode]=names;result.efforts[mode]=stops.map(id=>effortLabels[id]);
  }
  return result;
}
function renderLists(){
  const lists=resolveLists(currentConfig);
  listsKey=JSON.stringify([lists,currentConfig?.chat?.model,currentConfig?.work?.model]);
  models=lists.models;efforts=lists.efforts;
  for(const mode of ['chat','work']){const p=currentConfig?.[mode];if(!p)continue;$('#'+mode+'-enabled').checked=p.enabled;buildModels(mode,p.model);buildEfforts(mode,p.effort);}
}
function applyLists(lists){
  pageLists=lists||{};
  if(!currentConfig)return;
  const next=resolveLists(currentConfig);
  const key=JSON.stringify([next,currentConfig.chat.model,currentConfig.work.model]);
  if(key===listsKey)return;
  renderLists();
}
function fill(data){
  // Reopening the card must not rebuild identical model lists or remount the
  // slider: that is what made the panel blink once on every open. Structural
  // rebuild happens only when the lists or the selected model really change;
  // plain values are re-applied silently (no visual change when already equal).
  setTheme(data.theme||'dark');
  $('#version').textContent='v'+data.version;$('#enabled').checked=data.config.enabled;$('#startup').checked=data.startup;
  currentConfig=data.config;
  if(data.models)baseModels=data.models;
  if(data.efforts)baseEfforts=data.efforts;
  if(data.lists)pageLists=data.lists;
  learnLabels(baseEfforts);
  const lists=resolveLists(currentConfig);
  const key=JSON.stringify([data.version,lists,data.config.chat.model,data.config.work.model]);
  if(key!==listsKey){
    listsKey=key;models=lists.models;efforts=lists.efforts;
    for(const mode of ['chat','work']){const p=data.config[mode];$('#'+mode+'-enabled').checked=p.enabled;buildModels(mode,p.model);buildEfforts(mode,p.effort);}
    return;
  }
  for(const mode of ['chat','work']){
    const p=data.config[mode];
    $('#'+mode+'-enabled').checked=p.enabled;
    if($('#'+mode+'-model').value!==p.model)selectedModel(mode,p.model);
    // Re-selecting the same effort replays the slider animation: that is the
    // flicker on reopen, so only touch it when the saved value really differs.
    if($('#'+mode+'-effort').dataset.effort!==p.effort)void selectEffort(mode,p.effort);
  }
}
window.chooseMode=mode=>{closeMenus();$('.segments').classList.toggle('work',mode==='work');document.querySelectorAll('[data-mode]').forEach(b=>{const yes=b.dataset.mode===mode;b.classList.toggle('selected',yes);b.setAttribute('aria-selected',String(yes));});document.querySelectorAll('[data-pane]').forEach(p=>{const yes=p.dataset.pane===mode;p.classList.toggle('active',yes);p.inert=!yes;});};
async function startOrb(){
  if(orbLoading||window.orbController)return;orbLoading=true;
  const {__webpack_modules__}=await import('../runtime/horizon.mjs');
  const blue=[0x35/255,0x66/255,0xf0/255];
  const palette={accentColor:[...blue,1],fallbackColors:['#2854e2','#9ab5f8','#e7efff']};
  const exports={};function require(name){if(name==='IlRO')return {b:()=>palette};throw Error('Unexpected rendering dependency');}
  require.d=(target,map)=>{for(const [name,get]of Object.entries(map))Object.defineProperty(target,name,{get});};
  require.p=new URL('../runtime/',location.href).href;
  __webpack_modules__.HNEj({},exports,require);
  let draws=0;const canvas=$('#voice');
  if(!canvas.getContext('webgl2',{premultipliedAlpha:true}))throw Error('需要支持 WebGL 2 的显卡驱动');
  const controller=await exports.HorizonVoiceOrbController.create(canvas,{displayScale:.98,presentation:'overlay',onDraw:()=>{draws++;window.orbDraws=draws;},onRenderError:()=>request('orbError','原始 WebGL 渲染器无法启动，请检查显卡驱动。')});
  if(!controller)throw Error('网页原始渲染器初始化失败');
  if(document.querySelectorAll('#orb canvas').length!==1){controller.dispose();throw Error('原始 WebGL 渲染失败，已停止简化替代效果');}
  controller.setAudioLevels(null);
  controller.setInputs({paletteIndex:0,phase:'active',previewAudioLevel:0,voiceActivity:'idle'});
  window.orbController=controller;window.addEventListener('pagehide',()=>controller.dispose());
  window.orbKind='HorizonVoiceOrbController/live';
}
// Motion lives in the page: Qt only shows the window and says where the orb is.
// transform-origin is the orb centre mapped into card coordinates, so the card
// grows out of the ball whichever side it was placed on.
let panelAnim=null,panelDir={x:0,y:-1},toastAnim=null,toastTimer=0,toastHover=false;
function panelEnter(m){
  const card=$('#card'),origin=m.origin||{x:168,y:313},dir=m.dir||{x:0,y:-1};
  panelDir=dir;
  card.style.transformOrigin=origin.x+'px '+origin.y+'px';
  card.classList.add('on');
  if(panelAnim)panelAnim.cancel();
  const dx=(-dir.x*16).toFixed(1),dy=(-dir.y*16).toFixed(1);
  panelAnim=card.animate([{opacity:0,transform:`translate(${dx}px,${dy}px) scale(.9)`},{opacity:1,transform:'none'}],{duration:220,easing:'cubic-bezier(.22,1,.36,1)',fill:'both'});
  panelAnim.onfinish=()=>{card.style.opacity='1';card.style.transform='none';panelAnim=null;};
  // Safety net: if the frame clock is throttled the card would stay at opacity
  // 0, i.e. an open window with nothing in it. Force the settled state.
  setTimeout(()=>{if(card.style.opacity!=='1'){if(panelAnim)panelAnim.cancel();panelAnim=null;card.style.opacity='1';card.style.transform='none';}},450);
}
function panelExit(){
  const card=$('#card'),dir=panelDir;
  if(panelAnim)panelAnim.cancel();
  const dx=(-dir.x*10).toFixed(1),dy=(-dir.y*10).toFixed(1);
  panelAnim=card.animate([{opacity:1,transform:'none'},{opacity:0,transform:`translate(${dx}px,${dy}px) scale(.96)`}],{duration:150,easing:'cubic-bezier(.4,0,1,1)',fill:'both'});
  panelAnim.onfinish=()=>{panelAnim=null;card.classList.remove('on');card.style.opacity='';card.style.transform='';request('panelHidden');};
}
function showToast(m){
  const root=$('#toast'),bubble=root.querySelector('.bubble');
  if(m.theme)setTheme(m.theme);
  root.classList.toggle('up',!!m.above);
  root.style.setProperty('--tail',(m.tail||156)+'px');
  $('#toast-model').textContent=m.model||'目标模型';
  const previous=(m.previous||'').trim();
  $('#toast-sub-lead').hidden=!previous;
  $('#toast-previous').hidden=!previous;
  $('#toast-previous').textContent=previous;
  $('#toast-sub-tail').textContent=previous?'':'网页的模型与预设不一致，已自动恢复';
  if(toastAnim)toastAnim.cancel();
  clearTimeout(toastTimer);
  // Grow out of the tail, which always points at the ball.
  bubble.style.transformOrigin=(m.tail||156)+'px '+(m.above?'100%':'0');
  const from=m.above?-12:12;
  root.classList.remove('in');void root.offsetWidth;root.classList.add('in');
  toastAnim=bubble.animate([{opacity:0,transform:`translateY(${from}px) scale(.94)`},{opacity:1,offset:.55},{opacity:1,transform:'none'}],{duration:460,easing:'cubic-bezier(.16,1,.3,1)',fill:'both'});
  toastAnim.onfinish=()=>{bubble.style.opacity='1';bubble.style.transform='none';};
  setTimeout(()=>{if(bubble.style.opacity!=='1'){if(toastAnim)toastAnim.cancel();bubble.style.opacity='1';bubble.style.transform='none';}},600);
  scheduleToastHide();
}
function scheduleToastHide(){clearTimeout(toastTimer);if(toastHover)return;toastTimer=setTimeout(hideToast,5200);}
function hideToast(){
  const bubble=$('#toast .bubble');
  if(toastAnim)toastAnim.cancel();
  $('#toast').classList.remove('in');
  toastAnim=bubble.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(6px) scale(.982)'}],{duration:240,easing:'ease',fill:'both'});
  toastAnim.onfinish=()=>{toastAnim=null;bubble.style.opacity='';bubble.style.transform='';request('toastDone');};
}
new QWebChannel(qt.webChannelTransport,channel=>{
  bridge=channel.objects.bridge;
  bridge.message.connect(raw=>{
    const m=JSON.parse(raw);
    if(m.type==='initial'&&isPanel){fill(m);notice(m.status||'已准备就绪');}
    if(m.type==='theme')setTheme(m.theme);
    if(m.type==='lists'&&isPanel)applyLists(m.lists);
    if(m.type==='status'&&isPanel){notice(m.text);if(typeof m.extension==='boolean')setExtensionInstalled(m.extension);}
    if(m.type==='extensionState'&&isPanel)setExtensionInstalled(!!m.state?.installed);
    if(m.type==='extensionPrepared'&&isPanel)$('#guide-state').textContent='路径已复制：'+m.path+'。在文件夹选择框中粘贴并确认。';
    if(m.type==='showGuide'&&isPanel){$('#guide').hidden=false;$('#prepare-extension').focus();}
    if(m.type==='notice')notice(m.text);
    if(m.type==='panelEnter'&&isPanel)panelEnter(m);
    if(m.type==='panelExit'&&isPanel)panelExit();
    if(m.type==='toast'&&isToast)showToast(m);
    if(m.type==='pulse'&&isOrb){const o=$('#orb');o.classList.remove('pulse');void o.offsetWidth;o.classList.add('pulse');}
    if(m.type==='release'&&isPanel){release=m.release;$('#update').disabled=false;$('#update-label').textContent=release.newer?'安装更新 '+release.tag:'已是最新版 · '+release.tag;notice(release.newer?'更新来自 GitHub Releases，下载后将校验 SHA-256。':'当前已是 GitHub 最新稳定版。');}
    if(m.type==='updateError'&&isPanel){$('#update').disabled=false;notice(m.text);}
    if(m.type==='runtimeReady'&&isPanel){const link=$('#web-style');link.href=new URL('../runtime/web-ui.css',location.href).href+'?ready=1';}
    if(m.type==='runtimeReady'&&isOrb)startOrb().catch(e=>{$('#orb-error').hidden=false;request('orbError',e.message);});
  });
  if(isOrb){let down=false,moved=false,x=0,y=0;const hit=$('#orb-hit');hit.onpointerdown=e=>{if(e.button!==0)return;down=true;moved=false;x=e.screenX;y=e.screenY;hit.setPointerCapture(e.pointerId);request('dragStart');};hit.onpointermove=e=>{if(down&&Math.abs(e.screenX-x)+Math.abs(e.screenY-y)>4){moved=true;request('dragMove');}};hit.onpointerup=e=>{if(!down)return;down=false;request('dragEnd',{moved});};hit.oncontextmenu=e=>{e.preventDefault();request('context');};}
  else if(isPanel){
    const header=$('header');let panelDragging=false;
    header.onpointerdown=e=>{if(e.button!==0||e.target.closest('button'))return;panelDragging=true;header.classList.add('dragging');header.setPointerCapture(e.pointerId);request('panelDragStart');};
    header.onpointermove=()=>{if(panelDragging)request('panelDragMove');};
    const endPanelDrag=()=>{if(!panelDragging)return;panelDragging=false;header.classList.remove('dragging');request('panelDragEnd');};
    header.onpointerup=endPanelDrag;header.onpointercancel=endPanelDrag;header.onlostpointercapture=endPanelDrag;
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('#card'))request('hide');});
    for(const theme of ['light','dark'])$('#theme-'+theme).onclick=()=>{setTheme(theme);request('theme',{theme});};
    for(const mode of ['chat','work']){
      $('[data-mode='+mode+']').onclick=()=>chooseMode(mode);
      $('[data-mode='+mode+']').onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const next=mode==='chat'?'work':'chat';chooseMode(next);$('[data-mode='+next+']').focus();}};
      $('#'+mode+'-model').onclick=()=>openMenu(mode);
      $('#'+mode+'-model').onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();if($('#'+mode+'-model-menu').hidden)openMenu(mode,true);else $('#'+mode+'-model-menu').querySelector('[aria-selected=true]')?.focus();}};
      $('#'+mode+'-model-menu').onkeydown=e=>{const options=[...e.currentTarget.children],index=options.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?options.length-1:(index+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;options[next].focus();}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenus();$('#'+mode+'-model').focus();}else if(e.key==='Tab')closeMenus();};
      $('#'+mode+'-effort').onkeydown=e=>{const items=efforts[mode],index=items.findIndex(item=>item[0]===$('#'+mode+'-effort').dataset.effort);let next;if(e.key==='Home')next=0;else if(e.key==='End')next=items.length-1;else if(['ArrowLeft','ArrowDown'].includes(e.key))next=Math.max(0,index-1);else if(['ArrowRight','ArrowUp'].includes(e.key))next=Math.min(items.length-1,index+1);if(next!==undefined){e.preventDefault();selectEffort(mode,items[next][0]);}};
      $('#'+mode+'-effort').onfocus=()=>sliderInstances[mode]?.focus(true);
      $('#'+mode+'-effort').onblur=()=>sliderInstances[mode]?.focus(false);
    }
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.model-field'))closeMenus();});
    $('#close').onclick=()=>request('hide');$('#save').onclick=()=>{closeMenus();const config={enabled:$('#enabled').checked};for(const mode of ['chat','work'])config[mode]={enabled:$('#'+mode+'-enabled').checked,model:$('#'+mode+'-model').value,effort:$('#'+mode+'-effort').dataset.effort};request('save',{config,startup:$('#startup').checked});};
    // One-click deploy: the shell signs a CRX and registers it with Edge, so no
    // developer mode is involved. The dialog below stays as a manual fallback.
    $('#extension-action').onclick=()=>{closeMenus();if(extensionInstalled)request('uninstallExtension');else request('installExtension');notice(extensionInstalled?'正在移除浏览器扩展…':'正在部署浏览器扩展，Edge 会自动重启…');};
    $('#guide-close').onclick=()=>{$('#guide').hidden=true;};
    $('#prepare-extension').onclick=()=>{request('prepareExtension');$('#guide-state').textContent='正在准备扩展并打开 Edge…';};
    $('#copy-path').onclick=()=>request('copyExtension');
    $('#open-folder').onclick=()=>request('openExtension');
    renderExtensionAction();
    $('#update').onclick=()=>{if(release?.newer){$('#update').disabled=true;request('installUpdate');}else{$('#update').disabled=true;request('checkUpdate');notice('正在查询 GitHub Releases…');}};
    document.addEventListener('focusin',e=>{if(!e.target.closest('.model-field'))closeMenus();});
    document.onkeydown=e=>{if(e.key==='Escape'){if(!$('#guide').hidden){$('#guide-close').click();return;}if(document.querySelector('.model-menu:not([hidden])')){closeMenus();return;}request('hide');}if(e.key==='Tab'&&!$('#guide').hidden){const buttons=[...$('#guide').querySelectorAll('button:not([disabled])')],index=buttons.indexOf(document.activeElement);if(e.shiftKey&&index<=0){e.preventDefault();buttons.at(-1).focus();}else if(!e.shiftKey&&(index===buttons.length-1||index<0)){e.preventDefault();buttons[0].focus();}}};
  }
  else{
    const bubble=$('#toast .bubble');
    bubble.onpointerenter=()=>{toastHover=true;clearTimeout(toastTimer);};
    bubble.onpointerleave=()=>{toastHover=false;scheduleToastHide();};
  }
  request('ready',{view});
});
