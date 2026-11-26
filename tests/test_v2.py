import base64,json,threading,time,tempfile,unittest,copy,smtplib
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook,load_workbook
from v2_model import *
from v2_engine import Controller,Results
from test_independent import FakeSMTP

class FastLease:
    def __init__(self,sender):self.next_after=0;self.interval=None
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def wait(self,stop):
        if stop.is_set():raise InterruptedError('simulation stopped')
    def reserve(self,interval=60):self.interval=interval;self.next_after=time.time()+.4
    def finished(self,interval=60):self.interval=interval;self.next_after=time.time()+.4

class ScriptedSMTP(smtplib.SMTP):
    """Exercise smtplib's envelope and DATA handling without opening a socket."""
    def __init__(self, replies, commands):
        super().__init__()
        self.ehlo_resp = b'local test'
        self.replies = iter(replies)
        self.commands = commands

    def putcmd(self, cmd, args=''):
        self.commands.append((cmd.lower(), args))

    def getreply(self):
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def send(self, data):
        self.commands.append(('body', ''))

    def quit(self):
        self.close()


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.home=self.root/'home';self.source=self.root/'customers.xlsx'
        b=Workbook();s=b.active;s.title='Clients';s.append(['公司名称','邮箱','备注','语言','电话']);s.append(['Example One','one@example.com','Keep me','en','0100']);s.append(['Example Two','two@example.com','','es','0200']);b.save(self.source);b.close()
        self.cfg=dict(DEFAULT,market='Example Market',sender='sender@example.org',sender_name='Example',host='smtp.example.org',port=465,sheet='Clients',language_col='',storage=str(self.home))
        self.ids={}
        for lang in ('en','es','pt'):self.ids[lang]=save_template(dict(name='Example '+lang,language=lang,subject='Hello {{company}}',format='text',body='Dear {{company}},\n\nLocal example.',attachments=[]),self.home)
        self.cfg['template_id']=self.ids['en'];self.cfg=import_customers(self.source,self.cfg,self.home);self.smtp=[]
        def connector(cfg,password):
            s=FakeSMTP();self.smtp.append(s);return s
        self.controller=Controller(self.home,connector=connector,lease_factory=FastLease,copy_checker=lambda *args:'模拟副本检查，未访问网络')
        self.addCleanup(self.cleanup)
    def cleanup(self):
        if self.controller.busy:self.controller.stop();self.controller.thread.join(3)
        self.controller.close()
    def wait(self,predicate,timeout=4):
        end=time.time()+timeout
        while time.time()<end:
            if predicate():return
            time.sleep(.02)
        self.fail('Timed out waiting for simulation state')
    def finish(self):self.controller.thread.join(5);self.assertFalse(self.controller.busy)
    def test_actual_baseline_and_secret_whitelist(self):
        self.assertEqual((DEFAULT['interval'],DEFAULT['batch'],DEFAULT['cap']),(60,10,100));save_config(dict(self.cfg,password='DO_NOT_SAVE',access_token='DO_NOT_SAVE'),self.home)
        content=(self.home/'config/settings.json').read_text('utf-8');self.assertNotIn('DO_NOT_SAVE',content);self.assertNotIn('password',json.loads(content))
        with self.assertRaisesRegex(ValueError,'整数'):validate_account(dict(self.cfg,port='not-a-number'))
    def test_import_creates_stable_copy_before_sending(self):
        before=self.source.read_bytes();rows=self.controller.prepare(self.cfg);p=Path(self.controller.job['output']);self.assertTrue(p.exists());self.assertEqual(len(rows),2)
        again=import_customers(self.source,self.cfg,self.home);self.assertEqual(again['file'],self.cfg['file']);self.assertEqual(self.source.read_bytes(),before)
    def test_language_matches_existing_local_templates(self):
        cfg=dict(self.cfg,language_col='语言');rows=self.controller.prepare(cfg);self.assertEqual([r['template_id'] for r in rows],[self.ids['en'],self.ids['es']])
    def test_unknown_language_held(self):
        b=load_workbook(self.cfg['file']);b['Clients']['D3']='not-configured';b.save(self.cfg['file']);b.close();rows=self.controller.prepare(dict(self.cfg,language_col='语言'));self.assertEqual(rows[1]['state'],'skipped')
    def test_unknown_and_missing_variables_block(self):
        item=templates(self.home)[self.ids['en']];c=Customer(2,'Example','one@example.com')
        for text in ('{{missing}}','{{note}}','{{company | upper}}','{% include x %}'):
            with self.assertRaises(ValueError):build_message(c,{},self.cfg,dict(item,body=text))
    def test_all_customer_columns_and_html_escape(self):
        self.assertEqual(merge('{{电话}}',{'电话':'0100'}),'0100');self.assertEqual(merge('{{company}}',{'company':'A&B'},True),'A&amp;B')
    def test_attachment_and_inline_image_share_correct_mime(self):
        folder=self.home/'sig';folder.mkdir();png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD4kAAAAASUVORK5CYII=');(folder/'logo.png').write_bytes(png);(folder/'sig.html').write_text('<div>Example signature<img src="logo.png" width="100"></div>','utf-8')
        signature=import_html(folder/'sig.html',self.home);item=templates(self.home)[self.ids['en']];msg=build_message(Customer(2,'Example','one@example.com'),{},dict(self.cfg,signature_html=signature),dict(item,attachments=[str(folder/'logo.png')]))
        from v2_delivery import validate_inline
        self.assertTrue(validate_inline(msg)['valid']);self.assertEqual(msg.get_content_type(),'multipart/mixed');self.assertEqual(len(list(msg.iter_attachments())),1);self.assertEqual(msg.get_body(preferencelist=('plain',)).get_content().count('Example signature'),1)
    def test_changed_attachment_blocks_start(self):
        p=self.root/'attachment.txt';p.write_text('before','utf-8');items=templates(self.home);items[self.ids['en']]['attachments']=[str(p)];atomic_json(self.home/'config/templates.json',items);self.controller.prepare(self.cfg);p.write_text('after','utf-8')
        with self.assertRaises(ValueError):self.controller.start('simulated')
    def test_pause_resume_does_not_interrupt_current_submission(self):
        self.controller.prepare(self.cfg);self.controller.start('simulated');self.wait(lambda:self.controller.snapshot()['counts']['accepted']==1);self.controller.pause();self.wait(lambda:self.controller.status=='paused');time.sleep(.5);self.assertEqual(sum(s.calls for s in self.smtp),1)
        self.controller.resume();self.finish();self.assertEqual(sum(s.calls for s in self.smtp),2);self.assertEqual(self.controller.snapshot()['counts']['accepted'],2)
    def test_stop_then_restart_never_auto_sends(self):
        self.controller.prepare(self.cfg);self.controller.start('simulated');self.wait(lambda:self.controller.snapshot()['counts']['accepted']==1);self.controller.stop();self.finish();self.controller.close()
        self.controller=Controller(self.home,connector=lambda *args:FakeSMTP(),lease_factory=FastLease,copy_checker=lambda *args:'模拟');self.assertFalse(self.controller.busy);self.assertEqual(self.controller.snapshot()['counts']['accepted'],1)
        self.controller.start('simulated');self.finish();self.assertEqual(self.controller.snapshot()['counts']['accepted'],2)
    def test_double_start_and_multi_window_blocked(self):
        self.controller.prepare(self.cfg);self.controller.start('simulated')
        with self.assertRaises(ValueError):self.controller.start('simulated')
        with self.assertRaises(ValueError):Controller(self.home)
        self.finish();self.assertEqual(sum(s.calls for s in self.smtp),2)
    def test_cross_batch_and_reimport_no_duplicates(self):
        cfg=dict(self.cfg,batch=1);self.controller.prepare(cfg);self.controller.start('simulated');self.finish();self.assertEqual(self.controller.status,'batch_done');self.controller.start('simulated');self.finish()
        rows=self.controller.prepare(cfg);self.assertTrue(all(r['state']=='history' for r in rows));self.assertEqual(sum(s.calls for s in self.smtp),2)
    def test_daily_cap_does_not_reset(self):
        self.controller.prepare(dict(self.cfg,cap=1));self.controller.start('simulated');self.finish();self.assertEqual(sum(s.calls for s in self.smtp),1);self.assertEqual(self.controller.snapshot()['today'],1)
        self.controller.start('simulated');self.finish();self.assertEqual(sum(s.calls for s in self.smtp),1)
    def test_unknown_continues_and_is_never_retried(self):
        self.controller.connector=lambda *args:FakeSMTP('unknown');self.controller.prepare(self.cfg);self.controller.start('simulated');self.finish();self.assertEqual(self.controller.snapshot()['counts']['unknown'],2);self.assertEqual(self.controller.snapshot()['counts']['ready'],0)
        rows=self.controller.prepare(self.cfg);self.assertEqual(rows[0]['state'],'history')
    def test_recipient_failure_continues_without_yellow(self):
        self.controller.connector=lambda *args:FakeSMTP('failed');self.controller.prepare(self.cfg);self.controller.start('simulated');self.finish();self.assertEqual(self.controller.snapshot()['counts']['failed'],2)
        self.assertEqual(self.controller.status,'completed');self.assertIn('RCPT TO 550',self.controller.job['rows'][0]['reason'])
        self.assertEqual(self.controller.job['rows'][0]['result']['smtp_response'],'rejected')
        b=load_workbook(self.controller.job['output']);self.assertNotEqual(b['Clients']['A2'].fill.fgColor.rgb,'FFFFFF00');self.assertIn('发送失败',b['Clients']['C2'].value);b.close()
    def test_excel_failure_does_not_change_accepted(self):
        self.controller.prepare(self.cfg)
        with patch('v2_engine.Results.record',side_effect=PermissionError('simulated')):
            self.controller.start('simulated');self.finish()
        self.assertEqual(self.controller.snapshot()['counts']['accepted'],1);self.assertEqual(sum(s.calls for s in self.smtp),1);self.controller.repair();b=load_workbook(self.controller.job['output']);self.assertEqual(b['Clients']['A2'].fill.fgColor.rgb,'FFFFFF00');b.close()
    def test_orphaned_claim_recovered_unknown_not_ready(self):
        self.controller.prepare(self.cfg);row=self.controller.job['rows'][0];self.controller.ledger.claim(self.cfg['sender'],Customer(row['row'],row['company'],row['email']),'subject',100,'<orphan@example.org>');self.controller.close();self.controller=Controller(self.home,lease_factory=FastLease)
        self.assertEqual(self.controller.snapshot()['counts']['unknown'],1);self.assertFalse(self.controller.busy)
    def test_external_excel_changes_are_backed_up_on_repair(self):
        self.controller.prepare(self.cfg);output=Path(self.controller.job['output']);b=load_workbook(output);b['Clients']['C2']='External change';b.save(output);b.close();self.controller.repair();self.assertEqual(len(list(output.parent.glob('*外部改动备份*.xlsx'))),1)
    def test_refuses_other_program_data_paths(self):
        other=self.root/'other-program';(other/'data').mkdir(parents=True);(other/'core.py').write_text('# mock program');p=other/'data'/'private.xlsx'
        with self.assertRaises(ValueError):protect_source(p)
    def test_authentication_error_is_chinese_and_no_secret(self):
        from v2_engine import explain
        text=explain(smtplib.SMTPAuthenticationError(535,b'SECRET_DO_NOT_SHOW'))
        self.assertIn('认证失败',text);self.assertNotIn('SECRET_DO_NOT_SHOW',text)
    def test_csv_working_copy_created_and_updated(self):
        path=self.root/'sample.csv';path.write_text('公司名称,邮箱,备注\nExample,one@example.com,Keep\n',encoding='utf-8');cfg=import_customers(path,dict(self.cfg,sheet='CSV'),self.home);before=path.read_bytes();self.controller.prepare(cfg)
        self.assertTrue(Path(self.controller.job['output']).is_file());self.controller.start('simulation');self.finish();text=Path(self.controller.job['output']).read_text('utf-8-sig');self.assertIn('发送邮件开发信',text);self.assertEqual(before,path.read_bytes())
    def test_unavailable_smtp_stops_without_claiming_any_customer(self):
        def unavailable(*args):
            raise smtplib.SMTPConnectError(421, b'Service not available')

        self.controller.connector = unavailable
        self.controller.prepare(self.cfg)
        self.controller.start('simulated')
        self.finish()
        self.assertEqual(self.controller.status, 'stopped')
        self.assertEqual(self.controller.snapshot()['today'], 0)
        self.assertEqual([row['state'] for row in self.controller.job['rows']], ['ready', 'ready'])
        self.assertIn('421', self.controller.last)

    def test_auth_failure_stops_after_one_connection(self):
        calls=[]
        def reject(*args):calls.append(1);raise smtplib.SMTPAuthenticationError(535,b'FAKE_SECRET_MUST_NOT_LOG')
        self.controller.connector=reject;self.controller.prepare(self.cfg);self.controller.start('simulation');self.finish();self.assertEqual(len(calls),1);self.assertEqual(self.controller.snapshot()['counts']['accepted'],0);self.assertNotIn('FAKE_SECRET', ''.join(self.controller.logs))
    def test_throttle_421_stops_batch_with_reason(self):
        class Throttled(FakeSMTP):
            def data(self,data):raise smtplib.SMTPDataError(421,b'throttle simulation')
        self.controller.connector=lambda *args:Throttled();self.controller.prepare(self.cfg);self.controller.start('simulation');self.finish();self.assertEqual(self.controller.snapshot()['counts']['failed'],1);self.assertEqual(self.controller.snapshot()['counts']['ready'],1);self.assertIn('421',self.controller.job['rows'][0]['reason'])
    def scripted_batch(self, *sessions, cfg=None):
        commands = []
        sessions = iter(sessions)
        self.controller.connector = lambda *_: ScriptedSMTP(next(sessions), commands)
        self.controller.prepare(cfg or self.cfg)
        self.controller.start('SIMULATED_SECRET')
        self.finish()
        return commands

    def test_mixed_excel_queue_skips_local_errors_and_finishes_without_intervention(self):
        book = load_workbook(self.source)
        sheet = book['Clients']
        sheet.delete_rows(2, 2)
        for company, address in [('First', 'first@example.com'), ('Empty', ''),
                                 ('Invalid', 'bad-address'), ('Refused', 'refused@example.com'),
                                 ('Last', 'last@example.com')]:
            sheet.append([company, address])
        book.save(self.source)
        book.close()
        cfg = import_customers(self.source, self.cfg, self.home)
        ok = [(250, b'ok'), (250, b'ok'), (354, b'data'), (250, b'queued')]
        refused = [(250, b'ok'), (550, b'5.7.1 Recipient address rejected: access denied'), (250, b'reset')]
        with patch.object(FastLease, 'reserve', autospec=True, side_effect=FastLease.reserve) as reserve:
            commands = self.scripted_batch(ok, refused, ok, cfg=cfg)
        self.assertEqual(self.controller.status, 'completed')
        self.assertEqual([r['state'] for r in self.controller.job['rows']],
                         ['accepted', 'skipped', 'skipped', 'failed', 'accepted'])
        self.assertEqual(self.controller.snapshot()['counts'],
                         dict(ready=0, accepted=2, failed=1, unknown=0, skipped=2))
        self.assertEqual(self.controller.snapshot()['today'], 3)
        self.assertEqual([call.args[1] for call in reserve.call_args_list], [60, 60, 60])
        self.assertEqual([args for cmd, args in commands if cmd == 'rcpt'],
                         ['TO:<first@example.com>', 'TO:<refused@example.com>', 'TO:<last@example.com>'])
        lines = (self.home/'logs/events.log').read_text('utf-8').splitlines()
        entries = {entry['row']: entry for line in lines if '客户处理 ' in line
                   for entry in [json.loads(line.split('客户处理 ', 1)[1])]}
        self.assertEqual(set(entries), {2, 3, 4, 5, 6})
        self.assertEqual(entries[3]['reason'], '收件邮箱为空')
        self.assertEqual(entries[4]['reason'], '收件邮箱格式无效')
        self.assertEqual(entries[5]['smtp_code'], 550)
        self.assertEqual(entries[5]['smtp_response'], '5.7.1 Recipient address rejected: access denied')
        self.assertEqual(entries[6]['company'], 'Last')

    def test_duplicate_claim_skip_does_not_reserve_an_interval(self):
        self.controller.prepare(self.cfg)
        claim = self.controller.ledger.claim

        def claim_one(sender, customer, *args, **kwargs):
            if customer.row == 2:
                return None
            return claim(sender, customer, *args, **kwargs)

        with patch.object(self.controller.ledger, 'claim', side_effect=claim_one), \
             patch.object(FastLease, 'reserve', autospec=True, side_effect=FastLease.reserve) as reserve:
            self.controller.start('simulated')
            self.finish()
        self.assertEqual([row['state'] for row in self.controller.job['rows']], ['skipped', 'accepted'])
        self.assertEqual(self.controller.snapshot()['today'], 1)
        self.assertEqual(reserve.call_count, 1)
        self.assertEqual(sum(s.calls for s in self.smtp), 1)

    def test_runtime_render_failure_skips_without_using_attempt_or_interval(self):
        self.controller.prepare(self.cfg)
        render = self.controller.message

        def render_one(row, fields):
            if row['row'] == 2:
                raise ValueError('模拟收件人字段缺失')
            return render(row, fields)

        with patch.object(self.controller, 'message', side_effect=render_one):
            self.controller.start('simulated')
            self.finish()
        self.assertEqual([row['state'] for row in self.controller.job['rows']], ['skipped', 'accepted'])
        self.assertEqual(self.controller.snapshot()['today'], 1)
        self.assertEqual(sum(s.calls for s in self.smtp), 1)
        self.assertIn('模拟收件人字段缺失', ''.join(self.controller.logs))

    def test_invalid_recipient_continues_at_normal_interval_and_counts_attempt(self):
        ok = [(250, b'ok'), (250, b'ok'), (354, b'send data'), (250, b'2.0.0 queued')]
        invalid = [(250, b'ok'), (550, b'5.1.1 User unknown\n5.1.1 Check address'), (250, b'reset')]
        with patch.object(FastLease, 'finished', autospec=True, side_effect=FastLease.finished) as finished:
            commands = self.scripted_batch(invalid, ok)
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['failed', 'accepted'])
        self.assertEqual([call.args[1] for call in finished.call_args_list], [60, 60])
        self.assertEqual(self.controller.snapshot()['today'], 2)
        self.assertEqual([cmd for cmd, _ in commands].count('body'), 1)
        result = json.loads((self.home/'data/attempts/1-result.json').read_text('utf-8'))
        self.assertEqual((result['smtp_stage'], result['smtp_code'], result['smtp_enhanced_code']), ('RCPT TO', 550, '5.1.1'))
        self.assertEqual(result['smtp_response'], '5.1.1 User unknown\n5.1.1 Check address')
        self.assertIn('5.1.1 User unknown', (self.home/'logs/events.log').read_text('utf-8'))
        with self.controller.ledger.connect() as db:
            self.assertIn('当前收件地址不存在或格式无效', db.execute('SELECT detail FROM attempts WHERE id=1').fetchone()[0])

    def test_sender_throttle_stops_and_manual_resume_skips_failed_attempt(self):
        throttled = [(451, b'4.7.0 Sending rate limit exceeded SIMULATED_SECRET'), (250, b'reset')]
        ok = [(250, b'ok'), (250, b'ok'), (354, b'send data'), (250, b'2.0.0 queued')]
        commands = self.scripted_batch(throttled, ok)
        self.assertEqual(self.controller.status, 'stopped')
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['failed', 'ready'])
        self.assertIn('发送限流', self.controller.last)
        self.assertIn('MAIL FROM 451 4.7.0', self.controller.last)
        self.assertNotIn('SIMULATED_SECRET', (self.home/'logs/events.log').read_text('utf-8'))
        self.assertNotIn('SIMULATED_SECRET', (self.home/'data/attempts/1-result.json').read_text('utf-8'))
        self.controller.resume('SIMULATED_SECRET')
        self.finish()
        self.assertEqual([args for cmd, args in commands if cmd == 'rcpt'], ['TO:<two@example.com>'])
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['failed', 'accepted'])

    def test_disconnect_after_data_continues_without_retry(self):
        book = load_workbook(self.source)
        book['Clients'].append(['Example Three', 'three@example.com'])
        book.save(self.source)
        book.close()
        cfg = import_customers(self.source, self.cfg, self.home)
        prefix = [(250, b'ok'), (250, b'ok'), (354, b'send data')]
        ok = prefix + [(250, b'2.0.0 queued')]
        unknown = prefix + [smtplib.SMTPServerDisconnected('lost final reply')]
        commands = self.scripted_batch(ok, unknown, ok, cfg=cfg)
        self.assertEqual(self.controller.status, 'completed')
        self.assertIn('DATA 阶段未能确认', self.controller.job['rows'][1]['reason'])
        self.assertEqual([cmd for cmd, _ in commands].count('body'), 3)
        self.assertEqual([args for cmd, args in commands if cmd == 'rcpt'],
                         ['TO:<one@example.com>', 'TO:<two@example.com>', 'TO:<three@example.com>'])
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['accepted', 'unknown', 'accepted'])
        self.controller.close()
        self.controller = Controller(self.home, connector=lambda *_: self.fail('unexpected SMTP connection'),
                                     lease_factory=FastLease)
        self.assertFalse(self.controller.busy)
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['accepted', 'unknown', 'accepted'])
        with self.assertRaisesRegex(ValueError, '没有未尝试'):
            self.controller.start('SIMULATED_SECRET')

    def test_data_rejection_retains_codes_but_hides_quoted_body(self):
        rejected = [(250, b'ok'), (250, b'ok'), (354, b'send data'),
                    (550, b'5.7.1 Rejected content: Local example.'), (250, b'reset')]
        self.scripted_batch(rejected)
        self.assertEqual(self.controller.status, 'stopped')
        result = self.controller.job['rows'][0]['result']
        self.assertEqual(result['smtp_enhanced_code'], '5.7.1')
        self.assertIn('策略拒收', result['reason'])
        self.assertNotIn('Local example.', (self.home/'logs/events.log').read_text('utf-8'))
        self.assertNotIn('Local example.', result['smtp_response'])

    def test_250_before_body_is_not_treated_as_acceptance(self):
        commands = self.scripted_batch([(250, b'ok'), (250, b'ok'), (250, b'unexpected before body'), (250, b'reset')])
        self.assertEqual(self.controller.status, 'stopped')
        self.assertEqual([r['state'] for r in self.controller.job['rows']], ['unknown', 'ready'])
        self.assertNotIn('body', [cmd for cmd, _ in commands])
    def test_language_mapping_typo_does_not_silently_fall_back(self):
        with self.assertRaises(ValueError):self.controller.prepare(dict(self.cfg,language_col='不存在的语言表头'))
    def test_ambiguous_language_templates_not_guessed(self):
        save_template(dict(name='Another Spanish',language='es',subject='Another',format='text',body='Other content',attachments=[]),self.home)
        rows=self.controller.prepare(dict(self.cfg,language_col='语言'));self.assertEqual(rows[1]['state'],'skipped');self.assertIn('多个模板',rows[1]['reason'])
    def test_literal_field_names_with_spaces_are_supported(self):
        self.assertEqual(merge('Hello {{ Contact Name }}',{'Contact Name':'Example Person'}),'Hello Example Person')
        with self.assertRaises(ValueError):merge('{{ company.upper() }}',{'company':'Example'})
    def test_unreferenced_blank_or_duplicate_extra_headers_do_not_change_import_rules(self):
        b=load_workbook(self.cfg['file']);s=b['Clients'];s['F1']='';s['G1']='';s['H1']='电话';s['H2']='duplicate';b.save(self.cfg['file']);b.close()
        rows=self.controller.prepare(self.cfg);self.assertEqual([r['state'] for r in rows],['ready','ready'])
        with self.assertRaises(ValueError):merge('{{电话}}',customer_fields(self.cfg)[2])

if __name__=='__main__':unittest.main()
