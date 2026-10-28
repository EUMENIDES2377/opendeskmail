"""Offline fictitious demonstration. Never opens SMTP/IMAP or credentials."""
import time,uuid,tkinter as tk,smtplib,sys,json
from tkinter import messagebox
from pathlib import Path
from openpyxl import Workbook
from core import BASE
from v2_model import DEFAULT,save_config,save_template,import_customers
from v2_engine import Controller
from v2_gui import Application
from app_paths import DATA_ROOT

class SimulatedSMTP:
    def data(self,raw):return 250,b'OFFLINE-SIMULATION-ONLY'
    def sendmail(self,sender,recipients,raw):
        if any(email.rsplit('@',1)[-1] not in ('example.com','example.org','example.net') for email in recipients):raise smtplib.SMTPRecipientsRefused({recipients[0]:(550,b'fictional demo addresses only')})
        self.data(raw);return {}
    def quit(self):pass
    def close(self):pass
class SimulatedLease:
    def __init__(self,sender):self.next_after=0
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def reserve(self,interval=60):self.next_after=time.time()+2
    def finished(self,interval=60):self.next_after=time.time()+2
    def wait(self,stop):
        while time.time()<self.next_after:
            if stop.wait(.1):raise InterruptedError('演示已停止')
class DemoApplication(Application):
    def account_dialog(self):messagebox.showinfo('离线演示','这是虚构客户模拟界面，不连接SMTP/IMAP，不读取凭据。请使用launch.bat配置自己的正式账号。',parent=self.root)
    def test_account(self,*args):return '仅模拟，不代表真实账号认证成功。'
    def single_test(self,*args):return '仅模拟，不向任何真实地址发送。'
def main():
    home=DATA_ROOT/'demos'/uuid.uuid4().hex[:12];home.mkdir(parents=True);source=home/'fictional.xlsx';book=Workbook();sheet=book.active;sheet.title='Examples';sheet.append(['公司名称','邮箱','备注','语言']);sheet.append(['Example One','one@example.com','虚构客户','en']);sheet.append(['Example Two','two@example.com','虚构客户','es']);sheet.append(['Example Three','three@example.com','虚构客户','pt']);sheet.append(['Invalid Example','官网表单','演示跳过','en']);book.save(source);book.close()
    cfg=dict(DEFAULT,market='离线演示（仅虚构数据）',sender='sender@example.org',sender_name='Example Sender',host='smtp.example.org',port=465,sheet='Examples',language_col='语言')
    for lang,body in [('en','Hello {{company}},\n\nOffline example only.'),('es','Hola {{company}},\n\nEjemplo local.'),('pt','Olá {{company}},\n\nExemplo local.')]:
        ident=save_template(dict(name='Example '+lang,language=lang,format='text',subject='[DEMO] Example for {{company}}',body=body,attachments=[]),home)
        if lang=='en':cfg['template_id']=ident
    cfg=import_customers(source,cfg,home);save_config(cfg,home);controller=Controller(home,connector=lambda *args:SimulatedSMTP(),lease_factory=SimulatedLease,copy_checker=lambda *args:'仅模拟副本状态；未访问邮箱服务器')
    controller.prepare(cfg);root=tk.Tk();app=DemoApplication(root,home,controller);app.password='DEMO-NOT-A-CREDENTIAL';app.show_rows();root.title('离线模拟演示 · 无真实发信 · 演示间隔加速为2秒')
    if '--smoke' in sys.argv:
        def done():
            root.update_idletasks();print(json.dumps(dict(visible=bool(root.winfo_ismapped()),geometry=root.geometry(),pages=len(app.tabs.tabs()),tree_height=app.tree.winfo_height(),counts=controller.snapshot()['counts']),ensure_ascii=False),flush=True);app.close()
        root.after(600,done)
    root.mainloop()
if __name__=='__main__':main()
