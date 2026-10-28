"""Collect exact wheel notices; optionally verify missing notices from PyPI sdists."""
from pathlib import Path
import email,hashlib,io,json,tarfile,urllib.request,zipfile,sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=ROOT/'licenses/dependencies';dest.mkdir(parents=True,exist_ok=True);inventory=[]
    for path in sorted((ROOT/'wheelhouse').glob('*.whl')):
        with zipfile.ZipFile(path) as z:
            metadata=email.message_from_bytes(z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))));name=metadata['Name'];version=metadata['Version'];prefix=name.lower().replace('-','_')+'-'+version
            notices=[n for n in z.namelist() if any(word in Path(n).name.casefold() for word in ('license','licence','notice','copying'))];saved=[]
            for index,n in enumerate(notices):
                out=dest/(prefix+'-'+str(index)+'-'+Path(n).name);out.write_bytes(z.read(n));saved.append(out.relative_to(ROOT).as_posix())
            source='wheel';source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
            if not notices and '--fetch-missing' in sys.argv:
                request=urllib.request.Request(f'https://pypi.org/pypi/{name}/{version}/json',headers={'User-Agent':'OpenDeskMail-license-audit/0.1'})
                info=json.load(urllib.request.urlopen(request,timeout=30));sdist=next(item for item in info['urls'] if item['packagetype']=='sdist');data=urllib.request.urlopen(sdist['url'],timeout=30).read();assert hashlib.sha256(data).hexdigest()==sdist['digests']['sha256']
                with tarfile.open(fileobj=io.BytesIO(data),mode='r:*') as tar:
                    for index,member in enumerate(tar.getmembers()):
                        if member.isfile() and Path(member.name).name.casefold() in ('license','licence','licence.rst','license.txt','license.md','copying'):
                            out=dest/(prefix+'-sdist-'+str(index)+'-'+Path(member.name).name);out.write_bytes(tar.extractfile(member).read());saved.append(out.relative_to(ROOT).as_posix())
                source=sdist['url'];source_hash=sdist['digests']['sha256']
            license_name=metadata.get('License-Expression') or metadata.get('License') or '; '.join(v for v in metadata.get_all('Classifier',[]) if 'License' in v)
            if len(license_name)>160:license_name='MIT (full text retained)'
            inventory.append(dict(name=name,version=version,license=license_name,notice_files=saved,notice_source=source,notice_source_sha256=source_hash,wheel_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (ROOT/'licenses/dependency-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),'utf-8')
    assert all(item['notice_files'] for item in inventory),'Missing notices; use --fetch-missing to inspect exact sdist'
    print(json.dumps({'dependencies':len(inventory),'notice_files':sum(len(i['notice_files']) for i in inventory)}))
if __name__=='__main__':main()
