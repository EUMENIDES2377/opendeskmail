"""Independent account lock and durable spacing; never touches other editions."""
import hashlib,json,msvcrt,os,threading,time
from pathlib import Path
_active=None

def require_lease(sender):
    if _active is None or _active.sender!=sender.strip().lower() or _active.thread!=threading.get_ident():
        raise RuntimeError('请从独立版桌面界面操作，当前未持有账号发送锁。')

class AccountLease:
    def __init__(self,sender,directory=None):
        self.sender=sender.strip().lower();self.thread=threading.get_ident()
        from app_paths import DATA_ROOT
        root=Path(directory or DATA_ROOT/'locks');root.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(self.sender.encode()).hexdigest();self.lock=root/(key+'.lock');self.state=root/(key+'.json');self.file=None
    def __enter__(self):
        global _active
        self.file=self.lock.open('a+b');self.file.seek(0)
        if self.lock.stat().st_size==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:self.file.close();raise RuntimeError('该账号已有独立版任务在运行，请先暂停另一任务。')
        try:
            self.next_after=float(json.loads(self.state.read_text('utf-8')).get('next_after',0)) if self.state.exists() else 0
        except Exception:self.__exit__(None,None,None);raise RuntimeError('发送间隔记录异常，请核查后再启动。')
        _active=self;return self
    def wait(self,stop):
        while time.time()<self.next_after:
            if stop.wait(min(0.5,max(0,self.next_after-time.time()))):raise InterruptedError('已暂停后续发送')
        if stop.is_set():raise InterruptedError('已暂停后续发送')
    def reserve(self,interval=60):
        require_lease(self.sender)
        if time.time()<self.next_after:raise RuntimeError('尚未达到发送间隔')
        self.finished(interval)
    def finished(self,interval=60):
        self.next_after=time.time()+max(60,float(interval));temp=self.state.with_suffix('.tmp')
        with temp.open('w',encoding='utf-8') as f:json.dump({'next_after':self.next_after},f);f.flush();os.fsync(f.fileno())
        os.replace(temp,self.state)
    def __exit__(self,*args):
        global _active
        _active=None
        if self.file and not self.file.closed:
            self.file.seek(0)
            try:msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            finally:self.file.close()
