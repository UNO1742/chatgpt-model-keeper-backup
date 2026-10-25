"""Load the companion Edge extension without the store, developer mode or clicks.

Edge 156 refuses side-loading in every classic way that used to work:

* an externally installed CRX (``HKCU\\Software\\Microsoft\\Edge\\Extensions``) is
  accepted at first, marked "not verified" and its unpacked files are purged
  afterwards, so the extension never actually runs;
* writing the enabled state into ``Secure Preferences`` is pointless, because the
  per-extension MAC in ``protection.macs`` is recomputed from an internal seed;
* ``ExtensionInstallForcelist`` only force-installs store or managed extensions.

What does work is the command line Edge itself uses for "load unpacked": start
the browser once with ``--load-extension=<folder>``. Edge registers the folder as
an unpacked extension with no browser UI involved. That flag is per browser
process, though, so a later plain launch does not inherit it.

The stable trick is an "anchor": keep one windowless Edge process alive that was
started with the flag (``--no-startup-window``, the same mode Edge uses for its
own startup boost). Every later launch - taskbar, Start menu, a link in another
app - hands its command line to that surviving process, so it opens a window
inside a browser that already has the extension loaded. Measured on Edge
156: a plain launch after the anchor reports ``location=8`` (COMMAND_LINE),
no disable reasons and ``has_started_service_worker`` true.

`guard()` keeps that anchor in place: it re-anchors when Edge exits, repairs a
browser that was started without the flag, and gives up quietly after repeated
failures instead of fighting the machine.

The RSA key is still minted per machine: the public half goes into the installed
manifest and decides the extension ID, so no signing secret ships with the app
and every machine gets a stable, predictable ID.
"""
import base64
import hashlib
import json
import os
import subprocess
import time
import winreg
from pathlib import Path

KEY_FILE = 'extension_key.json'
MARKER_FILE = 'extension_state.json'
RSA_BITS = 2048
LOAD_FLAG = '--load-extension='
ANCHOR_FLAG = '--no-startup-window'
RESTORE_FLAG = '--restore-last-session'
DETACHED = 0x00000008
_NO_WINDOW = 0x08000000
LOADED_LOCATIONS = (4, 8)          # UNPACKED, COMMAND_LINE
# Rate limits shared by every caller: a launch needs a few seconds to become
# visible in the profile, and repeated failures must not turn into a loop.
_guard = {'launch': 0.0, 'attempts': 0, 'suspend': 0.0}


def _der_length(size):
    if size < 0x80:
        return bytes([size])
    body = size.to_bytes((size.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(body)]) + body


def _der(tag, body):
    return bytes([tag]) + _der_length(len(body)) + body


def _der_integer(value):
    body = value.to_bytes(max(1, (value.bit_length() + 7) // 8), 'big')
    if body[0] & 0x80:
        body = b'\x00' + body
    return _der(0x02, body)


def public_key(n, e):
    """SubjectPublicKeyInfo DER, the exact blob Chromium hashes into the ID."""
    rsa = _der(0x30, _der_integer(n) + _der_integer(e))
    algorithm = _der(0x30, bytes.fromhex('06092A864886F70D010101') + b'\x05\x00')
    return _der(0x30, algorithm + _der(0x03, b'\x00' + rsa))


def identifier(public):
    digest = hashlib.sha256(public).digest()[:16].hex()
    return ''.join(chr(ord('a') + int(digit, 16)) for digit in digest)


def _create_key():
    script = ('$r=[System.Security.Cryptography.RSA]::Create(' + str(RSA_BITS) + ');'
              '$p=$r.ExportParameters($true);'
              '[Convert]::ToBase64String($p.Modulus)+" "+[Convert]::ToBase64String($p.D)')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, timeout=120,
                            creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    stdout = (result.stdout or b'').decode('mbcs', 'replace')
    if result.returncode != 0 or len(stdout.split()) != 2:
        raise RuntimeError('无法生成扩展签名密钥：' + (result.stderr or b'').decode('mbcs', 'replace').strip()[:200] or 'PowerShell 未返回密钥')
    modulus, private = stdout.split()
    return (int.from_bytes(base64.b64decode(modulus), 'big'),
            int.from_bytes(base64.b64decode(private), 'big'), 65537)


def load_key(root):
    path = Path(root) / KEY_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return int(data['n'], 16), int(data['d'], 16), int(data['e'], 16)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    key = _create_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'n': format(key[0], 'x'), 'd': format(key[1], 'x'),
                                'e': format(key[2], 'x')}), encoding='utf-8')
    return key


def manifest_key(folder):
    """Public key recorded in a manifest folder, or '' when it has none."""
    try:
        manifest = json.loads((Path(folder) / 'manifest.json').read_text(encoding='utf-8'))
        return manifest.get('key') or ''
    except (OSError, ValueError, AttributeError):
        return ''


def folder_id(folder):
    key = manifest_key(folder)
    try:
        return identifier(base64.b64decode(key)) if key else ''
    except ValueError:
        return ''


def sync_manifest(folder, root):
    """Pin the machine key into the installed manifest so the ID is stable."""
    folder = Path(folder)
    path = folder / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    n, _, e = load_key(root)
    wanted = base64.b64encode(public_key(n, e)).decode()
    if manifest.get('key') != wanted:
        manifest['key'] = wanted
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def edge_profile_roots():
    """Every `User Data` directory Edge may keep a profile in."""
    local = os.environ.get('LOCALAPPDATA')
    candidates = []
    if local:
        candidates.append(Path(local) / 'Microsoft' / 'Edge' / 'User Data')
        candidates.append(Path(local) / 'Microsoft' / 'Edge Beta' / 'User Data')
    return [path for path in candidates if path.is_dir()]


def _profile_files():
    files = []
    for root in edge_profile_roots():
        for pref in root.glob('*/Secure Preferences'):
            files.append(pref)
    return files


def _read_entry(pref, ext_id):
    try:
        data = json.loads(pref.read_text(encoding='utf-8', errors='replace'))
    except (OSError, ValueError):
        return None
    entry = data.get('extensions', {}).get('settings', {}).get(ext_id)
    if not entry:
        return None
    return {'enabled': not entry.get('disable_reasons') and entry.get('state', 1) == 1,
            'version': str(entry.get('manifest', {}).get('version', '')),
            'location': entry.get('location'),
            'file': str(pref)}


def live_state(ext_id):
    """Whether Edge currently knows this extension, as far as the profile says."""
    if not ext_id:
        return None
    for pref in _profile_files():
        entry = _read_entry(pref, ext_id)
        if entry:
            return entry
    return None


def loaded_any(ext_id):
    """True when a profile holds a live entry that came from loading the folder.

    Only meaningful while Edge runs: Chromium writes the entry of a
    command-line extension during the session and leaves it behind after the
    browser exits, so a closed profile alone proves nothing.
    """
    if not ext_id:
        return False
    for pref in _profile_files():
        entry = _read_entry(pref, ext_id)
        if entry and entry['enabled'] and entry['location'] in LOADED_LOCATIONS:
            return True
    return False


def visible_edge_windows():
    """Titles of Edge windows the user can actually see."""
    if os.name != 'nt':
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value != 'Chrome_WidgetWin_1':
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if title.value:
            titles.append(title.value)
        return True

    try:
        user32.EnumWindows(collect, 0)
    except OSError:
        return []
    return titles


def _marker_path(root):
    return Path(root) / MARKER_FILE


def marker(root):
    try:
        return json.loads(_marker_path(root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def registered(root):
    """True while this machine is marked as deployed (used for UI state)."""
    root = Path(root)
    return bool(marker(root).get('id')) and (root / 'extension' / 'manifest.json').is_file()


def _write_marker(root, ext_id, version, folder):
    keep = marker(root)
    data = {'id': ext_id, 'version': version, 'folder': str(folder),
            'deployed': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if isinstance(keep.get('autoRestart'), bool):
        data['autoRestart'] = keep['autoRestart']
    _marker_path(root).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def guard_enabled(root):
    """Whether the watchdog may repair a browser that is already open."""
    value = marker(Path(root)).get('autoRestart')
    return True if not isinstance(value, bool) else value


def set_guard_enabled(root, enabled):
    root = Path(root)
    data = marker(root)
    data['autoRestart'] = bool(enabled)
    _marker_path(root).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data['autoRestart']


def state(root):
    """What the settings card needs to render install / uninstall."""
    root = Path(root)
    ext_id = folder_id(root / 'extension')
    data = marker(root)
    deployed = bool(data) and (root / 'extension' / 'manifest.json').is_file()
    running = edge_running()
    return {'installed': bool(deployed), 'enabled': bool(running and loaded_any(ext_id)),
            'id': ext_id, 'version': data.get('version', ''), 'running': running,
            'guard': guard_enabled(root)}


def edge_running():
    """Whether any Edge process exists.

    `tasklist` prints localised text, so the output is matched as bytes: asking
    for `text=True` without an encoding makes Python decode CP936 output as
    UTF-8, the decode error is swallowed by the reader thread, `stdout` comes
    back as None and the settings card dies with an AttributeError.
    """
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq msedge.exe', '/NH'],
                                capture_output=True, timeout=20,
                                creationflags=_NO_WINDOW if os.name == 'nt' else 0)
        return b'msedge.exe' in (result.stdout or b'').lower()
    except (OSError, subprocess.SubprocessError):
        return False


def edge_binary():
    for base in (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'),
                 r'C:\Program Files (x86)', r'C:\Program Files'):
        if not base:
            continue
        candidate = Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'
        if candidate.is_file():
            return candidate
    return None


def _close_edge(grace=6, timeout=20):
    """Close Edge, then force it once the polite request has been ignored.

    Edge normally keeps a background process alive (`--no-startup-window`) that
    has no window to close, so the plain `taskkill` below never succeeds on its
    own. That mattered: a new instance launched afterwards just hands its
    command line to the surviving process and `--load-extension` is dropped,
    which looked exactly like "the button did nothing".
    """
    flags = _NO_WINDOW if os.name == 'nt' else 0
    subprocess.run(['taskkill', '/IM', 'msedge.exe'], capture_output=True, timeout=20,
                   creationflags=flags)
    deadline = time.time() + grace
    while time.time() < deadline:
        if not edge_running():
            return True
        time.sleep(0.3)
    subprocess.run(['taskkill', '/F', '/T', '/IM', 'msedge.exe'], capture_output=True,
                   timeout=20, creationflags=flags)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not edge_running():
            return True
        time.sleep(0.3)
    return not edge_running()


def _launch(extra=()):
    """Start Edge detached, so it outlives this program and its process tree."""
    binary = edge_binary()
    if not binary:
        raise RuntimeError('未找到 Microsoft Edge。')
    flags = DETACHED if os.name == 'nt' else 0
    subprocess.Popen([str(binary), *extra], creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _guard['launch'] = time.time()
    return True


def anchor(root, folder=None):
    """Leave a windowless Edge running that already has the extension loaded."""
    root = Path(root)
    folder = Path(folder or root / 'extension')
    if not (folder / 'manifest.json').is_file():
        raise RuntimeError('扩展文件缺失，请重新安装本程序。')
    if edge_running():
        return {'started': False, 'reason': 'running'}
    _launch([LOAD_FLAG + str(folder), ANCHOR_FLAG])
    return {'started': True}


def _await_live(ext_id, timeout=25):
    """Edge writes the manifest entry a few seconds after the browser starts."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if loaded_any(ext_id):
            return live_state(ext_id)
        time.sleep(0.5)
    return live_state(ext_id)


def guard(root, folder=None):
    """Keep the extension available for every Edge start.

    Runs on a timer, so every branch is cheap and idempotent: an Edge that is
    already carrying the extension is never touched, a closed Edge gets an
    anchor, and an open Edge that lost the extension is restarted once (with
    the previous session restored) before the watchdog backs off.
    """
    root = Path(root)
    folder = Path(folder or root / 'extension')
    if not registered(root):
        return {'action': 'idle', 'reason': 'not-installed'}
    ext_id = folder_id(folder)
    running = edge_running()
    if running and loaded_any(ext_id):
        _guard['attempts'] = 0
        return {'action': 'idle', 'reason': 'loaded'}
    now = time.time()
    if now < _guard['suspend']:
        return {'action': 'idle', 'reason': 'suspended'}
    if now - _guard['launch'] < 25:
        return {'action': 'idle', 'reason': 'starting'}
    if not running:
        _launch([LOAD_FLAG + str(folder), ANCHOR_FLAG])
        claimed = loaded_any(ext_id) or _await_live(ext_id, 25) is not None
        if claimed:
            _guard['attempts'] = 0
            return {'action': 'anchored'}
        _guard['attempts'] += 1
        if _guard['attempts'] >= 3:
            _guard['suspend'] = time.time() + 600
        return {'action': 'anchor-failed'}
    if not guard_enabled(root):
        return {'action': 'idle', 'reason': 'auto-restart off'}
    windows = visible_edge_windows()
    _close_edge()
    _launch([LOAD_FLAG + str(folder)] + ([RESTORE_FLAG] if windows else [ANCHOR_FLAG]))
    applied = _await_live(ext_id, 25)
    if applied and applied['enabled']:
        _guard['attempts'] = 0
        return {'action': 'restarted', 'windows': len(windows)}
    _guard['attempts'] += 1
    if _guard['attempts'] >= 3:
        _guard['suspend'] = time.time() + 600
    return {'action': 'restart-failed', 'windows': len(windows)}


def deploy(root, folder=None, restart=True):
    """Make the extension available and report whether it is loaded now.

    `restart=False` never closes a browser the user is working in: the marker is
    written and, when Edge happens to be closed, the anchor is left running so
    the next launch already carries the extension.
    """
    root = Path(root)
    folder = Path(folder or root / 'extension')
    if not (folder / 'manifest.json').is_file():
        raise RuntimeError('扩展文件缺失，请重新安装本程序。')
    manifest = sync_manifest(folder, root)
    ext_id = identifier(base64.b64decode(manifest['key']))
    version = str(manifest.get('version', '1.0'))
    _write_marker(root, ext_id, version, folder)
    running = edge_running()
    if running and loaded_any(ext_id):
        # Already loaded: never bounce a browser for nothing.
        return {'installed': True, 'enabled': True, 'id': ext_id, 'version': version,
                'running': True, 'restarted': False}
    if not running:
        _launch([LOAD_FLAG + str(folder), ANCHOR_FLAG])
        applied = _await_live(ext_id, 25)
        return {'installed': True, 'enabled': bool(applied and applied['enabled']), 'id': ext_id,
                'version': version, 'running': edge_running(), 'restarted': False, 'anchored': True}
    if not restart:
        return {'installed': True, 'enabled': False, 'id': ext_id, 'version': version,
                'running': True, 'restarted': False, 'needsRestart': True}
    windows = visible_edge_windows()
    _close_edge()
    _launch([LOAD_FLAG + str(folder)] + ([RESTORE_FLAG] if windows else [ANCHOR_FLAG]))
    applied = _await_live(ext_id, 25)
    return {'installed': True, 'enabled': bool(applied and applied['enabled']), 'id': ext_id,
            'version': version, 'running': edge_running(), 'restarted': bool(windows),
            'anchored': not windows}


def refresh(root, folder=None):
    """Re-apply after an app update, but never resurrect a removed extension.

    Runs at every start, so it must not close a browser the user is using.
    """
    root = Path(root)
    data = marker(root)
    if not data:
        return {'installed': False, 'enabled': False, 'id': '', 'version': '', 'running': edge_running()}
    return deploy(root, folder, restart=False)


def remove(root):
    """Close Edge, forget the unpacked entry and drop the marker."""
    root = Path(root)
    ext_id = folder_id(root / 'extension') or marker(root).get('id', '')
    if edge_running():
        _close_edge()
    for pref in _profile_files():
        try:
            data = json.loads(pref.read_text(encoding='utf-8', errors='replace'))
        except (OSError, ValueError):
            continue
        settings = data.get('extensions', {}).get('settings', {})
        if ext_id not in settings:
            continue
        settings.pop(ext_id, None)
        macs = data.get('protection', {}).get('macs', {}).get('extensions', {}).get('settings', {})
        macs.pop(ext_id, None)
        try:
            pref.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        except OSError:
            continue
    try:
        _marker_path(root).unlink()
    except FileNotFoundError:
        pass
    return {'installed': False, 'enabled': False, 'id': ext_id, 'version': '', 'running': edge_running()}


def restart_edge():
    """Plain restart, used by the "restart Edge" menu entry."""
    was_running = edge_running()
    if was_running:
        _close_edge()
    _launch()
    return {'restarted': was_running, 'running': True}
