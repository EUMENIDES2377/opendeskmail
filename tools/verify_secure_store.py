"""Exercise only a fresh fictional credential target, then remove that target."""
import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from v2_model import SecureStore

def main():
    unique=uuid.uuid4().hex
    cfg={'sender':unique+'@example.invalid','host':'smtp.example.invalid','port':465,'security':'SSL/TLS'}
    store=SecureStore()
    try:
        first=uuid.uuid4().hex;second=uuid.uuid4().hex
        store.write(cfg,first);assert store.read(cfg)==first
        store.write(cfg,second);assert store.read(cfg)==second
    finally:store.delete(cfg)
    assert store.read(cfg) is None
    print('Windows Credential Manager: write/read/update/delete verified using one isolated fictional target. No SMTP used.')

if __name__=='__main__':main()
