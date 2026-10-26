"""Keep the pinned rendering resources on disk; only fall back to the network."""
import hashlib
import json
from pathlib import Path
import os
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor

def ensure_runtime(root, assets):
    manifest=json.loads((assets/'runtime_manifest.json').read_text(encoding='utf-8'))
    cache=root/'runtime'
    # The same pinned files ship inside the installer, so a first launch needs
    # neither the network nor a warm cache. A packed copy is only trusted while
    # its digest still matches; anything else is fetched and verified as before.
    seed=assets/'runtime_seed'
    def matches(path, entry):
        try:
            return path.is_file() and path.stat().st_size==entry['size'] and hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
        except OSError:
            return False
    def place(path, entry, source):
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.download')
        if source is None:
            req=urllib.request.Request(entry['url'],headers={'User-Agent':'ChatGPT-Model-Keeper/2.0'})
            with urllib.request.urlopen(req,timeout=25) as response:
                data=response.read(entry['size']+1)
            if len(data)!=entry['size'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                raise ValueError('网页渲染资源未通过完整性校验')
            temporary.write_bytes(data)
        else:
            shutil.copyfile(source,temporary)
        os.replace(temporary,path)
    def fetch(entry):
        path=cache/entry['path']
        if matches(path,entry):
            return
        packed=seed/entry['path']
        place(path,entry,packed if matches(packed,entry) else None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch,manifest['files']))
    return cache
