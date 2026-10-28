"""Standalone GUI entrypoint. No campaign-specific files or Codex dependency."""
import hashlib,json,sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import app
from core import BASE,Customer,address_file,read_customers,smtp_connect,now
from app_paths import USER_HOME as BASE
from account_guard import AccountLease
from desktop_runtime import ExcelResults,submit,verify_copies,atomic_json
from first_run import ensure_configured,import_signature

app.DEFAULT_SETTINGS['market']=''
class DesktopApp(app.App):
    def __init__(self,root):
        self.progress_state={'success':0,'failed':0,'unknown':0,'skipped':0,'remaining':0,'current':'尚未发送'}
        super().__init__(root);root.title('OpenDesk Mail · '+self.v['market'].get())
        self.progress=tk.StringVar();ttk.Label(root,textvariable=self.progress,font=('Microsoft YaHei UI',11,'bold'),padding=8,wraplength=1000).pack(fill='x');self.update_progress()
        ttk.Button(root,text='修改市场名称',command=self.edit_market).pack(anchor='e',padx=12,pady=3)
    def edit_market(self):
        from tkinter.simpledialog import askstring
        if self.busy:return
        name=askstring('市场名称','填写市场名称：',initialvalue=self.v['market'].get(),parent=self.root)
        if name and name.strip():self.v['market'].set(name.strip());self.root.title('OpenDesk Mail · '+name.strip());self.save()
    def config(self):
        cfg=super().config()
        if cfg.get('signature_html'):
            p=Path(cfg['signature_html']);cfg['signature_html']=str(p if p.is_absolute() else BASE/p)
        return cfg
    def save(self):
        # Parent excludes password. Keep signature portable when inside package.
        super().save()
        p=BASE/'settings.json'
        if p.exists():
            cfg=json.loads(p.read_text('utf-8'));sig=cfg.get('signature_html')
            if sig:
                try:cfg['signature_html']=str(Path(sig).relative_to(BASE))
                except ValueError:pass
            atomic_json(p,cfg)
    def pick_signature(self):
        selected=filedialog.askopenfilename(filetypes=[('HTML签名','*.htm *.html')])
        if selected:
            try:self.v['signature_html'].set(import_signature(selected));self.stamp=None
            except Exception as exc:self.error(exc)
    def load_plan(self):
        cfg,_,_,_=super().load_plan()
        with self.ledger.connect() as db:past={r[0] for r in db.execute('SELECT email FROM attempts WHERE is_test=0')}
        suppressed=address_file(BASE/'不再联系.txt')|address_file(BASE/'已回复邮箱.txt')
        customers=read_customers(cfg['file'],cfg['sheet'],cfg['company_col'],cfg['email_col'],cfg['note_col'],past|address_file(BASE/'已发邮箱.txt'),suppressed)
        plan=[(c,self.render(c,cfg['subject'],cfg)) for c in customers if c.status=='ready'][:cfg['batch']]
        snapshot=[cfg,self.body.get('1.0','end-1c'),hashlib.sha256(Path(cfg['file']).read_bytes()).hexdigest(),[(c.row,c.company,c.email,c.note,c.status) for c in customers],[(str(m['Subject']),app.message_plain(m)) for _,m in plan]]
        if cfg.get('signature_html'):snapshot.append(app.load_signature(cfg['signature_html']).fingerprint)
        stamp=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest();return cfg,customers,plan,stamp
    def preview(self):
        super().preview()
        if self.stamp:
            self.progress_state.update(success=0,failed=0,unknown=0,skipped=sum(c.status!='ready' for c in self.customers),remaining=len(self.plan),current='预览完成，尚未发送');self.update_progress()
    def update_progress(self):
        p=self.progress_state;self.progress.set(f"服务器接受 {p['success']} · 失败 {p['failed']} · 跳过 {p['skipped']} · 待核实 {p['unknown']} · 本批剩余 {p['remaining']}\n当前客户：{p['current']}")
    def poll(self):
        super().poll()
        if hasattr(self,'progress'):self.update_progress()
    def deliver(self,cfg,password,plan,test=False):
        reporter=None if test else ExcelResults(cfg);results=[]
        p=self.progress_state;p.update(success=0,failed=0,unknown=0,remaining=len(plan))
        try:
            with AccountLease(cfg['sender']) as lease:
                for c,msg in plan:
                    p['current']=c.company
                    self.events.put(('status','等待发送间隔：'+c.company));lease.wait(self.stop_event)
                    suppressed=address_file(BASE/'不再联系.txt')|address_file(BASE/'已发邮箱.txt')|address_file(BASE/'已回复邮箱.txt')
                    if c.email in suppressed or (not test and c.email in self.ledger.blocked()):p['skipped']+=1;p['remaining']-=1;continue
                    lease.reserve(cfg['interval']);smtp=None
                    try:smtp=smtp_connect(cfg,password);r=submit(smtp,self.ledger,c,msg,cfg,test)
                    finally:
                        lease.finished(cfg['interval'])
                        if smtp:
                            try:smtp.quit()
                            except Exception:smtp.close()
                    results.append(r);state=r['state'];p['remaining']-=1
                    p[{'accepted':'success','failed':'failed','unknown':'unknown','skipped':'skipped'}[state]]+=1
                    atomic_json(BASE/'data'/'progress.json',dict(updated=now(),counts=p,results=results))
                    if reporter:reporter.record(r)
                    self.events.put(('status',c.company+'：'+state+(('；结果表：'+str(reporter.path)) if reporter and reporter.source.suffix.lower()=='.xlsx' else '；本地日志已保存')))
                    if state in ('failed','unknown'):raise InterruptedError('发送失败或状态待核实，已记录并暂停，不自动重发')
        except InterruptedError as exc:self.events.put(('status',str(exc)))
        finally:
            if results:
                try:
                    note=verify_copies(cfg,password,results);self.events.put(('archive_status',note))
                    if reporter:
                        for r in results:reporter.record(r)
                    atomic_json(BASE/'data'/'progress.json',dict(updated=now(),counts=p,results=results))
                except Exception as exc:self.events.put(('archive_status','发送结果已保存，副本核对失败：'+type(exc).__name__+'；不归档、不重发'))
            password=None
            if p['remaining']==0 and not p['failed'] and not p['unknown']:
                self.events.put(('status','本批处理结束；服务器接受不代表客户收件。下一批请重新生成预览。'))
    def test_connection(self):
        try:
            if not self.require_credential(self.test_connection):return
            cfg=self.config();password=self.v['password'].get()
            def work():
                with AccountLease(cfg['sender']):
                    smtp=smtp_connect(cfg,password)
                    try:smtp.noop()
                    finally:smtp.close()
                self.events.put(('status','SMTP连接与认证成功；未发送邮件。'))
            self.start(work)
        except Exception as exc:self.error(exc)

def main():
    root=tk.Tk();root.withdraw()
    if '--smoke-test' in sys.argv:
        instance=DesktopApp(root);root.update();print('GUI_SMOKE_OK');root.after_cancel(instance._poll_job);root.destroy();return
    if not ensure_configured(root,app.DEFAULT_SETTINGS):root.destroy();return
    instance=DesktopApp(root);root.deiconify();root.mainloop()

if __name__=='__main__':
    from main import main as public_main
    public_main()

