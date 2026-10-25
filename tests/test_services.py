import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import github_updates as updates
from runtime_cache import ensure_runtime
from desktop import validate_config

class Response(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class Services(unittest.TestCase):
    def test_versions(self):
        self.assertGreater(updates.version('v2.1.0'),updates.version('2.0.9'))
        with self.assertRaises(ValueError):updates.version('v2.0.0-rc')
    def test_release_checks(self):
        body={'draft':False,'prerelease':False,'tag_name':'v2.1.0','assets':[{'name':updates.ASSET,'browser_download_url':f'https://github.com/{updates.REPO}/releases/download/v2.1.0/{updates.ASSET}','digest':'sha256:'+'a'*64,'size':3}]}
        with patch('urllib.request.urlopen',return_value=Response(json.dumps(body).encode())):
            self.assertTrue(updates.latest('2.0.0')['newer'])
        body['assets'][0]['browser_download_url']='https://example.com/setup.exe'
        with patch('urllib.request.urlopen',return_value=Response(json.dumps(body).encode())):
            with self.assertRaises(ValueError):updates.latest('2.0.0')
    def test_download_digest_failure_never_leaves_installer(self):
        release={'url':f'https://github.com/{updates.REPO}/releases/download/v2.1.0/{updates.ASSET}','sha256':'a'*64,'size':3}
        with tempfile.TemporaryDirectory() as directory:
            with patch('urllib.request.urlopen',return_value=Response(b'bad')):
                with self.assertRaises(ValueError):updates.download(release,Path(directory))
            self.assertEqual(list(Path(directory).iterdir()),[])
    def test_runtime_cache_verifies_and_reuses(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);assets=base/'assets';assets.mkdir();body=b'renderer'
            manifest={'files':[{'path':'horizon.mjs','url':'https://chatgpt.com/cdn/test.js','size':len(body),'sha256':hashlib.sha256(body).hexdigest()}]}
            (assets/'runtime_manifest.json').write_text(json.dumps(manifest))
            with patch('urllib.request.urlopen',return_value=Response(body)) as fetch:
                ensure_runtime(base,assets);ensure_runtime(base,assets);self.assertEqual(fetch.call_count,1)
    def test_form_validation(self):
        self.assertEqual(validate_config(copy.deepcopy(app.DEFAULT)),app.DEFAULT)
        broken=copy.deepcopy(app.DEFAULT);broken['work']['model']=''
        with self.assertRaises(ValueError):validate_config(broken)
        for forbidden in ('pro','ultra','max'):
            broken=copy.deepcopy(app.DEFAULT);broken['chat']['effort']=forbidden
            with self.assertRaises(ValueError):validate_config(broken)
        broken=copy.deepcopy(app.DEFAULT);broken['work']['effort']='none'
        with self.assertRaises(ValueError):validate_config(broken)
        broken=copy.deepcopy(app.DEFAULT);broken['chat']['effort']='made-up'
        with self.assertRaises(ValueError):validate_config(broken)
    def test_appearance_and_legacy_effort_migration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'ROOT',Path(directory)):
            self.assertEqual(app.load_appearance(),{'theme':'dark'})
            app.atomic_write(app.ROOT/'appearance.json',{'theme':'light'})
            self.assertEqual(app.load_appearance(),{'theme':'light'})
            config=copy.deepcopy(app.DEFAULT);config['chat']['effort']='ultra';config['work']['effort']='max'
            app.atomic_write(app.ROOT/'config.json',config)
            self.assertEqual(app.load_config()['chat']['effort'],'xhigh')
            self.assertEqual(app.load_config()['work']['effort'],'xhigh')
    def test_assisted_install_uses_real_extension_folder(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'ROOT',Path(directory)), patch('os.startfile') as launch:
            folder=app.prepare_extension_install()
            self.assertTrue((folder/'manifest.json').is_file())
            launch.assert_called_once_with('microsoft-edge:edge://extensions/')
    def test_unpacked_deploy_pins_key_and_marks_state(self):
        import extension_deploy as deploy
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'extension'
            shutil.copytree(app.ASSETS/'extension',folder)
            manifest=deploy.sync_manifest(folder,root)
            ext_id=deploy.identifier(base64.b64decode(manifest['key']))
            self.assertEqual(len(ext_id),32)
            self.assertEqual(ext_id,deploy.folder_id(folder))
            # A stored machine key keeps the identifier stable across re-syncs.
            self.assertEqual(deploy.sync_manifest(folder,root)['key'],manifest['key'])
            deploy._write_marker(root,ext_id,manifest['version'],folder)
            self.assertTrue(deploy.registered(root))
            self.assertEqual(deploy.state(root)['id'],ext_id)
            deploy._marker_path(root).unlink()
            self.assertFalse(deploy.registered(root))
    def test_deploy_refuses_missing_extension_folder(self):
        import extension_deploy as deploy
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                deploy.deploy(Path(directory),Path(directory)/'missing')
    def test_guard_preference_survives_marker_rewrite(self):
        import extension_deploy as deploy
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            # Defaults on, and a later rewrite must not lose the explicit opt-out.
            self.assertTrue(deploy.guard_enabled(root))
            deploy.set_guard_enabled(root,False)
            self.assertFalse(deploy.guard_enabled(root))
            deploy._write_marker(root,'a'*32,'2.5.0',root/'extension')
            self.assertFalse(deploy.guard_enabled(root))
            deploy.set_guard_enabled(root,True)
            self.assertTrue(deploy.guard_enabled(root))
            self.assertIsInstance(deploy.visible_edge_windows(),list)
            self.assertEqual(deploy.guard(Path(directory)),{'action':'idle','reason':'not-installed'})
    def test_extension_origins_dedupe_installed_and_bundled_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'ROOT',Path(directory)):
            folder=app.ROOT/'extension';folder.mkdir()
            shutil.copy2(app.ASSETS/'extension'/'manifest.json',folder/'manifest.json')
            self.assertEqual(app.extension_ids(),[app.extension_id()])
            self.assertEqual(len(app.extension_id()),32)
            self.assertEqual(app.extension_origins(),['chrome-extension://'+app.extension_id()+'/'])

if __name__=='__main__':unittest.main()
