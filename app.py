"""ChatGPT Model Keeper: per-user installer, settings UI and native messaging host."""
import copy
import ctypes
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import winreg

import extension_deploy

HOST = 'local.chatgpt.modelkeeper'
VERSION = '2.8.0'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'ChatGPTModelKeeper'
def installation_root():
    base = Path(os.environ['LOCALAPPDATA'])
    # A frozen installed host must keep using its own directory when Edge or
    # Windows startup launches it outside the original installing environment.
    if getattr(sys, 'frozen', False):
        own = Path(sys.executable).resolve().parent
        if own.name == 'ChatGPTModelKeeper' and (own/'host.json').is_file():
            return own
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Edge\NativeMessagingHosts'+'\\'+'local.chatgpt.modelkeeper') as key:
            registered, _ = winreg.QueryValueEx(key, '')
        candidate = Path(registered).parent.resolve()
        if (candidate.is_relative_to(base.resolve()) and candidate.name=='ChatGPTModelKeeper'
                and (candidate/'ModelKeeper.exe').is_file() and (candidate/'host.json').is_file()):
            return candidate
    except (OSError, ValueError):
        pass
    root = base/'ChatGPTModelKeeper'
    root.mkdir(parents=True, exist_ok=True)
    # Windows can redirect a write under AppData to a package LocalCache. Resolve
    # after creation, so Explorer, Edge and Run receive the physical path.
    return root.resolve()

ROOT = installation_root()
EXE = ROOT / 'ModelKeeper.exe'
ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
DEFAULT = {'enabled': True, 'chat': {'enabled': True, 'model': 'GPT-6', 'effort': 'xhigh'},
           'work': {'enabled': True, 'model': 'GPT-6 Sol', 'effort': 'xhigh'}}
MODELS = {'chat': ['GPT-6', 'GPT-5.6 Sol'],
          'work': ['GPT-6.1 Sol', 'GPT-6 Astra', 'GPT-6 Sol', 'GPT-6 Luna',
                   'GPT-5.6 Sol', 'GPT-5.6 Terra', 'GPT-5.6 Luna']}
EFFORTS = [('none','即时 / Instant'), ('low','轻度 / Light'),
           ('medium','中 / Medium'), ('high','高 / High'), ('xhigh','极高 / Extra high')]
MODE_EFFORTS = {'chat': EFFORTS, 'work': EFFORTS[1:]}
EFFORT_IDS = {key for key, _ in EFFORTS}
# Pro and Ultra are exactly what a preset is supposed to keep people off.
BLOCKED_MODEL = re.compile(r'(?:^|[^a-z0-9])(pro|ultra)(?:[^a-z0-9]|$)', re.IGNORECASE)

def clean_models(value):
    """Model names as reported by the page, minus the tiers we never offer."""
    if not isinstance(value, list): return []
    names = []
    for item in value[:16]:
        name = ' '.join(str(item or '').split())[:60]
        if name and not BLOCKED_MODEL.search(name) and name not in names: names.append(name)
    return names

def clean_efforts(value):
    if not isinstance(value, list): return []
    return [item for item in (str(v) for v in value[:8]) if item in EFFORT_IDS]

def atomic_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def load_config():
    result = copy.deepcopy(DEFAULT)
    try:
        data = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        if isinstance(data.get('enabled'), bool): result['enabled'] = data['enabled']
        for mode in ('chat', 'work'):
            p = data.get(mode, {})
            if isinstance(p.get('enabled'), bool): result[mode]['enabled'] = p['enabled']
            if isinstance(p.get('model'), str) and 0 < len(p['model']) <= 80:
                result[mode]['model'] = p['model']
            if p.get('effort') in dict(MODE_EFFORTS[mode]): result[mode]['effort'] = p['effort']
    except (OSError, ValueError, TypeError, AttributeError): pass
    return result

def extension_ids():
    # The installed copy carries this machine's signing key, so it owns the live
    # ID; the bundled key stays listed for extensions that were loaded by hand
    # before one-click deployment existed.
    values = [extension_deploy.folder_id(ROOT/'extension'), extension_deploy.folder_id(ASSETS/'extension')]
    return [value for value in dict.fromkeys(values) if value]

def extension_id():
    values = extension_ids()
    return values[0] if values else ''

def extension_origins():
    return ['chrome-extension://'+value+'/' for value in extension_ids()]

def deploy_extension(restart=True):
    # Registering the extension is best effort: when Edge refuses, the settings
    # card still offers the manual developer-mode guide. Install and migration
    # call it with restart=False so they never close a browser in use.
    try:
        return extension_deploy.deploy(ROOT, extension_directory(), restart=restart)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        return {'installed': False, 'enabled': False, 'id': '', 'version': '', 'running': False, 'error': str(error)}

def refresh_extension():
    # Re-apply after an app update, but never resurrect an extension the user
    # removed on purpose.
    if not extension_deploy.registered(ROOT):
        return {'installed': False, 'enabled': False, 'id': extension_id(), 'version': '', 'running': False}
    try:
        return extension_deploy.refresh(ROOT, extension_directory())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        return {'installed': False, 'enabled': False, 'id': '', 'version': '', 'running': False, 'error': str(error)}

def startup_enabled():
    """Is the current EXE the one Windows launches at login?"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            match = re.fullmatch(r'"([^"]+)"\s+--startup', value)
            return bool(match and Path(match.group(1)).resolve()==EXE.resolve())
    except FileNotFoundError:
        return False

def startup_preference():
    """The user's stored choice: True/False, or None when never recorded."""
    try:
        data=json.loads((ROOT/'startup.json').read_text(encoding='utf-8'))
    except (OSError,ValueError,AttributeError):
        return None
    if 'enabled' in data:
        return bool(data['enabled'])
    # Legacy files only carried {'configured': True}; those users asked for it.
    return True if data.get('configured') else None

def set_startup(enabled):
    if enabled:
        if not EXE.is_file():
            raise RuntimeError('请先安装到本机，再启用开机自启。')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, f'"{EXE}" --startup')
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass
    atomic_write(ROOT/'startup.json', {'configured': True, 'enabled': bool(enabled)})

def reconcile_startup():
    """Re-create a missing Run entry, or drop one the user turned off.

    Without this a lost Run value stayed lost forever: the stored preference said
    "nothing to do" and no screen offered to turn it back on.
    """
    wanted = startup_preference()
    if wanted is None or not EXE.is_file():
        return False
    if wanted == startup_enabled():
        return False
    try:
        set_startup(wanted)
        return True
    except (OSError, RuntimeError):
        return False

def install():
    # A first installation enables login startup; later updates keep the stored
    # choice instead of silently resetting it.
    wanted = startup_preference()
    ROOT.mkdir(parents=True, exist_ok=True)
    if not getattr(sys, 'frozen', False): raise RuntimeError('请使用已打包的 EXE 安装。')
    if Path(sys.executable).resolve() != EXE.resolve():
        shutil.copy2(sys.executable, EXE)
    shutil.copytree(ASSETS / 'extension', ROOT / 'extension', dirs_exist_ok=True)
    deploy_extension(restart=False)
    host_exe = ROOT/'ModelKeeperHost.exe'
    atomic_write(ROOT / 'host.json', {'name': HOST, 'description': 'ChatGPT Model Keeper',
        'path': str(host_exe if host_exe.exists() else EXE), 'type': 'stdio',
        'allowed_origins': extension_origins()})
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Edge\NativeMessagingHosts' + '\\' + HOST) as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(ROOT / 'host.json'))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ChatGPTModelKeeper') as key:
        for name, val in {'DisplayName': 'ChatGPT 模型锁定器', 'DisplayVersion': VERSION,
                          'Publisher': 'Model Keeper (local build)', 'InstallLocation': str(ROOT),
                          'DisplayIcon': str(EXE), 'UninstallString': f'"{EXE}" --uninstall'}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)
    # Start Menu shortcut; login startup is registered separately for this user.
    menu = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs'
    menu.mkdir(parents=True, exist_ok=True)
    script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + str(menu / 'ChatGPT 模型锁定器.lnk').replace("'", "''") + "');$s.TargetPath='" + str(EXE).replace("'", "''") + "';$s.Save()"
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                   creationflags=0x08000000, check=True, timeout=20, capture_output=True)
    if not (ROOT / 'config.json').exists(): atomic_write(ROOT / 'config.json', DEFAULT)
    set_startup(True if wanted is None else wanted)

def extension_directory():
    folder = ROOT/'extension'
    required = ('manifest.json','background.js','content.js','popup.html','popup.js')
    if not all((folder/name).is_file() for name in required):
        shutil.copytree(ASSETS/'extension', folder, dirs_exist_ok=True)
    folder = folder.resolve(strict=True)
    json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    return folder


def load_appearance():
    try:
        data=json.loads((ROOT/'appearance.json').read_text(encoding='utf-8'))
        if data.get('theme') in ('light','dark'):return {'theme':data['theme']}
    except (OSError,ValueError,AttributeError):pass
    return {'theme':'dark'}


def prepare_extension_install():
    # Edge requires first-time confirmation for unpacked extensions. Prepare the
    # real folder; open its native management page without changing policies.
    folder=extension_directory()
    os.startfile('microsoft-edge:edge://extensions/')
    return folder

def uninstall():
    set_startup(False)
    # Browser must remove its own extension; preserve preferences for reinstall.
    try: extension_deploy.remove(ROOT)
    except (OSError, RuntimeError, ValueError): pass
    for sub in (r'Software\Microsoft\Edge\NativeMessagingHosts' + '\\' + HOST,
                r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ChatGPTModelKeeper'):
        try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except FileNotFoundError: pass
    shortcut = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/ChatGPT 模型锁定器.lnk'
    shortcut.unlink(missing_ok=True)
    (ROOT / 'host.json').unlink(missing_ok=True)

def native_streams():
    if sys.stdin is not None and sys.stdout is not None:
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        return sys.stdin.buffer, sys.stdout.buffer
    # PyInstaller windowed executables have sys.stdin/sys.stdout = None.
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.restype = ctypes.c_void_p
    i = kernel.GetStdHandle(-10)
    o = kernel.GetStdHandle(-11)
    return (os.fdopen(msvcrt.open_osfhandle(i, os.O_RDONLY | os.O_BINARY), 'rb', buffering=0),
            os.fdopen(msvcrt.open_osfhandle(o, os.O_WRONLY | os.O_BINARY), 'wb', buffering=0))

def read_exact(stream, n):
    parts = bytearray()
    while len(parts) < n:
        block = stream.read(n - len(parts))
        if not block: return None
        parts.extend(block)
    return bytes(parts)

def native_main():
    inp, out = native_streams()
    reports = {}
    while True:
        header = read_exact(inp, 4)
        if header is None: break
        size = struct.unpack('<I', header)[0]
        if size > 65536: break
        body = read_exact(inp, size)
        if body is None: break
        try:
            req = json.loads(body)
            if req.get('type') == 'status':
                # Only fixed status fields. No URL, title or conversation content.
                report = req.get('report', {})
                allowed = {k: str(report.get(k, ''))[:240]
                           for k in ('mode','state','detail','previous','applied','seq')}
                allowed['changed'] = '1' if report.get('changed') else '0'
                allowed['time'] = time.strftime('%H:%M:%S')
                # What the page actually offers, so the card can copy it instead
                # of shipping a hard-coded guess.
                allowed['models'] = clean_models(report.get('models'))
                allowed['efforts'] = clean_efforts(report.get('efforts'))
                allowed['forModel'] = ' '.join(str(report.get('forModel') or '').split())[:60]
                reports[str(req.get('tab', 0))[:20]] = allowed
                reports = dict(list(reports.items())[-12:])
                atomic_write(ROOT / 'status.json', {'updated': time.time(), 'tabs': reports})
            response = {'id': req.get('id'), 'config': load_config()}
        except (ValueError, AttributeError, TypeError, OSError):
            response = {'error': 'Invalid request'}
        payload = json.dumps(response, ensure_ascii=False).encode('utf-8')
        out.write(struct.pack('<I', len(payload)) + payload)
        out.flush()

def gui():
    from desktop import run
    # Login startup can disappear (cleaner tools, profile resets); repair it here
    # so the toggle in the settings card always reflects reality.
    reconcile_startup()
    run()

def register_installed():
    global ROOT, EXE
    legacy = ROOT
    inherited = startup_preference()
    was_enabled = startup_enabled() if (legacy/'startup.json').exists() else True
    ROOT = Path(sys.executable).resolve().parent
    EXE = ROOT/'ModelKeeper.exe'
    for name in ('config.json','ui.json','appearance.json'):
        if legacy!=ROOT and (legacy/name).is_file() and not (ROOT/name).exists():
            shutil.copy2(legacy/name,ROOT/name)
    if not (ROOT/'config.json').exists():atomic_write(ROOT/'config.json',DEFAULT)
    shutil.copytree(ASSETS/'extension',ROOT/'extension',dirs_exist_ok=True)
    deploy_extension(restart=False)
    atomic_write(ROOT/'host.json',{'name':HOST,'description':'ChatGPT Model Keeper',
        'path':str(ROOT/'ModelKeeperHost.exe'),'type':'stdio',
        'allowed_origins':extension_origins()})
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Edge\NativeMessagingHosts'+'\\'+HOST) as key:
        winreg.SetValueEx(key,'',0,winreg.REG_SZ,str(ROOT/'host.json'))
    set_startup(was_enabled if inherited is None else inherited)
    try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Uninstall\ChatGPTModelKeeper')
    except FileNotFoundError:pass

def main():
    if '--register-installed' in sys.argv:
        register_installed()
        return 0
    if '--unregister-installed' in sys.argv:
        uninstall()
        return 0
    if '--autostart' in sys.argv:
        value = sys.argv[sys.argv.index('--autostart')+1]
        if value not in ('on', 'off'):
            raise ValueError('Expected --autostart on or off')
        set_startup(value == 'on')
        return 0
    if '--install' in sys.argv:
        install()
        return 0
    if '--install-extension' in sys.argv:
        result = deploy_extension()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('installed') else 1
    if '--uninstall-extension' in sys.argv:
        print(json.dumps(extension_deploy.remove(ROOT), ensure_ascii=False))
        return 0
    if '--selftest' in sys.argv:
        return 0 if all(k in load_config() for k in ('chat','work')) and len(extension_id())==32 else 2
    if '--uninstall' in sys.argv:
        from tkinter import messagebox
        uninstall()
        messagebox.showinfo('已解除安装登记', '本机消息接口和开始菜单入口已移除。\n请在 Edge 扩展页移除“ChatGPT 模型锁定器”，然后删除以下文件夹：\n'+str(ROOT)+'\n\n配置保留在该文件夹中。')
    elif '--native' in sys.argv or any(a.startswith('chrome-extension://') for a in sys.argv[1:]):
        native_main()
    else: gui()
    return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        ROOT.mkdir(parents=True, exist_ok=True)
        import traceback
        (ROOT/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
        sys.exit(1)
