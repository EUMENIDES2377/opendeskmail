"""Install the local-review ZIP in a temporary directory; simulated tests only."""
from pathlib import Path
import hashlib,json,os,subprocess,tempfile,zipfile
ROOT=Path(__file__).resolve().parents[1]

def main():
    archive=ROOT/'dist/OpenDeskMail-0.1.0-windows-x64-review.zip'
    with tempfile.TemporaryDirectory(prefix='OpenDeskMail-release-check-') as temporary:
        temp=Path(temporary)
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                resolved=(temp/member).resolve()
                if temp.resolve() not in resolved.parents:raise ValueError('Unsafe archive member')
            z.extractall(temp)
        app=temp/'OpenDeskMail';manifest=json.loads((app/'RELEASE-MANIFEST.json').read_text())
        for rel,expected in manifest['files'].items():
            if hashlib.sha256((app/rel).read_bytes()).hexdigest()!=expected:raise ValueError('Manifest mismatch')
        env=dict(os.environ,OPENDESK_MAIL_DATA_DIR=str(temp/'user-state'))
        completed=subprocess.run([str(app/'python-runtime/python.exe'),'setup_local.py','--no-shortcut'],cwd=app,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        if completed.returncode:
            print(completed.stdout);raise SystemExit(completed.returncode)
        check=subprocess.run([str(app/'.venv/Scripts/python.exe'),'-c','from app_paths import USER_HOME,CODE_ROOT; from v2_model import load_config; assert CODE_ROOT not in USER_HOME.parents; assert not load_config().get("sender"); import tkinter; print("fresh-profile-ok")'],cwd=app,env=env,capture_output=True,text=True)
        if check.returncode:raise RuntimeError('Fresh profile verification failed')
        print(json.dumps({'ok':True,'archive_hash_verified':True,'fresh_offline_install':True,'simulated_suite':True,'fresh_profile':True,'shortcuts_created':False,'real_smtp_used':False}))

if __name__=='__main__':main()
