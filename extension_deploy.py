"""Deploy the companion Edge extension without developer mode.

Chromium browsers read externally installed extensions from the registry
(HKCU\\Software\\Microsoft\\Edge\\Extensions\\<id> with `path` + `version`), scan it
on browser start and install the referenced CRX without asking for developer
mode. The CRX3 file must be signed, so this module mints one RSA key per machine
and writes its public half into the installed manifest. That public key decides
the extension ID, which keeps the native messaging allow-list consistent
without shipping any signing secret with the app.

Format reference: Chrome's CRX3 header (Cr24 / protobuf CrxFileHeader). An
equivalent PyPI implementation exists as `crx3` (MIT); this module stays
dependency-free so the frozen build carries no extra crypto stack.
"""
import base64
import hashlib
import io
import json
import os
import struct
import subprocess
import time
import winreg
import zipfile
from pathlib import Path

EDGE_KEY = 'Software\\Microsoft\\Edge\\Extensions'
KEY_FILE = 'extension_key.json'
CRX_FILE = 'extension.crx'
RSA_BITS = 2048
SIGNATURE_CONTEXT = b'CRX3 SignedData\x00'
DIGEST_INFO = bytes.fromhex('3031300d060960864801650304020105000420')
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


def _varint(value):
    out = bytearray()
    while True:
        block = value & 0x7f
        value >>= 7
        out.append(block | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number, payload):
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _sign(data, n, d):
    digest = DIGEST_INFO + hashlib.sha256(data).digest()
    block = b'\x00\x01' + b'\xff' * (RSA_BITS // 8 - len(digest) - 3) + b'\x00' + digest
    return pow(int.from_bytes(block, 'big'), d, n).to_bytes(RSA_BITS // 8, 'big')


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


def _payload(folder):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(folder).rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    return buffer.getvalue()


def pack(folder, target, root):
    """Write a signed CRX3 next to the extension and return (id, version)."""
    folder = Path(folder)
    manifest = sync_manifest(folder, root)
    n, d, e = load_key(root)
    public = public_key(n, e)
    crx_id = hashlib.sha256(public).digest()[:16]
    payload = _payload(folder)
    signed_header = _field(1, crx_id)
    signature = _sign(SIGNATURE_CONTEXT + struct.pack('<I', len(signed_header)) + signed_header + payload, n, d)
    header = _field(2, _field(1, public) + _field(2, signature)) + _field(10000, signed_header)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.part')
    temporary.write_bytes(b'Cr24' + struct.pack('<II', 3, len(header)) + header + payload)
    os.replace(temporary, target)
    return identifier(public), str(manifest.get('version', '1.0'))


def registered(ext_id):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, EDGE_KEY + '\\' + ext_id) as key:
            path, _ = winreg.QueryValueEx(key, 'path')
            version, _ = winreg.QueryValueEx(key, 'version')
            return {'path': path, 'version': version}
    except (FileNotFoundError, OSError):
        return None


def state(root):
    """What the settings card needs to render install / uninstall."""
    root = Path(root)
    ext_id = folder_id(root / 'extension')
    entry = registered(ext_id) if ext_id else None
    return {'installed': bool(entry), 'id': ext_id, 'version': (entry or {}).get('version', ''),
            'running': edge_running()}


def deploy(root, folder=None):
    """Pack and register the extension. Safe to call repeatedly."""
    root = Path(root)
    folder = Path(folder or root / 'extension')
    if not (folder / 'manifest.json').is_file():
        raise RuntimeError('扩展文件缺失，请重新安装本程序。')
    crx = root / CRX_FILE
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    version = str(manifest.get('version', '1.0'))
    ext_id = identifier(base64.b64decode(sync_manifest(folder, root)['key']))
    stale = not crx.is_file() or (registered(ext_id) or {}).get('version') != version
    if not stale:
        newest = max((path.stat().st_mtime for path in folder.rglob('*') if path.is_file()), default=0)
        stale = newest > crx.stat().st_mtime
    if stale:
        ext_id, version = pack(folder, crx, root)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, EDGE_KEY + '\\' + ext_id) as key:
        winreg.SetValueEx(key, 'path', 0, winreg.REG_SZ, str(crx))
        winreg.SetValueEx(key, 'version', 0, winreg.REG_SZ, version)
    return {'installed': True, 'id': ext_id, 'version': version, 'running': edge_running()}


def remove(root):
    """Drop the registry entry; Chromium uninstalls it on the next start."""
    root = Path(root)
    ext_id = folder_id(root / 'extension')
    if not ext_id:
        return {'installed': False, 'id': '', 'version': '', 'running': edge_running()}
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, EDGE_KEY + '\\' + ext_id)
    except FileNotFoundError:
        pass
    return {'installed': False, 'id': ext_id, 'version': '', 'running': edge_running()}


def edge_running():
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq msedge.exe', '/NH'],
                                capture_output=True, text=True, timeout=20,
                                creationflags=_NO_WINDOW if os.name == 'nt' else 0)
        return 'msedge.exe' in result.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def edge_binary():
    for candidate in (Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
                      Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe'):
        if candidate.is_file():
            return candidate
    return None


def restart_edge():
    """Close Edge gracefully and reopen it so the registry scan runs again."""
    binary = edge_binary()
    if not binary:
        raise RuntimeError('未找到 Microsoft Edge。')
    subprocess.run(['taskkill', '/IM', 'msedge.exe'], capture_output=True, timeout=20,
                   creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(30):
        if not edge_running():
            break
        time.sleep(0.2)
    subprocess.Popen([str(binary)], creationflags=_NO_WINDOW if os.name == 'nt' else 0)
    return {'restarted': True, 'running': True}
