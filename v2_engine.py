"""Threaded, restart-safe single-account controller; all transports injectable."""
import hashlib,json,queue,threading,time,msvcrt,os
from pathlib import Path
from dataclasses import asdict
from core import Customer,Ledger,read_customers,address_file,now,smtp_connect
from account_guard import AccountLease
from app_paths import DATA_ROOT
from v2_model import HOME,STATES,templates,language,customer_fields,build_message,template_fingerprint,public_config,digest
from v2_delivery import submit,atomic_json,verify_copies,ExcelResults

def explain(exc):
    import smtplib,ssl
    if isinstance(exc,smtplib.SMTPAuthenticationError):return f'认证失败（{exc.smtp_code}），已暂停。请向服务商确认授权码、SMTP权限或OAuth要求，不要反复尝试密码。'
    if isinstance(exc,ssl.SSLCertVerificationError):return 'TLS证书校验失败，已暂停。请核对服务器、系统时间和证书链，不会关闭校验。'
    if isinstance(exc,(TimeoutError,ConnectionError)):return '连接中断或超时，已暂停。提交结果可能未知，请核查记录；不会自动重发。'
    if isinstance(exc,PermissionError):return '文件被占用或无写入权限。请关闭Excel后点击修复工作副本；已接受邮件不会重发。'
    if isinstance(exc,(ValueError,RuntimeError,InterruptedError)):return str(exc)
    return type(exc).__name__+'：操作已暂停，请核查本地记录或配置。'

class Results(ExcelResults):
    def __init__(self,cfg):
        super().__init__(cfg);old=json.loads(self.state.read_text('utf-8')) if self.state.exists() else {};self.expected=old.get('output_sha256')
        if self.source.suffix.lower()=='.csv':self.path=self.path.with_suffix('.csv')
    def persist(self):atomic_json(self.state,dict(rows=self.rows,source_sha256=self.source_hash,output=str(self.path),output_sha256=self.expected))
    def record(self,r):
        if r.get('is_test') or r['state']=='skipped':return
        self.rows[str(r['row'])]=r;self.persist();self.write()
    def write(self):
        if self.path.exists() and self.expected and digest(self.path)!=self.expected:raise ValueError('工作副本已被外部修改；已保留发送记录，请另存外部改动后修复，禁止因此重发。')
        if self.source.suffix.lower()=='.csv':
            import csv,datetime
            from core import export_csv
            if digest(self.source)!=self.source_hash:raise ValueError('原导入快照已变化，请重新预览。')
            with self.source.open(encoding='utf-8-sig',newline='') as f:reader=csv.DictReader(f);heads=list(reader.fieldnames);records=list(reader)
            note_col=self.cfg.get('note_col') or '备注'
            for col in (note_col,'本工具发送状态','本工具发送时间','本工具Message-ID','本工具SMTP回复'):
                if col not in heads:heads.append(col)
            for number,item in enumerate(records,2):
                r=self.rows.get(str(number))
                if not r:continue
                dt=datetime.datetime.fromisoformat(r['finished']);state=r['state'];note=('发送邮件开发信' if state=='accepted' else '发送失败' if state=='failed' else '发送状态待核实')+f'（{dt.month}.{dt.day}）'
                if state=='failed':note+='：'+r.get('reason','')
                original=item.get(note_col,'') or ''
                if note not in original.splitlines():item[note_col]=note if not original.strip() or original.strip()=='待发送邮件开发信' else original.rstrip()+'\n'+note
                item.update({'本工具发送状态':STATES.get(state,state),'本工具发送时间':r['finished'],'本工具Message-ID':r.get('message_id',''),'本工具SMTP回复':str(r.get('smtp_code',''))+' '+r.get('smtp_response','')})
            self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp.csv');export_csv(tmp,heads,[[r.get(c,'') for c in heads] for r in records]);tmp.replace(self.path)
        else:super().write()
        if self.path.exists():self.expected=digest(self.path)
        self.persist()

class Controller:
    def __init__(self,root=HOME,connector=smtp_connect,lease_factory=None,copy_checker=verify_copies):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.instance=(self.root/'instance.lock').open('a+b');self.instance.seek(0)
        if (self.root/'instance.lock').stat().st_size==0:self.instance.write(b'0');self.instance.flush()
        self.instance.seek(0)
        try:msvcrt.locking(self.instance.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:self.instance.close();raise ValueError('此独立工作区已有程序窗口，请使用现有窗口，不能多开任务。')
        self.ledger=Ledger(self.root/'data/history.sqlite3');self.connector=connector;self.copy_checker=copy_checker
        self.lease_factory=lease_factory or (lambda sender:AccountLease(sender,DATA_ROOT/'locks'))
        self.events=queue.Queue();self.lock=threading.RLock();self.pause_flag=threading.Event();self.stop_flag=threading.Event();self.thread=None;self.job=None
        self.status='idle';self.current='';self.current_email='';self.last='';self.countdown=0;self.logs=[]
        self.recover()
    def close(self):
        if self.busy:raise ValueError('任务仍在提交，请先安全停止并等待。')
        if not self.instance.closed:
            self.instance.seek(0);msvcrt.locking(self.instance.fileno(),msvcrt.LK_UNLCK,1);self.instance.close()
    @property
    def busy(self):return self.thread is not None and self.thread.is_alive()
    def log(self,text):
        line=now()+' '+text;self.logs.append(line);self.events.put(line)
        path=self.root/'logs/events.log';path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as f:f.write(line+'\n')
    def save(self):
        if self.job:atomic_json(self.root/'data/job.json',self.job)
    def recover(self):
        # Orphaned claims never become ready merely because the process restarted.
        with self.ledger.connect() as db:
            db.execute("UPDATE attempts SET state='unknown',finished=?,detail=coalesce(detail,'')||'；进程中断，禁止自动重试' WHERE state='sending'",(now(),))
        path=self.root/'data/job.json'
        if not path.exists():return
        self.job=json.loads(path.read_text('utf-8'));self.status='stopped'
        with self.ledger.connect() as db:records=list(db.execute('SELECT id,email,state,started,finished,message_id,company,subject,is_test FROM attempts ORDER BY id'))
        byemail={r[1]:r for r in records if not r[8]}
        for row in self.job['rows']:
            if row['email'] in byemail and row['state'] not in ('yellow','duplicate','invalid','blocked','history','template_error','skipped'):
                r=byemail[row['email']];row['state']=r[2]
                saved=self.root/f'data/attempts/{r[0]}-result.json'
                result=json.loads(saved.read_text('utf-8')) if saved.exists() else dict(attempt_id=r[0],row=row['row'],company=r[6],email=r[1],state=r[2],started=r[3],finished=r[4] or now(),message_id=r[5],subject=r[7],reason='从数据库恢复；不会自动发送')
                row['result']=result
        self.save();self.log('已恢复记录，真实发送保持停止；须本人预览后主动继续。')
    def suppression(self):return set().union(*(address_file(self.root/'config'/name) for name in ('已发邮箱.txt','已回复邮箱.txt','不再联系.txt')))
    def prepare(self,cfg):
        with self.lock:
            if self.busy:raise ValueError('任务仍在运行，请先安全停止。')
            cfg=public_config(cfg);cfg['storage']=str(self.root);all_templates=templates(self.root)
            if cfg.get('template_id') not in all_templates:raise ValueError('请保存并选择一个本地模板。')
            fields=customer_fields(cfg);customers=read_customers(cfg['file'],cfg['sheet'],cfg['company_col'],cfg['email_col'],cfg['note_col'],self.ledger.blocked(),self.suppression());rows=[]
            for c in customers:
                row=asdict(c);row['state']=row.pop('status');row['reason']='';row['template_id']=cfg['template_id']
                if row['state']=='ready':
                    try:
                        lang=fields[c.row].get(cfg.get('language_col')) if cfg.get('language_col') else None
                        if lang:
                            matches=[k for k,v in all_templates.items() if language(v['language'])==language(lang)]
                            if not matches:raise ValueError('没有匹配语言的本地模板：'+str(lang))
                            if len(matches)>1 and cfg['template_id'] not in matches:raise ValueError('该语言有多个模板，请明确选择对应模板或保留唯一匹配：'+str(lang))
                            row['template_id']=cfg['template_id'] if cfg['template_id'] in matches else matches[0]
                        build_message(c,fields[c.row],cfg,all_templates[row['template_id']])
                    except Exception as exc:row.update(state='template_error',reason=explain(exc))
                rows.append(row)
            self.job=dict(cfg=cfg,rows=rows,templates=all_templates,template_hash=template_fingerprint(all_templates,cfg),source_hash=digest(cfg['file']),created=now(),batch_number=0)
            reporter=Results(cfg);reporter.write();self.job['output']=str(reporter.path);self.status='prepared';self.save();self.log('预览已生成，未发送；工作副本：'+str(reporter.path));return rows
    def message(self,row):
        cfg=self.job['cfg'];fields=customer_fields(cfg);c=Customer(row['row'],row['company'],row['email'],row.get('note',''))
        return build_message(c,fields[c.row],cfg,self.job['templates'][row['template_id']])
    def check(self):
        if not self.job:raise ValueError('请先导入客户并生成预览。')
        cfg=self.job['cfg']
        if digest(cfg['file'])!=self.job['source_hash'] or template_fingerprint(templates(self.root),cfg)!=self.job['template_hash']:raise ValueError('模板、附件、签名或客户快照发生变化，请重新生成预览。')
    def start(self,password):
        with self.lock:
            if self.busy:raise ValueError('任务已在运行，不能重复开始。')
            self.check()
            if not password:raise ValueError('请在本地掩码框输入密码或授权码。')
            if not any(r['state']=='ready' for r in self.job['rows']):raise ValueError('没有未尝试的待发送客户。')
            self.stop_flag.clear();self.pause_flag.clear();self.status='running';self.job['batch_number']+=1;self.job['batch_processed']=0;self.job['batch_target']=min(self.job['cfg']['batch'],sum(r['state']=='ready' for r in self.job['rows']));self.save()
            self.thread=threading.Thread(target=self._work,args=(password,),daemon=False);self.thread.start()
    def pause(self):
        self.pause_flag.set();self.log('已请求暂停；若当前邮件正在提交，将等待结果落盘。')
    def resume(self,password=None):
        if self.busy:self.pause_flag.clear();self.log('继续当前批次；失败或未知客户不会重发。')
        else:self.start(password)
    def stop(self):
        self.stop_flag.set();self.pause_flag.clear();self.log('已请求安全停止；不会粗暴中断当前SMTP提交。')
    def wait_boundary(self,lease):
        while True:
            if self.stop_flag.is_set():raise InterruptedError('已安全停止，未提交的客户保留待发送。')
            if self.pause_flag.is_set():self.status='paused';time.sleep(.1);continue
            self.countdown=max(0,int(lease.next_after-time.time()+.99))
            if not self.countdown:break
            self.status='waiting';self.stop_flag.wait(min(.2,max(0,lease.next_after-time.time())))
        self.status='running'
    def _work(self,password):
        cfg=self.job['cfg'];reporter=None;results=[];sent=0
        try:
            reporter=Results(cfg)
            with self.lease_factory(cfg['sender']) as lease:
                for row in self.job['rows']:
                    if row['state']!='ready':continue
                    if sent>=cfg['batch']:break
                    self.current=row['company'];self.current_email=row['email'];self.wait_boundary(lease);self.check()
                    if cfg['cap'] and self.snapshot()['today']>=cfg['cap']:raise ValueError('已达到当日尝试上限；保留剩余客户，计数不会重置。')
                    if row['email'] in self.ledger.blocked()|self.suppression():row.update(state='skipped',reason='发送前最新历史/拒收/回复名单已有记录');self.save();continue
                    msg=self.message(row);self.wait_boundary(lease);lease.reserve(cfg['interval']);smtp=None
                    try:
                        self.status='submitting';self.log('正在提交：'+row['company']+' <'+row['email']+'>');smtp=self.connector(cfg,password)
                        result=submit(smtp,self.ledger,Customer(row['row'],row['company'],row['email']),msg,cfg)
                    finally:
                        lease.finished(cfg['interval'])
                        if smtp:
                            try:smtp.quit()
                            except Exception:smtp.close()
                    row.update(state=result['state'],result=result,reason=result.get('reason',''));sent+=1;self.job['batch_processed']=sent;results.append(result);self.last=row['company']+'：'+STATES.get(row['state'],row['state']);self.save();self.log(self.last)
                    try:reporter.record(result)
                    except Exception as exc:
                        self.job['excel_error']=explain(exc);self.save();raise ValueError('邮件结果已写入数据库；Excel保存失败，请修复副本，禁止因此重发。')
                    if result['state'] in ('failed','unknown'):raise InterruptedError('失败或状态待核实，已暂停本批；不会自动重试。')
                self.status='completed' if not any(r['state']=='ready' for r in self.job['rows']) else 'batch_done'
        except Exception as exc:
            self.status='stopped';self.last=explain(exc);self.log(self.last)
            with self.ledger.connect() as db:
                uncertain=list(db.execute("SELECT id,email,message_id FROM attempts WHERE state='sending' AND is_test=0"))
            for ident,email,mid in uncertain:
                self.ledger.finish(ident,'unknown','提交操作中断，结果待核实，禁止自动重试')
                for row in self.job['rows']:
                    if row['email']==email and row['state']=='ready':row.update(state='unknown',reason='持久提交意图存在，结果待核实')
        finally:
            if results:
                try:
                    note=self.copy_checker(cfg,password,results);self.log(note)
                    for row in self.job['rows']:
                        if row.get('result') in results:reporter.record(row['result'])
                except Exception as exc:self.log('副本或Excel核对未完成：'+type(exc).__name__+'；已接受状态保留，不重发。')
            password=None;self.countdown=0;self.save()
    def repair(self):
        if self.busy:raise ValueError('请先安全停止。')
        if not self.job:raise ValueError('没有待修复工作副本。')
        reporter=Results(self.job['cfg'])
        if reporter.path.exists() and reporter.expected and digest(reporter.path)!=reporter.expected:
            import shutil,uuid
            backup=reporter.path.with_name(reporter.path.stem+'_外部改动备份_'+uuid.uuid4().hex[:8]+reporter.path.suffix);shutil.copy2(reporter.path,backup);reporter.expected=digest(reporter.path);self.log('已保留外部修改备份：'+str(backup))
        for row in self.job['rows']:
            if row.get('result'):reporter.rows[str(row['row'])]=row['result']
        reporter.persist();reporter.write();self.job.pop('excel_error',None);self.save();self.log('工作副本已按持久发送结果修复，未发送任何邮件。')
    def snapshot(self,sender=None):
        rows=self.job['rows'] if self.job else [];counts={k:sum(r['state']==k for r in rows) for k in ('ready','accepted','failed','unknown')};counts['skipped']=sum(r['state'] not in ('ready','accepted','failed','unknown','sending') for r in rows)
        sender=sender or (self.job['cfg']['sender'] if self.job else '')
        with self.ledger.connect() as db:today=db.execute('SELECT count(*) FROM attempts WHERE sender=? AND substr(started,1,10)=?',(sender,now()[:10])).fetchone()[0]
        return dict(total=len(rows),counts=counts,status=self.status,current=self.current,email=self.current_email,last=self.last,countdown=self.countdown,today=today,batch=self.job.get('batch_number',0) if self.job else 0)
