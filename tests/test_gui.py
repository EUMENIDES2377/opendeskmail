"""Exercise this application's own widgets only; never connects to a mailbox."""
import json,tempfile,tkinter as tk,unittest
from pathlib import Path
from unittest.mock import patch
import app,core,desktop,desktop_runtime,first_run

class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        for name in ('email_body.txt','signature.txt','已发邮箱.txt','不再联系.txt','已回复邮箱.txt'):(self.base/name).write_text('',encoding='utf-8')
        for module in (app,core,desktop,desktop_runtime,first_run):
            p=patch.object(module,'BASE',self.base);p.start();self.addCleanup(p.stop)
        p=patch.object(app,'CredentialStore');mock=p.start();mock.return_value.read.return_value=None;self.addCleanup(p.stop)
        self.root=tk.Tk();self.root.withdraw()
        def close_root():
            self.root.update()
            for callback in self.root.tk.call('after','info'):self.root.after_cancel(callback)
            self.root.destroy()
        self.addCleanup(close_root)
    def test_wizard_is_visible_and_cancels_without_config(self):
        observations=[]
        def close():
            top=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel));observations.append(bool(top.winfo_ismapped()));top.destroy()
        self.root.after(300,close)
        self.assertFalse(first_run.ensure_configured(self.root,app.DEFAULT_SETTINGS));self.assertEqual(observations,[True]);self.assertFalse((self.base/'settings.json').exists())
    def test_wizard_saves_own_config_without_password(self):
        def fill():
            top=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel));frame=top.winfo_children()[0]
            values={1:'Example Market',2:'sender@example.org',3:'Example User',4:'smtp.example.org',5:'465',7:'Hello {{company}}'}
            for widget in frame.winfo_children():
                if widget.winfo_class()=='TEntry' and int(widget.grid_info()['row']) in values:widget.insert(0,values[int(widget.grid_info()['row'])])
                if isinstance(widget,tk.Text):widget.insert('1.0','Dear {{company}},\n\nExample content.')
            next(w for w in frame.winfo_children() if w.winfo_class()=='TButton' and str(w.cget('text')).startswith('保存自己的')).invoke()
        self.root.after(300,fill);self.assertTrue(first_run.ensure_configured(self.root,app.DEFAULT_SETTINGS))
        cfg=json.loads((self.base/'settings.json').read_text('utf-8'));self.assertEqual(cfg['market'],'Example Market');self.assertEqual(cfg['sender'],'sender@example.org');self.assertNotIn('password',cfg)
    def test_main_window_initializes_without_network(self):
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            instance=desktop.DesktopApp(self.root);self.root.update()
            self.assertIn('服务器接受',instance.progress.get());self.assertEqual(instance.ledger.rows(),[])
            self.root.after_cancel(instance._poll_job)
    def test_gui_dispatch_updates_progress_ledger_and_excel(self):
        from openpyxl import Workbook
        from account_guard import AccountLease
        from test_independent import FakeSMTP
        source=self.base/'customers.xlsx';book=Workbook();sh=book.active;sh.title='Customers';sh.append(['公司名称','邮箱','备注']);sh.append(['Example Company','customer@example.com','Existing note']);book.save(source);book.close()
        instance=desktop.DesktopApp(self.root)
        for key,value in dict(file=str(source),sheet='Customers',sender='sender@example.org',host='smtp.example.org',subject='Hello {{company}}').items():instance.v[key].set(value)
        instance.body.insert('1.0','Dear {{company}},\n\nExample content.');cfg=instance.config();customer=core.Customer(2,'Example Company','customer@example.com');message=instance.render(customer,cfg['subject'],cfg);smtp=FakeSMTP()
        with patch.object(desktop,'smtp_connect',return_value=smtp),patch.object(desktop,'AccountLease',side_effect=lambda sender:AccountLease(sender,self.base/'locks')):
            instance.deliver(cfg,'not-a-real-secret',[(customer,message)])
        self.assertEqual(instance.progress_state['success'],1);self.assertEqual(instance.progress_state['remaining'],0);self.assertEqual(len(instance.ledger.rows()),1)
        self.assertEqual(len(list((self.base/'data/results').glob('*.xlsx'))),1);self.assertEqual(smtp.calls,1);self.root.after_cancel(instance._poll_job)

if __name__=='__main__':unittest.main()
