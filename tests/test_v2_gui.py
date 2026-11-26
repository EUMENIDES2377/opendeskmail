import gc,json,tempfile,tkinter as tk,unittest,time
from pathlib import Path
from unittest.mock import patch,Mock
from v2_model import DEFAULT,import_customers,save_config,save_template
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
        self.instance = None
        self.root = None
        # Release Tk cycles on the thread that created the interpreter.
        gc.collect()
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

    def test_unknown_result_continues_without_confirmation(self):
        app = self.app()
        template_id = save_template(dict(name='Example', language='en', subject='Example',
                                         format='text', body='Example body', attachments=[]), self.home)
        source = Path(self.tmp.name)/'example.csv'
        source.write_text('公司名称,邮箱\nOne,one@example.com\nTwo,two@example.com\nThree,three@example.com\n', encoding='utf-8')
        cfg = import_customers(source, dict(app.cfg, template_id=template_id, sheet='CSV'), self.home)
        self.controller.prepare(cfg)
        app.password = 'SIMULATED'
        states = iter(['accepted', 'unknown', 'accepted'])
        recipients = []

        class RecordingSMTP(FakeSMTP):
            def sendmail(self, sender, targets, raw):
                recipients.extend(targets)
                return super().sendmail(sender, targets, raw)

        self.controller.connector = lambda *_: RecordingSMTP(next(states))
        self.controller.start(app.password)
        self.controller.thread.join(5)
        self.assertFalse(self.controller.busy)
        self.assertEqual(recipients, ['one@example.com', 'two@example.com', 'three@example.com'])
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['accepted', 'unknown', 'accepted'])

    def test_project_switch_restart_preserves_history_templates_and_daily_limit(self):
        source = Path(self.tmp.name)/'port.csv'
        source.write_text('公司名称,邮箱\nPort One,one@example.com\nPort Two,two@example.com\n', encoding='utf-8')
        port_template = save_template(dict(name='Port', language='en', subject='Port project',
                                           format='text', body='Port preview', attachments=[]), self.home)
        cfg = import_customers(source, dict(DEFAULT, market='Project One', sender='sender@example.org',
                               host='smtp.example.org', port=465, batch=1, cap=2, sheet='CSV',
                               template_id=port_template, signature_text='Port signature'), self.home)
        save_config(cfg, self.home)
        self.controller.prepare(cfg)
        self.controller.start('SIMULATED')
        self.controller.thread.join(5)
        self.assertFalse(self.controller.busy)
        port_output = Path(self.controller.job['output'])
        with self.controller.ledger.connect() as db:
            db.execute('ALTER TABLE attempts DROP COLUMN project')
        self.controller.close()
        sent = []

        class RecordingSMTP(FakeSMTP):
            def sendmail(self, sender, targets, raw):
                sent.extend(targets)
                return super().sendmail(sender, targets, raw)

        app = Application(self.root, home=self.home, enable_projects=True)
        self.instance = app
        self.addCleanup(app.projects.close)
        self.controller = app.controller
        self.assertEqual(app.project, 'default')
        self.assertEqual(app.controller.snapshot()['today'], 1)
        self.assertEqual(str(app.controller.message(app.controller.job['rows'][1])['Subject']), 'Port project')
        self.assertIn('Port signature', app.sig.get('1.0', 'end'))
        self.assertEqual(app.controller.job['rows'][0]['state'], 'accepted')

        second = app.projects.create('Project Two')
        app.project_choice.set(app.projects.names[second])
        app.select_project()
        self.controller = app.controller
        self.assertIsNone(app.controller.job)
        self.assertNotIn('file', app.cfg)
        self.assertEqual(app.cfg['sender'], cfg['sender'])
        self.assertEqual(app.sig.get('1.0', 'end-1c'), '')
        self.assertEqual(app.tv['subject'].get(), '')
        self.assertEqual(app.controller.snapshot(app.cfg['sender'])['today'], 1)
        second_source = Path(self.tmp.name)/'second.csv'
        second_source.write_text('公司名称,邮箱\nProject Two Customer,three@example.com\n', encoding='utf-8')
        app.cfg = import_customers(second_source, app.cfg, app.home)
        app.cfg['template_id'] = save_template(dict(
            name='Second template', language='en', subject='Second project',
            format='text', body='Second preview', attachments=[]), app.home)
        app.refresh_templates()
        app.mapping['sheet'].set('CSV')
        app.prepare()
        second_row = app.controller.job['rows'][0]
        self.assertEqual('Second project', str(app.controller.message(second_row)['Subject']))
        app.controller.connector = lambda *_: RecordingSMTP()
        app.controller.lease_factory = FastLease
        app.controller.start('SIMULATED')
        app.controller.thread.join(5)
        self.assertEqual(app.controller.snapshot()['counts']['accepted'], 1)
        self.assertEqual(len(app.controller.ledger.rows()), 1)

        app.project_choice.set(app.projects.names['default'])
        app.select_project()
        self.controller = app.controller
        self.assertEqual(app.controller.snapshot()['today'], 2)
        self.assertEqual(len(app.controller.ledger.rows()), 1)
        self.assertEqual(app.controller.job['output'], str(port_output))
        self.assertEqual([row['state'] for row in app.controller.job['rows']], ['accepted', 'ready'])
        self.assertEqual(app.tv['subject'].get(), 'Port project')
        self.assertIn('Port signature', app.sig.get('1.0', 'end'))
        app.close()

        self.root = tk.Tk()
        self.root.withdraw()
        restarted = Application(self.root, home=self.home, enable_projects=True)
        self.instance = restarted
        self.addCleanup(restarted.projects.close)
        self.controller = restarted.controller
        self.assertEqual(restarted.project, 'default')
        self.assertFalse(self.controller.busy)
        self.assertEqual(self.controller.snapshot()['today'], 2)
        self.assertEqual([row['state'] for row in self.controller.job['rows']], ['accepted', 'ready'])
        self.controller.connector = lambda *_: RecordingSMTP()
        self.controller.lease_factory = FastLease
        self.controller.start('SIMULATED')
        self.controller.thread.join(5)
        self.assertIn('已达到当日尝试上限', self.controller.last)
        self.assertEqual(sent, ['three@example.com'])

if __name__=='__main__':unittest.main()
