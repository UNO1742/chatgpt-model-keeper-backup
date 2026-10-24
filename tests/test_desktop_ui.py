"""Settings interaction regressions and theme/slider screenshots."""
import json
from pathlib import Path
import sys
import threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from functools import partial
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from runtime_cache import ensure_runtime


def run():
    base=Path(__file__).resolve().parents[1]
    initial={'type':'initial','config':app.DEFAULT,'startup':True,'version':app.VERSION,'models':app.MODELS,'efforts':app.MODE_EFFORTS,'theme':'dark'}
    runtime=ensure_runtime(base.parent/'test-web-runtime',base)
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=self.path.split('?')[0]
            name=path.rsplit('/',1)[-1]
            file=runtime/(path[len('/runtime/'):] if path.startswith('/runtime/') else name)
            if path.startswith(('/runtime/','/cdn/assets/')) and file.is_file():
                data=file.read_bytes();self.send_response(200)
                self.send_header('Content-Type','text/css' if name.endswith('.css') else 'application/javascript' if name.endswith('.mjs') else 'font/woff2')
                self.end_headers();self.wfile.write(data);return
            super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(base/'desktop_ui')))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':360,'height':650})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_init_script('window.initial='+json.dumps(initial)+';window.qt={webChannelTransport:{}};window.requests=[];window.QWebChannel=function(t,callback){callback({objects:{bridge:{message:{connect(fn){window.incoming=fn}},request(raw){const m=JSON.parse(raw);requests.push(m);if(m.action==="ready")incoming(JSON.stringify(initial));}}}})};')
            page.goto(f'http://127.0.0.1:{server.server_port}/index.html?view=settings')
            page.wait_for_function('document.querySelector("#chat-model").value==="GPT-6"')
            page.wait_for_timeout(380)
            page.wait_for_function('document.querySelector("#chat-effort").dataset.renderer==="original-RWnX-H"')
            bottom=page.locator('#card').evaluate('e=>e.getBoundingClientRect().bottom')
            page.screenshot(path=str(base.parent/'settings-v21-dark.png'))
            assert bottom<=650,bottom
            assert page.locator('#card').evaluate('e=>getComputedStyle(e).borderRadius')=='28px'
            dark=page.locator('#card').evaluate('e=>getComputedStyle(e).backgroundColor')
            assert page.locator('.Track-eoFI82').first.evaluate('e=>getComputedStyle(e).height')=='24px'
            assert page.locator('.Thumb-hwJ5wX').first.evaluate('e=>getComputedStyle(e).width')=='28px'
            assert page.locator('#chat-effort .Range-CJS9gM').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(58, 131, 247)'
            assert page.locator('#chat-effort .Tick-pg_l_t[data-selected=true]').count()==5
            assert page.locator('#chat-effort .Tick-pg_l_t').first.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(255, 255, 255, 0.3)'
            save_style=page.locator('#save').evaluate('e=>({color:getComputedStyle(e).color,background:getComputedStyle(e).backgroundColor})')
            assert save_style['color']!=save_style['background'],save_style
            page.locator('#chat-model').click();assert page.locator('#chat-model-menu').is_visible()
            assert page.locator('#chat-model-menu [role=option]').all_text_contents()==['GPT-6✓','GPT-5.6 Sol']
            page.locator('#chat-model').click();assert page.locator('#chat-model-menu').is_hidden()
            page.locator('#chat-model').click();page.locator('h1').click();assert page.locator('#chat-model-menu').is_hidden()
            page.locator('#chat-model').press('ArrowDown');assert page.locator('#chat-model-menu').is_visible()
            page.keyboard.press('End');page.keyboard.press('Enter')
            assert page.locator('#chat-model').evaluate('e=>e.value')=='GPT-5.6 Sol'
            assert page.locator('#chat-model-menu').is_hidden()
            page.locator('#chat-model').click();page.keyboard.press('Escape');assert page.locator('#chat-model-menu').is_hidden()
            assert not page.evaluate('requests.some(x=>x.action==="hide")')
            print('PASS model dropdown: exact per-mode catalog, second click, outside click, Escape and keyboard selection')
            page.locator('[data-mode=work]').click();page.wait_for_timeout(80)
            midway=page.locator('.thumb').evaluate('e=>getComputedStyle(e).transform')
            page.wait_for_timeout(250)
            finish=page.locator('.thumb').evaluate('e=>getComputedStyle(e).transform')
            assert midway!=finish,(midway,finish)
            assert page.locator('#pane-chat').evaluate('e=>e.inert')
            page.locator('#work-model').click()
            assert len(page.locator('#work-model-menu [role=option]').all_text_contents())==7
            assert page.locator('#work-model-menu [role=option]').filter(has_text='GPT-6.1 Sol').count()==1
            page.locator('#work-model').click()
            page.wait_for_function('document.querySelector("#work-effort").dataset.renderer==="original-RWnX-H"');page.locator('#work-effort').focus();page.keyboard.press('Home');page.keyboard.press('ArrowRight');page.keyboard.press('ArrowRight')
            assert page.locator('#work-effort').get_attribute('data-effort')=='high'
            assert page.locator('#work-effort').get_attribute('aria-valuetext')=='高 / High'
            page.wait_for_function('document.querySelectorAll("#work-effort .Tick-pg_l_t[data-selected=true]").length===3',timeout=5000)
            assert page.locator('#work-effort .Tick-pg_l_t[data-selected=true]').count()==3
            assert page.locator('#work-effort .Tick-pg_l_t[data-selected=false]').count()==1
            page.locator('#work-rail-labels button').filter(has_text='极高').click()
            assert page.locator('#work-effort').get_attribute('data-effort')=='xhigh'
            page.keyboard.press('ArrowLeft')
            assert not any('Ultra' in s or 'Pro' in s for s in page.locator('.rail-labels').all_text_contents())
            page.locator('#save').click()
            saved=page.evaluate('requests.findLast(x=>x.action==="save").data')
            assert saved['config']['chat']['model']=='GPT-5.6 Sol'
            assert saved['config']['work']['effort']=='high'
            print('PASS mode transition and discrete range: keyboard, clickable ticks, exact saved effort, no Pro/Ultra')
            # Compare visible centers rather than reproducing the component's math.
            for width in (360,420,360):
                page.set_viewport_size({'width':width,'height':650})
                page.locator('#work-rail-labels button').filter(has_text='极高').click()
                page.wait_for_timeout(650)
                thumb=page.locator('#work-effort .Thumb-hwJ5wX').bounding_box()
                dot=page.locator('#work-effort .Tick-pg_l_t').last.bounding_box()
                assert abs(thumb['x']+thumb['width']/2-dot['x']-dot['width']/2)<1.5,(width,thumb,dot)
            first=page.locator('#work-effort .Tick-pg_l_t').first.bounding_box()
            thumb=page.locator('#work-effort .Thumb-hwJ5wX').bounding_box()
            page.mouse.move(thumb['x']+thumb['width']/2,thumb['y']+thumb['height']/2)
            page.mouse.down();page.mouse.move(first['x']+first['width']/2,first['y']+first['height']/2,steps=10);page.mouse.up()
            page.wait_for_function('document.querySelector("#work-effort").dataset.effort==="low"')
            page.locator('#work-rail-labels').get_by_role('button',name='高',exact=True).click()
            assert page.evaluate('originalSliderEngine.component')=='H'
            assert page.locator('.native-slider-bridge').count()==0
            assert not page.evaluate('originalSliderEngine.loaded.some(id=>["Wf1j","bqtn","ZxXe"].includes(id))')
            print('PASS original React/Radix/Motion component: thumb/dot alignment across widths, real drag, no replacement range input or account modules')
            page.locator('#theme-light').click();page.wait_for_timeout(230)
            assert page.locator('html').get_attribute('data-theme')=='light'
            assert page.locator('#card').evaluate('e=>getComputedStyle(e).backgroundColor')!=dark
            assert page.locator('#work-effort .Range-CJS9gM').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(58, 131, 247)'
            assert page.evaluate('requests.some(x=>x.action==="theme"&&x.data.theme==="light")')
            page.screenshot(path=str(base.parent/'settings-v21-light.png'))
            page.locator('#pane-work .reasoning').screenshot(path=str(base.parent/'blue-slider-v211.png'))
            page.evaluate('incoming(JSON.stringify({...initial,theme:"light"}))')
            assert page.locator('#theme-light').get_attribute('aria-pressed')=='true'
            print('PASS monochrome day/night themes, immediate persistence request and restored appearance')
            assert page.locator('.hint').count()==0
            assert page.locator('#chat-effort').get_attribute('aria-describedby')is None
            assert page.locator('#work-effort').get_attribute('aria-describedby')is None
            assert page.locator('.action-row span').text_content()=='浏览器扩展'
            action=page.locator('#extension-action')
            assert action.text_content()=='安装' and action.get_attribute('data-state')=='idle'
            action.click();page.wait_for_timeout(60)
            assert page.evaluate('requests.some(x=>x.action==="installExtension")')
            page.evaluate('incoming(JSON.stringify({type:"extensionState",state:{installed:true,id:"probe",version:"2.1.0",running:true}}))')
            assert action.text_content()=='卸载' and action.get_attribute('data-state')=='installed'
            action.click();page.wait_for_timeout(60)
            assert page.evaluate('requests.some(x=>x.action==="uninstallExtension")')
            page.evaluate('incoming(JSON.stringify({type:"extensionState",state:{installed:false,id:"probe",version:"",running:true}}))')
            assert action.text_content()=='安装' and action.get_attribute('data-state')=='idle'
            page.evaluate('incoming(JSON.stringify({type:"showGuide"}))')
            assert page.locator('#guide').is_visible()
            page.locator('#guide-close').click();assert page.locator('#guide').is_hidden()
            print('PASS one-click extension deploy: install/uninstall requests, installed state flip, manual guide fallback')
            page.evaluate('incoming(JSON.stringify({type:"release",release:{newer:true,tag:"v2.2.0"}}));incoming(JSON.stringify(initial));')
            assert page.locator('#version').text_content()=='v'+app.VERSION
            page.locator('#update').click();assert page.evaluate('requests.some(x=>x.action==="installUpdate")')
            assert not errors,errors
            print('PASS GitHub update action survives reopening settings')
            browser.close()
    finally:server.shutdown();server.server_close()

if __name__=='__main__':run()
