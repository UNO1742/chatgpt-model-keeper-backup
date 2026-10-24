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
an unpacked extension, which keeps working on the following starts, and no
browser UI is involved. So deployment is: pin the manifest key (stable ID that
matches the native messaging allow-list), then restart Edge with that flag.

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
_NO_WINDOW = 0x08000000


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
                            capture_output=True, text=True, timeout=120,
                            creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode != 0 or len(result.stdout.split()) != 2:
        raise RuntimeError('无法生成扩展签名密钥：' + (result.stderr.strip()[:200] or 'PowerShell 未返回密钥'))
    modulus, private = result.stdout.split()
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
    _marker_path(root).write_text(json.dumps({'id': ext_id, 'version': version,
                                              'folder': str(folder),
                                              'deployed': time.strftime('%Y-%m-%dT%H:%M:%S')},
                                             ensure_ascii=False), encoding='utf-8')


def state(root):
    """What the settings card needs to render install / uninstall."""
    root = Path(root)
    ext_id = folder_id(root / 'extension')
    data = marker(root)
    deployed = bool(data) and (root / 'extension' / 'manifest.json').is_file()
    live = live_state(ext_id)
    return {'installed': bool(deployed), 'enabled': bool(live and live['enabled']),
            'id': ext_id, 'version': data.get('version', ''), 'running': edge_running()}


def edge_running():
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq msedge.exe', '/NH'],
                                capture_output=True, text=True, timeout=20,
                                creationflags=_NO_WINDOW if os.name == 'nt' else 0)
        return 'msedge.exe' in result.stdout.lower()
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


def _close_edge(timeout=25):
    subprocess.run(['taskkill', '/IM', 'msedge.exe'], capture_output=True, timeout=20,
                   creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(timeout * 5):
        if not edge_running():
            return True
        time.sleep(0.2)
    return not edge_running()


def _launch(extra=()):
    binary = edge_binary()
    if not binary:
        raise RuntimeError('未找到 Microsoft Edge。')
    subprocess.Popen([str(binary), *extra], creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    return True


def deploy(root, folder=None, restart=True):
    """Register the folder as an unpacked extension and (optionally) restart Edge.

    `restart=False` never closes a browser the user is working in: the marker is
    written and, when Edge happens to be closed, the flag is applied right away.
    """
    root = Path(root)
    folder = Path(folder or root / 'extension')
    if not (folder / 'manifest.json').is_file():
        raise RuntimeError('扩展文件缺失，请重新安装本程序。')
    manifest = sync_manifest(folder, root)
    ext_id = identifier(base64.b64decode(manifest['key']))
    version = str(manifest.get('version', '1.0'))
    was_running = edge_running()
    if was_running and not restart:
        _write_marker(root, ext_id, version, folder)
        return {'installed': True, 'enabled': False, 'id': ext_id, 'version': version,
                'running': True, 'restarted': False, 'needsRestart': True}
    if was_running:
        _close_edge()
    _launch([LOAD_FLAG + str(folder)])
    _write_marker(root, ext_id, version, folder)
    return {'installed': True, 'enabled': True, 'id': ext_id, 'version': version,
            'running': True, 'restarted': was_running}


def refresh(root, folder=None):
    """Re-apply after an app update, but never resurrect a removed extension.

    Runs at every start, so it must not close a browser the user is using: an
    extension Edge already knows about is left alone, and a missing one is only
    applied while Edge is closed.
    """
    root = Path(root)
    data = marker(root)
    if not data:
        return {'installed': False, 'enabled': False, 'id': '', 'version': '', 'running': edge_running()}
    ext_id = folder_id(root / 'extension') or data.get('id', '')
    live = live_state(ext_id)
    if live and live['enabled']:
        return {'installed': True, 'enabled': True, 'id': ext_id,
                'version': live['version'] or data.get('version', ''), 'running': edge_running()}
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
