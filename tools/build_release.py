"""Whitelist source release and optional local Windows review bundle."""
import hashlib,json,sys,zipfile
from pathlib import Path
from release_check import ROOT,audit

def write_bundle(path,files,kind):
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(p,'OpenDeskMail/'+p.relative_to(ROOT).as_posix())
        z.writestr('OpenDeskMail/RELEASE-MANIFEST.json',json.dumps({'version':'0.1.0','kind':kind,'files':manifest,'binary_redistribution_review_complete':False},indent=2))
    return hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name

def main():
    files=audit();out=ROOT/'dist';out.mkdir(exist_ok=True);sums=[]
    sums.append(write_bundle(out/'OpenDeskMail-0.1.0-source.zip',files,'source'))
    if '--windows-review' in sys.argv:
        runtime=[p for p in (ROOT/'python-runtime').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
        wheels=list((ROOT/'wheelhouse').glob('*.whl'))
        if not runtime or not wheels:raise ValueError('Missing local runtime/wheelhouse')
        inventory=json.loads((ROOT/'licenses/dependency-inventory.json').read_text())
        expected={x['wheel_sha256'] for x in inventory}
        if {hashlib.sha256(p.read_bytes()).hexdigest() for p in wheels}!=expected:raise ValueError('Wheel manifest mismatch')
        sums.append(write_bundle(out/'OpenDeskMail-0.1.0-windows-x64-review.zip',files+runtime+wheels,'windows-local-review'))
    (out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print('\n'.join(sums))

if __name__=='__main__':main()
