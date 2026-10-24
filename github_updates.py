"""Public GitHub Releases channel. No GitHub credentials ship in the application."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlparse

REPO='UNO1742/chatgpt-model-keeper-backup'
RELEASES=f'https://github.com/{REPO}/releases'
ASSET='ModelKeeper-Setup.exe'

def version(text):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',text)
    if not match:raise ValueError('无法识别发布版本')
    return tuple(map(int,match.groups()))

def latest(current):
    req=urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/latest',
        headers={'Accept':'application/vnd.github+json','User-Agent':'ChatGPT-Model-Keeper'})
    with urllib.request.urlopen(req,timeout=20) as r:data=json.load(r)
    if data.get('draft') or data.get('prerelease'):raise ValueError('不是稳定发布版本')
    tag=data['tag_name'];newer=version(tag)>version(current)
    asset=next((x for x in data['assets'] if x['name']==ASSET),None)
    if not asset:raise ValueError('此 Release 尚未包含 Windows 安装程序')
    url=asset['browser_download_url']
    prefix=f'https://github.com/{REPO}/releases/download/{tag}/'
    if not url.startswith(prefix):raise ValueError('安装包地址不属于本项目')
    digest=asset.get('digest','')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):raise ValueError('GitHub 未提供有效的安装包摘要')
    return {'tag':tag,'newer':newer,'url':url,'sha256':digest[7:], 'size':int(asset['size'])}

def download(release, directory):
    if not release['url'].startswith(f'https://github.com/{REPO}/releases/download/'):
        raise ValueError('拒绝非本项目下载地址')
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/ASSET
    partial=path.with_suffix('.part')
    digest=hashlib.sha256();size=0
    try:
        req=urllib.request.Request(release['url'],headers={'User-Agent':'ChatGPT-Model-Keeper'})
        with urllib.request.urlopen(req,timeout=60) as response,partial.open('wb') as out:
            while block:=response.read(1024*1024):
                size+=len(block)
                if size>release['size']:raise ValueError('安装包大小超出预期')
                digest.update(block);out.write(block)
        if size!=release['size'] or digest.hexdigest()!=release['sha256']:
            raise ValueError('安装包校验失败，已取消更新')
        partial.replace(path)
        return path
    finally:
        partial.unlink(missing_ok=True)
