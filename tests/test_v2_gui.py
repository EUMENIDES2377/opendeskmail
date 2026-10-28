import json,tempfile,tkinter as tk,unittest,time
from pathlib import Path
from unittest.mock import patch,Mock
from v2_model import DEFAULT,save_config,save_template
from v2_gui import Application
from v2_engine import Controller
from test_v2 import FastLease
from test_independent import FakeSMTP

class V2GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)/'workspace';self.root=tk.Tk();self.root.withdraw();self.controller=Controller(self.home,lease_factory=FastLease,connector=lambda *args:FakeSMTP(),copy_checker=lambda *args:'模拟副本')
        self.addCleanup(self.cleanup)
    def cleanup(self):
        if self.controller.busy:self.controller.stop();self.controller.thread.join(3)
        self.controller.close();self.root.update()
        for callback in self.root.tk.call('after','info'):self.root.after_cancel(callback)
        self.root.destroy()
    def app(self,configured=True):
        if configured:save_config(dict(DEFAULT,market='Example',sender='sender@example.org',host='smtp.example.org',port=465),self.home)
        self.instance=Application(self.root,self.home,self.controller);return self.instance
    def test_wizard_starts_when_unconfigured_and_has_masked_secret(self):
        app=self.app(False);self.root.deiconify()
        until=time.time()+.4
        while time.time()<until:self.root.update();time.sleep(.01)
        tops=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)];self.assertEqual(len(tops),1)
        def children(w):
            for c in w.winfo_children():yield c;yield from children(c)
        self.assertTrue(any(w.winfo_class()=='TEntry' and w.cget('show')=='*' for w in children(tops[0])))
        self.assertTrue(tops[0].winfo_ismapped());self.assertFalse((self.home/'config/settings.json').exists());tops[0].destroy()
    def test_configured_start_has_four_pages_no_auto_send(self):
        app=self.app();self.root.deiconify();self.root.update();self.assertEqual(len(app.tabs.tabs()),4);self.assertFalse(self.controller.busy);self.assertEqual(self.controller.ledger.rows(),[])
        self.assertIn('总数',app.summary.get());self.assertIn('今日累计',app.detail.get())
    def test_account_dialog_scroll_reaches_credential_type(self):
        app=self.app();self.root.deiconify();self.root.update();app.account_dialog();self.root.update()
        top=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        canvas=next(w for w in top.winfo_children() if isinstance(w,tk.Canvas))
        frame=next(w for w in canvas.winfo_children() if w.winfo_class()=='TFrame')
        field=next(w for w in frame.winfo_children() if w.winfo_class()=='TCombobox' and 'smtp_authorization_code' in w.cget('values'))
        self.assertTrue(field.bind('<MouseWheel>'));canvas.yview_moveto(1);self.root.update()
        self.assertGreaterEqual(field.winfo_rooty(),canvas.winfo_rooty())
        self.assertLessEqual(field.winfo_rooty()+field.winfo_height(),canvas.winfo_rooty()+canvas.winfo_height())
        self.assertGreater(field.winfo_width(),150);top.destroy()
    def test_connection_test_never_calls_sendmail(self):
        app=self.app();smtp=Mock()
        with patch('v2_gui.smtp_connect',return_value=smtp):text=app.test_account(app.cfg,'FAKE_ONLY')
        self.assertIn('未发送',text);smtp.sendmail.assert_not_called();smtp.noop.assert_called_once()
    def test_test_message_is_separate_from_real_history(self):
        from v2_model import build_message
        from core import Customer
        app=self.app();template=dict(subject='[TEST] Example',format='text',body='Hello {{company}}',attachments=[]);c=Customer(0,'Example','self@example.com');message=build_message(c,{},app.cfg,template)
        with patch('v2_gui.smtp_connect',return_value=FakeSMTP()):text=app.single_test(app.cfg,'FAKE_ONLY',c,message)
        self.assertIn('服务器已接受',text);self.assertNotIn(c.email,self.controller.ledger.blocked())
    def test_local_template_direct_edit_then_save(self):
        app=self.app();app.tv['name'].set('Example');app.tv['subject'].set('Hello {{company}}');app.tv['language'].set('es');app.body.insert('1.0','Hola {{company}}');app.save_template_ui();self.assertEqual(app.tv['language'].get(),'es');self.assertTrue(app.template_ids)
    def test_unsaved_template_edit_blocks_preview(self):
        app=self.app();app.tv['name'].set('Example');app.tv['subject'].set('Hello');app.body.insert('1.0','Example body');app.save_template_ui();app.body.insert('end',' changed')
        with self.assertRaises(ValueError):app.collect_cfg()

if __name__=='__main__':unittest.main()
