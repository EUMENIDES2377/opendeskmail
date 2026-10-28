"""Generate fictional assets and reproducible lock from audited dependencies."""
from pathlib import Path
import hashlib,json,shutil,struct,zlib
ROOT=Path(__file__).resolve().parents[1]

def chunk(kind,data):
    return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)

def main():
    # Generic geometric example, no brand artwork or user resource.
    width,height=160,48
    rows=b''.join(b'\0'+b''.join(bytes((40,110,190) if 8<x<152 and 8<y<40 else (245,248,252)) for x in range(width)) for y in range(height))
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')
    (ROOT/'examples/signature/logo.example.png').write_bytes(data)
    inventory=json.loads((ROOT/'licenses/dependency-inventory.json').read_text())
    lock=['# Windows x64 CPython 3.12 audited wheels; update with dependency/license review.']
    for item in inventory:lock.append(f"{item['name']}=={item['version']} --hash=sha256:{item['wheel_sha256']}")
    (ROOT/'requirements-windows-py312.lock.txt').write_text('\n'.join(lock)+'\n',encoding='utf-8')
    target=ROOT/'licenses/runtime';target.mkdir(exist_ok=True)
    for source,name in [(ROOT/'python-runtime/LICENSE.txt','CPython-LICENSE.txt'),(ROOT/'python-runtime/tcl/tk8.6/license.terms','TclTk-license.terms')]:
        if source.exists():shutil.copyfile(source,target/name)

if __name__=='__main__':main()
