import copy,io,json,os,smtplib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app_paths,configure,v2_model
from v2_model import DEFAULT,SecureStore,save_config
from v2_engine import Controller
from test_v2 import FastLease
from test_independent import FakeSMTP

SECRET='FAKE_SECRET_FOR_TEST_ONLY'
class MemoryStore:
    def __init__(self):self.values={};self.writes=0;self.reads=0
    def write(self,cfg,value):self.writes+=1;self.values[SecureStore.target(cfg)]=value
    def read(self,cfg):self.reads+=1;return self.values.get(SecureStore.target(cfg))
class ConfigSMTP(FakeSMTP):
    def __init__(self):super().__init__();self.noops=0
    def noop(self):self.noops+=1

class OpenSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.home=Path(self.tmp.name)/'profile';self.store=MemoryStore();self.client=ConfigSMTP();self.connections=0
        self.account=dict(DEFAULT,market='Example Project',sender='sender@example.org',host='smtp.example.org',port=465)
        self.payload=dict(account=self.account,credential=dict(kind='smtp_authorization_code',value=SECRET),consent=dict(configure=True,test_connection=True))
    def connector(self,cfg,password):self.connections+=1;self.assertEqual(password,SECRET);return self.client
    def apply(self,payload=None):return configure.apply_configuration(payload or self.payload,self.home,self.store,self.connector,FastLease)
    def test_default_data_outside_source(self):
        self.assertNotEqual(app_paths.USER_HOME,app_paths.CODE_ROOT);self.assertNotIn(app_paths.CODE_ROOT,app_paths.USER_HOME.parents)
        self.assertIn('OpenDeskMail',str(app_paths.DATA_ROOT))
    def test_user_directory_override(self):
        root=Path(self.tmp.name)/'state';self.assertEqual(app_paths.profile_home(environ={'OPENDESK_MAIL_DATA_DIR':str(root)}),(root/'profiles/default').resolve())
    def test_source_or_relative_runtime_override_refused(self):
        for path in (str(app_paths.CODE_ROOT),str(app_paths.CODE_ROOT/'workspace'),'relative'):
            with self.assertRaises(ValueError):app_paths.data_root({'OPENDESK_MAIL_DATA_DIR':path})
    def test_profile_traversal_refused(self):
        with self.assertRaises(ValueError):app_paths.profile_home('../other')
    def test_no_automatic_source_config_import(self):
        with patch.object(v2_model,'BASE',Path(self.tmp.name)):
            (Path(self.tmp.name)/'settings.json').write_text(json.dumps(dict(sender='ignored@example.com',password=SECRET)))
            self.assertEqual(v2_model.load_config(self.home)['sender'],'')
    def test_voluntarily_provided_credential_stored_without_reprompt(self):
        result=self.apply();self.assertTrue(result['ok']);self.assertEqual(self.store.writes,1);self.assertEqual(self.store.reads,0);self.assertEqual(self.connections,1);self.assertEqual(self.client.noops,1);self.assertEqual(self.client.calls,0)
        self.assertFalse(result['bulk_authorized']);self.assertEqual(result['emails_sent'],0)
    def test_credential_never_saved_to_config_or_results(self):
        result=self.apply();cfg=json.loads((self.home/'config/settings.json').read_text('utf-8'));self.assertNotIn('password',cfg);self.assertEqual(cfg['credential_kind'],'smtp_authorization_code');self.assertNotIn(SECRET,json.dumps(result))
        for path in self.home.rglob('*'):
            if path.is_file():self.assertNotIn(SECRET.encode(),path.read_bytes())
    def test_account_object_rejects_embedded_plaintext_secret(self):
        payload=copy.deepcopy(self.payload);payload['account']['password']=SECRET
        with self.assertRaises(ValueError):self.apply(payload)
        self.assertEqual(self.store.writes,0)
    def test_authorization_is_required(self):
        for key in ('configure','test_connection'):
            payload=copy.deepcopy(self.payload);payload['consent'][key]=False
            with self.assertRaises(ValueError):self.apply(payload)
        self.assertEqual(self.store.writes,0);self.assertEqual(self.connections,0)
    def test_existing_credential_used_for_current_target_only(self):
        self.apply();payload=copy.deepcopy(self.payload);payload.pop('credential');self.apply(payload);self.assertEqual(self.store.reads,1);self.assertEqual(self.connections,2)
    def test_account_edit_preserves_existing_limits_and_template(self):
        save_config(dict(self.account,interval=85,batch=4,cap=37,template_id='existing-template'),self.home)
        payload=copy.deepcopy(self.payload)
        payload['account']={key:self.account[key] for key in ('market','sender','host','port','security')}
        self.apply(payload);saved=v2_model.load_config(self.home)
        self.assertEqual((saved['interval'],saved['batch'],saved['cap'],saved['template_id']),(85,4,37,'existing-template'))
    def test_storage_failure_never_falls_back_to_text(self):
        self.store.write=lambda *args:(_ for _ in ()).throw(RuntimeError(SECRET))
        with self.assertRaises(RuntimeError):self.apply()
        self.assertFalse((self.home/'config/settings.json').exists());self.assertEqual(self.connections,0)
    def test_auth_rejection_is_single_attempt(self):
        calls=[]
        def reject(*args):calls.append(1);raise smtplib.SMTPAuthenticationError(535,SECRET.encode())
        with self.assertRaises(smtplib.SMTPAuthenticationError):configure.apply_configuration(self.payload,self.home,self.store,reject,FastLease)
        self.assertEqual(len(calls),1)
    def test_busy_profile_prevents_ai_reconfiguration(self):
        controller=Controller(self.home)
        try:
            with self.assertRaises(configure.ProfileBusyError):self.apply()
        finally:controller.close()
        self.assertEqual(self.store.writes,0)
    def test_validate_only_has_no_storage_or_network(self):
        out=io.StringIO();code=configure.cli(['--validate-only'],io.StringIO(json.dumps(self.payload)),out)
        self.assertEqual(code,0);self.assertNotIn(SECRET,out.getvalue());self.assertFalse(self.home.exists());self.assertEqual(self.connections,0)
    def test_cli_never_echoes_exception_or_arguments(self):
        for args in (['--password',SECRET],['--apply']):
            out=io.StringIO()
            with patch.object(configure,'apply_configuration',side_effect=RuntimeError(SECRET)):
                code=configure.cli(args,io.StringIO(json.dumps(self.payload)),out)
            self.assertEqual(code,1);self.assertNotIn(SECRET,out.getvalue());self.assertNotIn('Traceback',out.getvalue())
    def test_malformed_input_does_not_echo_content(self):
        out=io.StringIO();self.assertEqual(configure.cli(['--apply'],io.StringIO('{'+SECRET),out),1);self.assertNotIn(SECRET,out.getvalue())
    def test_ai_apply_cannot_start_bulk(self):
        with patch.object(Controller,'start',side_effect=AssertionError('No bulk permission')):result=self.apply()
        self.assertFalse(result['bulk_authorized']);self.assertEqual(self.client.calls,0)
    def test_explicit_test_recipient_and_permission_required(self):
        self.apply()
        with self.assertRaises(ValueError):configure.send_test_message({'test_mail':{'to':'self@example.com'}},self.home,self.store,self.connector,FastLease)
        with self.assertRaises(ValueError):configure.send_test_message({'consent':{'send_test':True}},self.home,self.store,self.connector,FastLease)
        self.assertEqual(self.client.calls,0)
    def test_authorized_single_test_does_not_mark_real_customer_sent(self):
        self.apply();result=configure.send_test_message({'consent':{'send_test':True},'test_mail':{'to':'self@example.com'}},self.home,self.store,self.connector,FastLease)
        self.assertTrue(result['ok']);self.assertEqual(self.client.calls,1);self.assertFalse(result['recipient_receipt_confirmed']);self.assertFalse(result['bulk_authorized'])
        from core import Ledger
        self.assertNotIn('self@example.com',Ledger(self.home/'data/history.sqlite3').blocked())
    def test_safe_auth_error_redaction(self):
        result=configure.safe_error(smtplib.SMTPAuthenticationError(535,SECRET.encode()));self.assertEqual(result['code'],535);self.assertNotIn(SECRET,json.dumps(result))

if __name__=='__main__':unittest.main()
