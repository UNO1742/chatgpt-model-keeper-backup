import * as originalSlider from './original_component.js';
const isOrb=new URLSearchParams(location.search).get('view')==='orb';
const $=s=>document.querySelector(s);
$('#orb').hidden=!isOrb;$('#card').hidden=isOrb;
let bridge,release=null,models={chat:[],work:[]},efforts={chat:[],work:[]},orbLoading=false;
const sliderInstances={},sliderLoads={};
function notice(s){if(!isOrb)$('#status').textContent=s;}
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
function renderEffort(mode,value){const slider=$('#'+mode+'-effort'),items=efforts[mode];let index=items.findIndex(item=>item[0]===value);if(index<0)index=items.length-1;const [id,label]=items[index];slider.dataset.effort=id;slider.setAttribute('aria-valuemin','0');slider.setAttribute('aria-valuemax',String(items.length-1));slider.setAttribute('aria-valuenow',String(index));slider.setAttribute('aria-valuetext',label);$('#'+mode+'-effort-label').textContent=label;$('#'+mode+'-rail-labels').querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));}
async function selectEffort(mode,value){renderEffort(mode,value);const instance=sliderInstances[mode]||await sliderLoads[mode];instance.select(value);}
function buildEfforts(mode,value){const items=efforts[mode],slider=$('#'+mode+'-effort');$('#'+mode+'-rail-labels').replaceChildren(...items.map(([id,label])=>{const button=document.createElement('button');button.textContent=label.split(' / ')[0];button.title=label;button.onclick=()=>{selectEffort(mode,id);slider.focus();};return button;}));renderEffort(mode,value);if(sliderInstances[mode]){sliderInstances[mode].select(slider.dataset.effort);return;}if(!sliderLoads[mode])sliderLoads[mode]=originalSlider.mount(slider,{options:items,selected:slider.dataset.effort,onChange:id=>renderEffort(mode,id)}).then(instance=>{sliderInstances[mode]=instance;instance.select(slider.dataset.effort);return instance;}).catch(error=>{notice('原始滑条加载失败：'+error.message);throw error;});}
function fill(data){$('#version').textContent='v'+data.version;$('#enabled').checked=data.config.enabled;$('#startup').checked=data.startup;models=data.models;efforts=data.efforts;setTheme(data.theme||'dark');for(const mode of ['chat','work']){const p=data.config[mode];$('#'+mode+'-enabled').checked=p.enabled;buildModels(mode,p.model);buildEfforts(mode,p.effort);}}
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
new QWebChannel(qt.webChannelTransport,channel=>{
  bridge=channel.objects.bridge;
  bridge.message.connect(raw=>{
    const m=JSON.parse(raw);
    if(m.type==='initial'&&!isOrb){fill(m);notice(m.status||'已准备就绪');}
    if(m.type==='theme'&&!isOrb)setTheme(m.theme);
    if(m.type==='status'&&!isOrb){notice(m.text);if(typeof m.extension==='boolean')setExtensionInstalled(m.extension);}
    if(m.type==='extensionState'&&!isOrb)setExtensionInstalled(!!m.state?.installed);
    if(m.type==='extensionPrepared'&&!isOrb)$('#guide-state').textContent='路径已复制：'+m.path+'。在文件夹选择框中粘贴并确认。';
    if(m.type==='showGuide'&&!isOrb){$('#guide').hidden=false;$('#prepare-extension').focus();}
    if(m.type==='notice')notice(m.text);
    if(m.type==='release'&&!isOrb){release=m.release;$('#update').disabled=false;$('#update-label').textContent=release.newer?'安装更新 '+release.tag:'已是最新版 · '+release.tag;notice(release.newer?'更新来自 GitHub Releases，下载后将校验 SHA-256。':'当前已是 GitHub 最新稳定版。');}
    if(m.type==='updateError'&&!isOrb){$('#update').disabled=false;notice(m.text);}
    if(m.type==='runtimeReady'&&!isOrb){const link=$('#web-style');link.href=new URL('../runtime/web-ui.css',location.href).href+'?ready=1';}
    if(m.type==='runtimeReady'&&isOrb)startOrb().catch(e=>{$('#orb-error').hidden=false;request('orbError',e.message);});
  });
  if(isOrb){let down=false,moved=false,x=0,y=0;const hit=$('#orb-hit');hit.onpointerdown=e=>{if(e.button!==0)return;down=true;moved=false;x=e.screenX;y=e.screenY;hit.setPointerCapture(e.pointerId);request('dragStart');};hit.onpointermove=e=>{if(down&&Math.abs(e.screenX-x)+Math.abs(e.screenY-y)>4){moved=true;request('dragMove');}};hit.onpointerup=e=>{if(!down)return;down=false;request('dragEnd',{moved});};hit.oncontextmenu=e=>{e.preventDefault();request('context');};}
  else{
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
    $('#extension-action').onclick=()=>{closeMenus();if(extensionInstalled)request('uninstallExtension');else request('installExtension');notice(extensionInstalled?'正在移除浏览器扩展…':'正在部署浏览器扩展…');};
    $('#guide-close').onclick=()=>{$('#guide').hidden=true;};
    $('#prepare-extension').onclick=()=>{request('prepareExtension');$('#guide-state').textContent='正在准备扩展并打开 Edge…';};
    $('#copy-path').onclick=()=>request('copyExtension');
    $('#open-folder').onclick=()=>request('openExtension');
    renderExtensionAction();
    $('#update').onclick=()=>{if(release?.newer){$('#update').disabled=true;request('installUpdate');}else{$('#update').disabled=true;request('checkUpdate');notice('正在查询 GitHub Releases…');}};
    document.addEventListener('focusin',e=>{if(!e.target.closest('.model-field'))closeMenus();});
    document.onkeydown=e=>{if(e.key==='Escape'){if(!$('#guide').hidden){$('#guide-close').click();return;}if(document.querySelector('.model-menu:not([hidden])')){closeMenus();return;}request('hide');}if(e.key==='Tab'&&!$('#guide').hidden){const buttons=[...$('#guide').querySelectorAll('button:not([disabled])')],index=buttons.indexOf(document.activeElement);if(e.shiftKey&&index<=0){e.preventDefault();buttons.at(-1).focus();}else if(!e.shiftKey&&(index===buttons.length-1||index<0)){e.preventDefault();buttons[0].focus();}}};
  }
  request('ready',{orb:isOrb});
});
