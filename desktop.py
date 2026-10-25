"""Qt WebEngine desktop: real-time Horizon renderer and a rounded settings card."""
import ctypes
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt, QUrl, QFile, QIODevice, QPoint
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QRegion
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

import app as api
import extension_deploy
from runtime_cache import ensure_runtime
import github_updates

class Events(QObject):
    completed=Signal(str,object)

class Bridge(QObject):
    message=Signal(str)
    def __init__(self,owner):super().__init__(owner);self.owner=owner
    def send(self,kind,**fields):self.message.emit(json.dumps({'type':kind,**fields},ensure_ascii=False))
    @Slot(str)
    def request(self,raw):
        try:
            message=json.loads(raw);action=message.get('action');data=message.get('data') or {}
            owner=self.owner
            if action=='ready':
                view=data.get('view')
                if view=='orb':
                    owner.orb_ready=True
                    if owner.runtime_ready:self.send('runtimeReady')
                elif view=='toast':
                    owner.toast_ready=True
                else:
                    owner.panel_ready=True;owner.initial();owner.status()
                    owner.push_enter()
                    if owner.runtime_ready:self.send('runtimeReady')
            elif action=='hide':owner.close_panel()
            elif action=='panelHidden':owner.hidden_by_page()
            elif action=='toastDone':owner.toast.hide()
            elif action=='panelDragStart':owner.panel_drag=(QCursor.pos(),owner.panel.pos())
            elif action=='panelDragMove' and owner.panel_drag:
                cursor,position=owner.panel_drag
                target=position+QCursor.pos()-cursor
                screen=owner.application.screenAt(QCursor.pos()) or owner.application.primaryScreen()
                area=screen.availableGeometry()
                owner.panel.move(QPoint(max(area.left()-owner.panel.width()+60,min(target.x(),area.right()-60)),max(area.top(),min(target.y(),area.bottom()-60))))
            elif action=='panelDragEnd':owner.panel_drag=None
            elif action=='dragStart':owner.drag_start=(QCursor.pos(),owner.orb.pos())
            elif action=='dragMove' and owner.drag_start:
                cursor,position=owner.drag_start;owner.orb.move(owner.clamp(position+QCursor.pos()-cursor))
                owner.close_panel(instant=True);owner.toast.hide()
            elif action=='dragEnd':
                owner.drag_start=None
                if data.get('moved'):api.atomic_write(api.ROOT/'ui.json',{'x':owner.orb.x(),'y':owner.orb.y()})
                else:owner.toggle_panel()
            elif action=='context':owner.context()
            elif action=='save':
                config=validate_config(data.get('config'))
                api.set_startup(bool(data.get('startup')))
                api.atomic_write(api.ROOT/'config.json',config)
                self.send('notice',text='已保存 · 开机自启'+('已开启' if api.startup_enabled() else '已关闭'))
            elif action=='theme':
                theme=data.get('theme')
                if theme not in ('light','dark'):raise ValueError('不支持的主题')
                api.atomic_write(api.ROOT/'appearance.json',{'theme':theme})
                self.send('theme',theme=theme)
            elif action=='prepareExtension':
                folder=api.prepare_extension_install()
                QApplication.clipboard().setText(str(folder))
                self.send('extensionPrepared',path=str(folder))
                self.send('notice',text='已准备扩展、复制路径并打开 Edge。首次仍需开启开发人员模式并加载文件夹。')
            elif action=='installExtension':
                self.send('notice',text='正在部署浏览器扩展…')
                owner.worker('extension',api.deploy_extension)
            elif action=='uninstallExtension':
                self.send('notice',text='正在移除浏览器扩展…')
                owner.worker('extension',lambda:extension_deploy.remove(api.ROOT))
            elif action=='restartEdge':
                self.send('notice',text='正在重启 Edge…')
                owner.worker('edgeRestart',extension_deploy.restart_edge)
            elif action in ('copyExtension','openExtension'):
                folder=api.extension_directory();QApplication.clipboard().setText(str(folder))
                if action=='openExtension':QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
                self.send('notice',text='扩展路径已复制。首次加载一次即可；连接后无需再打开文件夹。')
            elif action=='checkUpdate':owner.worker('release',lambda:github_updates.latest(api.VERSION))
            elif action=='installUpdate':
                if not owner.release or not owner.release.get('newer'):raise ValueError('请先检查 GitHub 更新')
                self.send('notice',text='正在从 GitHub 下载更新，完成后将校验并启动安装程序…')
                owner.worker('installer',lambda:github_updates.download(owner.release,api.ROOT/'downloads'))
            elif action=='orbError':
                owner.runtime_error=str(message.get('data',''))[:240]
                self.send('notice',text=owner.runtime_error)
        except Exception as error:self.send('updateError',text=str(error))

def validate_config(data):
    if not isinstance(data,dict) or not isinstance(data.get('enabled'),bool):raise ValueError('预设格式不正确')
    result={'enabled':data['enabled']}
    for mode in ('chat','work'):
        preset=data.get(mode,{})
        model=preset.get('model','')
        if not isinstance(model,str) or not 0<len(model.strip())<=80:raise ValueError('请输入网页中的完整模型名称')
        if preset.get('effort') not in dict(api.MODE_EFFORTS[mode]):raise ValueError('不支持的思考程度')
        if not isinstance(preset.get('enabled'),bool):raise ValueError('模式开关格式不正确')
        result[mode]={'enabled':preset['enabled'],'model':model.strip(),'effort':preset['effort']}
    return result

class LocalFiles(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        owner=self.server.owner
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':self.send_error(403);return
        path=urlparse(self.path).path
        prefix='/'+owner.token+'/'
        if not path.startswith(prefix) and path not in owner.font_files:self.send_error(404);return
        relative=path[len(prefix):] if path.startswith(prefix) else ''
        data=None;mime=None
        if relative=='ui/qwebchannel.js':
            data=owner.webchannel_js;mime='application/javascript'
        elif relative in ('ui/index.html','ui/style.css','ui/app.js','ui/original_component.js'):
            file=api.ASSETS/'desktop_ui'/relative.split('/')[-1]
            data=file.read_bytes();mime={'html':'text/html','css':'text/css','js':'application/javascript'}[file.suffix[1:]]
        elif relative in owner.runtime_files:
            file=api.ROOT/relative
            if not file.is_file():owner.runtime_event.wait(30)
            if file.is_file():data=file.read_bytes();mime={'.mjs':'application/javascript','.css':'text/css','.woff2':'font/woff2','.webp':'image/webp'}[file.suffix]
        elif path in owner.font_files:
            file=api.ROOT/'runtime'/owner.font_files[path]
            if not file.is_file():owner.runtime_event.wait(30)
            if file.is_file():data=file.read_bytes();mime='font/woff2'
        if data is None:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8' if mime.startswith(('text/','application/javascript')) else mime)
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)

class Page(QWebEnginePage):
    def acceptNavigationRequest(self,url,kind,main):
        return url.scheme()=='http' and url.host()=='127.0.0.1' and url.port()==self.parent().owner.server.server_port
    def javaScriptConsoleMessage(self,level,message,line,source):
        if 'error' in str(level).lower():self.parent().owner.console_errors.append(str(message)[:240])

class View(QWebEngineView):
    def __init__(self,owner,kind,width,height):
        super().__init__();self.owner=owner;self.kind=kind
        self.setWindowTitle('ChatGPT 模型锁定器 · '+{'orb':'实时语音球','settings':'模型设置','toast':'纠正提示'}[kind])
        flags=Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool
        if kind=='toast':flags|=Qt.WindowType.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        if kind=='toast':self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating,True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,True)
        self.resize(width,height)
        page=Page(self);page.setBackgroundColor(QColor(0,0,0,0));self.setPage(page)
        channel=QWebChannel(page);channel.registerObject('bridge',owner.bridge);page.setWebChannel(channel)
        self.channel=channel
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,True)
        page.setAudioMuted(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.loadFinished.connect(lambda ok:owner.console_errors.append(f'{kind} load failed: {self.url().toString()}') if not ok else None)
        self.load(QUrl(f'http://127.0.0.1:{owner.server.server_port}/{owner.token}/ui/index.html?view={kind}'))

class Desktop(QObject):
    def __init__(self,application,smoke=None):
        super().__init__();self.application=application;self.bridge=Bridge(self);self.events=Events(self)
        self.events.completed.connect(self.completed)
        self.runtime_ready=False;self.runtime_error='';self.orb_ready=False;self.panel_ready=False;self.runtime_event=threading.Event()
        self.panel_drag=None;self.mouse_buttons=0;self.guard_pending=False
        self.panel_closing=False;self.panel_enter=None;self.seen_corrections=None
        self.console_errors=[];self.release=None;self.drag_start=None;self.token=secrets.token_urlsafe(24)
        manifest=json.loads((api.ASSETS/'runtime_manifest.json').read_text(encoding='utf-8'))
        self.runtime_files={'runtime/'+entry['path'] for entry in manifest['files']}
        self.font_files={'/cdn/assets/'+entry['path']:entry['path'] for entry in manifest['files'] if entry['path'].endswith('.woff2')}
        file=QFile(':/qtwebchannel/qwebchannel.js')
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):raise RuntimeError('Qt WebChannel 资源不可用')
        self.webchannel_js=bytes(file.readAll());file.close()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),LocalFiles);self.server.owner=self
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.orb=View(self,'orb',80,80);self.panel=View(self,'settings',384,674)
        # Third view: the correction bubble. Lazy-free (created once) so a toast
        # never waits for a page load when a correction lands.
        self.toast=View(self,'toast',328,126);self.toast_ready=False
        # Limit hit area to the visible small orb, instead of a large transparent overlay.
        self.orb.setMask(QRegion(2,2,76,76,QRegion.RegionType.Ellipse))
        screen=application.primaryScreen().availableGeometry()
        position=QPoint(screen.right()-110,screen.bottom()-145)
        try:
            saved=json.loads((api.ROOT/'ui.json').read_text(encoding='utf-8'));position=QPoint(int(saved['x']),int(saved['y']))
        except (OSError,ValueError,KeyError,TypeError):pass
        self.orb.move(self.clamp(position));self.orb.show()
        # Only sample button state; no global hook, input interception or click replay.
        self.outside_timer=QTimer(self);self.outside_timer.timeout.connect(self.check_outside_click);self.outside_timer.start(25)
        self.timer=QTimer(self);self.timer.timeout.connect(self.status);self.timer.start(3000)
        # Watchdog: keeps a windowless Edge anchored with the extension loaded,
        # so opening Edge any way lands in a browser that already has it.
        self.guard_timer=QTimer(self);self.guard_timer.timeout.connect(self.guard);self.guard_timer.start(8000)
        self.worker('runtime',lambda:ensure_runtime(api.ROOT,api.ASSETS))
        self.worker('extensionRefresh',api.refresh_extension)
        application.aboutToQuit.connect(self.shutdown)
        if smoke:
            self.smoke=Path(smoke);QTimer.singleShot(11000,self.smoke_result)
    def check_outside_click(self):
        buttons=sum((1<<i) for i,key in enumerate((1,2,4)) if ctypes.windll.user32.GetAsyncKeyState(key)&0x8000)
        pressed=buttons & ~self.mouse_buttons;self.mouse_buttons=buttons
        if not pressed or not self.panel.isVisible() or self.panel_drag:return
        point=QCursor.pos()
        # The orb handles its own toggle on release, avoiding an accidental reopen.
        if self.orb.geometry().contains(point):return
        if not self.panel.geometry().adjusted(24,24,-24,-24).contains(point):self.close_panel()
    def clamp(self,p):
        area=self.application.primaryScreen().availableGeometry()
        return QPoint(max(area.left(),min(p.x(),area.right()-80)),max(area.top(),min(p.y(),area.bottom()-80)))
    def worker(self,kind,fn):
        def task():
            try:self.events.completed.emit(kind,fn())
            except Exception as e:self.events.completed.emit(kind,{'error':str(e)})
        threading.Thread(target=task,daemon=True).start()
    def guard(self):
        if self.guard_pending:return
        self.guard_pending=True
        self.worker('extensionGuard',lambda:extension_deploy.guard(api.ROOT))
    @Slot(str,object)
    def completed(self,kind,value):
        if kind=='runtime':self.runtime_event.set()
        if kind=='extensionGuard':self.guard_pending=False
        if isinstance(value,dict) and 'error' in value:
            if kind=='runtime':self.runtime_error='实时球资源加载失败：'+value['error']
            if kind in ('extensionRefresh','extensionGuard'):return
            if kind=='extension':
                self.bridge.send('updateError',text='扩展部署失败：'+value['error']+'（可在悬浮球右键菜单中手动安装）');return
            self.bridge.send('updateError',text=self.runtime_error if kind=='runtime' else value['error']);return
        if kind=='runtime':
            self.runtime_ready=True
            if self.orb_ready:self.bridge.send('runtimeReady')
        elif kind=='extensionGuard':
            if value.get('action')=='restarted':
                self.bridge.send('notice',text='Edge 已在后台重新加载扩展，标签页已恢复。' if value.get('windows') else '扩展已就绪，下次打开 Edge 自动生效。')
                self.bridge.send('extensionState',state=extension_deploy.state(api.ROOT))
        elif kind=='extension':
            self.bridge.send('extensionState',state=value)
            if value.get('installed'):
                if value.get('enabled'):
                    self.bridge.send('notice',text='扩展已启用，打开 Edge 即可使用。' if value.get('anchored') else '扩展已启用。')
                elif value.get('needsRestart'):
                    self.bridge.send('notice',text='扩展已登记，Edge 下次启动时自动启用。')
                else:
                    self.bridge.send('notice',text='扩展已登记，但 Edge 未接受，请重启浏览器后再试。')
            else:
                self.bridge.send('notice',text='扩展注册已移除。')
        elif kind=='edgeRestart':
            self.bridge.send('notice',text='Edge 已重启，扩展状态会在连接后自动刷新。')
        elif kind=='extensionRefresh':
            self.bridge.send('extensionState',state=value)
        elif kind=='release':self.release=value;self.bridge.send('release',release=value)
        elif kind=='installer':
            subprocess.Popen([str(value),'/SILENT','/CLOSEAPPLICATIONS'],creationflags=0x08000000)
            self.application.quit()
    def initial(self):
        self.bridge.send('initial',config=api.load_config(),startup=api.startup_enabled(),version=api.VERSION,
            models=api.MODELS,efforts=api.MODE_EFFORTS,theme=api.load_appearance()['theme'],status=self.runtime_error or '原始网页动效 · 实时 WebGL 渲染')
    def status(self):
        connected=False;text='等待 Edge 扩展连接。';data=None
        try:
            data=json.loads((api.ROOT/'status.json').read_text(encoding='utf-8'))
            connected=time.time()-data['updated']<20 and bool(data['tabs'])
            if connected:
                r=list(data['tabs'].values())[-1];text=f"{r['mode']} · {r['state']} · {r['detail']}"
        except (OSError,ValueError,KeyError,TypeError):pass
        if data:self.scan_corrections(data)
        if self.runtime_error:text=self.runtime_error
        if not self.panel_ready or not self.panel.isVisible():return
        state=extension_deploy.state(api.ROOT)
        self.bridge.send('status',text=text,connected=connected,extension=state['installed'],extensionEnabled=state['enabled'])
    def scan_corrections(self,data):
        # The extension reports {changed, previous, applied, seq}; anything new
        # since the last sweep becomes a bubble under the ball. The first sweep
        # only primes the seen set, so restarting never replays old news.
        try:stale=time.time()-float(data['updated'])>25
        except (KeyError,TypeError,ValueError):return
        current={}
        for tab,report in (data.get('tabs') or {}).items():
            if str(report.get('changed'))!='1':continue
            current[(str(tab),str(report.get('seq') or report.get('time') or ''))]=report
        if self.seen_corrections is None:
            self.seen_corrections=set(current);return
        fresh=[(key,report) for key,report in current.items() if key not in self.seen_corrections]
        self.seen_corrections=set(current)
        if not fresh or stale or self.panel.isVisible():return
        self.show_toast(fresh[-1][1])
    def show_toast(self,report):
        applied=str(report.get('applied') or '').strip()
        previous=str(report.get('previous') or '').strip()
        detail=f'网页上原来是 {previous}，已自动纠正' if previous else '网页上的模型和预设不一致，已自动纠正'
        area=self.application.primaryScreen().availableGeometry()
        orb=self.orb.geometry();width=self.toast.width();height=self.toast.height()
        cx=orb.x()+orb.width()//2
        below=orb.y()+orb.height()+8
        above=orb.y()-8-height
        # Prefer the bubble under the ball; flip above when the desk edge is
        # closer than the bubble is tall (the default spot is 65 px from the
        # bottom, so it usually flips).
        high=below+height>area.bottom()+1 and above>=area.top()
        y=above if high else below
        x=max(area.left(),min(cx-width//2,area.right()-width+1))
        self.toast.move(QPoint(int(x),int(y)))
        self.toast.show();self.toast.raise_()
        tail=max(24,min(int(cx-x-8),width-32))
        title='已按预设切回 '+(applied or '目标模型')
        # Give the freshly raised window one paint before the bubble animates in.
        QTimer.singleShot(30,lambda:self.bridge.send('toast',title=title,detail=detail,above=high,tail=tail))
        # The page normally reports back after its 5.2 s dwell; this bounds the
        # bubble even if that message is lost.
        QTimer.singleShot(9000,self.toast.hide)
    def panel_placement(self):
        area=self.application.primaryScreen().availableGeometry()
        orb=self.orb.geometry();ox,oy,ow=orb.x(),orb.y(),orb.width()
        right,bottom=ox+ow,oy+ow;cx,cy=ox+ow//2,oy+ow//2
        width,height=self.panel.width(),self.panel.height()
        inset,gap,gapx=24,6,14
        card_w,card_h=width-2*inset,height-2*inset
        candidates=[('上方',right-card_w-inset,oy-gap-card_h-inset),
                    ('下方',right-card_w-inset,bottom+gap-inset),
                    ('右侧',right+gapx-inset,cy-card_h//2-inset),
                    ('左侧',ox-gapx-card_w-inset,cy-card_h//2-inset)]
        def fits(x,y):
            return x>=area.left() and y>=area.top() and x+width<=area.right()+1 and y+height<=area.bottom()+1
        pick=next(((name,x,y) for name,x,y in candidates if fits(x,y)),None)
        if pick is None:
            def over(x,y):
                return (max(0,area.left()-x)+max(0,area.top()-y)+
                        max(0,x+width-area.right()-1)+max(0,y+height-area.bottom()-1))
            pick=min(candidates,key=lambda item:over(item[1],item[2]))
        x=max(area.left(),min(pick[1],area.right()-width+1))
        y=max(area.top(),min(pick[2],area.bottom()-height+1))
        origin={'x':cx-(x+inset),'y':cy-(y+inset)}
        dx,dy=(x+inset+card_w/2)-cx,(y+inset+card_h/2)-cy
        length=math.hypot(dx,dy) or 1
        return QPoint(int(x),int(y)),origin,{'x':round(dx/length,3),'y':round(dy/length,3)}
    def open_panel(self):
        if self.panel.isVisible():return
        self.toast.hide()
        point,origin,direction=self.panel_placement()
        self.panel.move(point)
        self.panel_enter={'origin':origin,'dir':direction}
        # Fill while the card is still transparent: it is already correct when
        # the enter animation starts, so nothing snaps into place mid-flight.
        if self.panel_ready:self.initial();self.status()
        self.panel.setWindowOpacity(1.0)
        self.panel.show();self.panel.raise_()
        self.push_enter()
    def push_enter(self):
        # The page may not exist yet on the very first open; the payload waits
        # for its "ready" and is delivered from there.
        payload=self.panel_enter
        if payload and self.panel_ready and self.panel.isVisible():
            self.panel_enter=None
            self.bridge.send('panelEnter',**payload)
            self.bridge.send('pulse')  # broadcast; only the orb view reacts
    def close_panel(self,instant=False):
        if not self.panel.isVisible() or self.panel_closing:return
        if instant or not self.panel_ready:
            self.panel.hide();return
        # The page plays the 150 ms exit and reports back; the fallback below
        # hides the window even if that message never arrives.
        self.panel_closing=True
        self.bridge.send('panelExit')
        QTimer.singleShot(320,self.hidden_by_page)
    def hidden_by_page(self):
        self.panel_closing=False;self.panel.hide()
    def toggle_panel(self):
        if self.panel.isVisible():self.close_panel()
        else:self.open_panel()
    def context(self):
        light=api.load_appearance()['theme']=='light'
        menu=QMenu();menu.setStyleSheet('QMenu{background:'+('#fff;color:#171717' if light else '#202020;color:#eee')+';border:1px solid #777;border-radius:10px;padding:7px} QMenu::item{padding:8px 15px} QMenu::item:selected{background:'+('#e9e9e9' if light else '#3a3a3a')+'}')
        menu.addAction('模型设置',self.toggle_panel)
        menu.addAction('修复浏览器扩展',lambda:self.worker('extension',api.deploy_extension))
        keep=menu.addAction('自动保持扩展启用')
        keep.setCheckable(True);keep.setChecked(extension_deploy.guard_enabled(api.ROOT))
        keep.toggled.connect(lambda checked:extension_deploy.set_guard_enabled(api.ROOT,checked))
        menu.addAction('立即准备 Edge（后台加载扩展）',lambda:self.worker('extension',lambda:extension_deploy.deploy(api.ROOT,restart=False)))
        menu.addAction('手动安装扩展…',self.manual_extension)
        menu.addAction('项目与下载 · GitHub',lambda:QDesktopServices.openUrl(QUrl(github_updates.RELEASES)))
        menu.addSeparator();menu.addAction('退出悬浮窗',self.application.quit);menu.exec(QCursor.pos())
    def manual_extension(self):
        # Developer-mode fallback, only needed when automatic registration fails.
        if not self.panel.isVisible():self.toggle_panel()
        QTimer.singleShot(600,lambda:self.bridge.send('showGuide'))
    def smoke_result(self):
        self.toggle_panel()
        def finish(result):
            def complete(panel):
                self.smoke.parent.mkdir(parents=True,exist_ok=True)
                self.smoke.write_text(json.dumps({'runtime_ready':self.runtime_ready,'orb':result,'panel':panel,'orb_ready':self.orb_ready,'panel_ready':self.panel_ready,'url':self.orb.url().toString(),'errors':self.console_errors,'runtime_error':self.runtime_error}),encoding='utf-8')
                self.panel.grab().save(str(self.smoke.with_suffix('.png')))
                self.application.quit()
            self.panel.page().runJavaScript('JSON.stringify({theme:document.documentElement.dataset.theme,sliders:[...document.querySelectorAll("[data-renderer]")].map(e=>{const t=e.querySelector(".Thumb-hwJ5wX")?.getBoundingClientRect(),d=[...e.querySelectorAll(".Tick-pg_l_t[data-selected=true]")].at(-1)?.getBoundingClientRect();return {renderer:e.dataset.renderer,blue:getComputedStyle(e.querySelector(".Range-CJS9gM")).backgroundColor,selectedDelta:t&&d?Math.abs(t.x+t.width/2-d.x-d.width/2):null}})})',complete)
        QTimer.singleShot(800,lambda:self.orb.page().runJavaScript('JSON.stringify({kind:window.orbKind,draws:window.orbDraws,canvases:document.querySelectorAll("canvas").length,body:document.body?.innerText.slice(0,100)})',finish))
    def shutdown(self):
        self.timer.stop();self.server.shutdown();self.server.server_close()
        self.orb.close();self.panel.close();self.toast.close()

def run():
    application=QApplication(sys.argv);application.setQuitOnLastWindowClosed(False)
    application.setApplicationName('ChatGPT Model Keeper')
    name='ModelKeeper-'+hashlib.sha256(str(api.ROOT).encode()).hexdigest()[:18]
    socket=QLocalSocket();socket.connectToServer(name)
    if socket.waitForConnected(250):
        socket.write(b'open' if '--startup' not in sys.argv else b'ping');socket.flush();socket.waitForBytesWritten(250);return
    server=QLocalServer();QLocalServer.removeServer(name)
    if not server.listen(name):raise RuntimeError('无法建立本机单实例通道')
    smoke=None
    if '--gui-smoke' in sys.argv:smoke=sys.argv[sys.argv.index('--gui-smoke')+1]
    desktop=Desktop(application,smoke)
    def connection():
        client=server.nextPendingConnection()
        def read():
            if bytes(client.readAll())==b'open':desktop.toggle_panel()
            client.disconnectFromServer()
        client.readyRead.connect(read)
        if client.bytesAvailable():read()
    server.newConnection.connect(connection)
    try:application.exec()
    finally:server.close()
