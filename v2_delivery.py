"""Durable wire results, incremental Excel output and read-only Sent checks."""
import hashlib,json,os,re,smtplib
from datetime import datetime
from email import policy
from pathlib import Path
from core import BASE,now

def validate_inline(msg):
    import copy
    from mime_check import require_valid_inline_mime
    def remove_attachments(part):
        if part.is_multipart():
            part.set_payload([p for p in part.get_payload() if p.get_content_disposition()!='attachment'])
            for child in part.get_payload():remove_attachments(child)
    clean=copy.deepcopy(msg);remove_attachments(clean);return require_valid_inline_mime(clean.as_bytes(policy=policy.SMTP))

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def smtp_details(stage, code, reply, *, password='', message=None, raw=None):
    response = reply.decode('utf-8', 'replace') if isinstance(reply, bytes) else str(reply or '')
    codes = set(re.findall(r'(?m)^\s*(?:[245]\d\d[- ])?([245]\.\d{1,3}\.\d{1,3})(?=\s|$)', response))
    enhanced = next(iter(codes)) if len(codes) == 1 else ''
    if stage == 'AUTH':
        response = '认证回复原文已省略' if response else ''
    else:
        if password:
            response = response.replace(password, '[凭据已隐藏]')
        if stage == 'DATA' and response and message is not None:
            # Some servers quote submitted content in their diagnostics.
            reply_text = ' '.join(response.casefold().split())
            bodies = [raw.partition(b'\r\n\r\n')[2].decode('utf-8', 'replace')]
            for part in message.walk():
                if part.get_content_maintype() == 'text' and not part.is_multipart():
                    try:
                        bodies.append(part.get_content(errors='replace'))
                    except (LookupError, ValueError):
                        response = '邮件编码无法核对，回复原文已省略'
                        break
            if any(line.strip() and ' '.join(line.casefold().split()) in reply_text
                   for body in bodies for line in body.splitlines()):
                response = '回复包含邮件内容，原文已省略'
    return dict(smtp_stage=stage, smtp_code=code or '', smtp_enhanced_code=enhanced, smtp_response=response)


def smtp_summary(details):
    codes = ' '.join(str(details[k]) for k in ('smtp_code', 'smtp_enhanced_code') if details.get(k))
    return ' '.join(item for item in (details.get('smtp_stage'), codes) if item)


def smtp_failure(details):
    stage = details['smtp_stage']
    code = details['smtp_code']
    enhanced = details['smtp_enhanced_code']
    reply = details['smtp_response'].casefold()
    recipient_invalid = False
    if stage == 'AUTH' or code in (530, 534, 535, 538):
        reason = '发件账号认证失败，请核对凭据及 SMTP 权限'
    elif re.search(r'\b(quota|daily limit|sending limit|mailbox full)\b|配额|超额', reply) or enhanced.endswith(('.2.2', '.3.1')):
        reason = '服务器报告配额或存储上限，请核对服务商限制'
    elif re.search(r'throttl|rate[ -]?limit|too many|限流|频率', reply):
        reason = '服务器报告发送限流，请核对服务商限制'
    elif enhanced == '4.7.0' or code == 421:
        reason = '服务器暂时拒绝提交，可能限流或服务不可用'
    elif enhanced[2:4] == '7.' or re.search(r'policy|blocked|策略', reply):
        reason = '服务器策略拒收，请核对发件权限和服务商策略'
    elif stage == 'RCPT TO' and code in (550, 553) and (
        enhanced in ('5.1.1', '5.1.3') or re.fullmatch(
            r'(?:recipient address rejected:\s*)?(?:user unknown|no such user|recipient address does not exist|invalid recipient address)[.!]?',
            reply.strip())
    ):
        reason = '当前收件地址不存在或格式无效'
        recipient_invalid = True
    else:
        reason = '服务器拒绝操作，影响范围待核查'
    return f'{reason}（{smtp_summary(details)}）', recipient_invalid


def submit(smtp,ledger,c,msg,cfg,test=False,*,password=''):
    raw=msg.as_bytes(policy=policy.SMTP)
    if any(p.get_content_disposition()=='inline' for p in msg.walk()):
        from v2_delivery import validate_inline
        validate_inline(msg)
    ident=ledger.claim(cfg['sender'],c,str(msg['Subject']),cfg['cap'],str(msg['Message-ID']),test=test)
    if ident is None:return {'state':'skipped','row':c.row,'company':c.company,'email':c.email}
    r=dict(attempt_id=ident,row=c.row,company=c.company,email=c.email,subject=str(msg['Subject']),message_id=str(msg['Message-ID']),started=now(),state='unknown',is_test=test)
    dest=Path(cfg['storage'])/'data'/'attempts';dest.mkdir(parents=True,exist_ok=True)
    # Keep the ledger claim blocking if saving the wire intent itself fails.
    atomic_json(dest/f'{ident}-intent.json',r);(dest/f'{ident}.eml').write_bytes(raw)
    response=None;final_data_reply=None;stage='SMTP 提交'
    originals={}
    def capture(command,original):
        def run(*args,**kwargs):
            nonlocal final_data_reply,stage
            stage=command
            reply=original(*args,**kwargs)
            if command=='DATA':final_data_reply=reply
            return reply
        return run
    try:
        for name,command in (('mail','MAIL FROM'),('rcpt','RCPT TO'),('data','DATA')):
            original=getattr(smtp,name,None)
            if original is not None:
                originals[name]=original
                setattr(smtp,name,capture(command,original))
        refused=smtp.sendmail(cfg['sender'],[c.email],raw)
        if refused:raise smtplib.SMTPRecipientsRefused(refused)
    except smtplib.SMTPRecipientsRefused as exc:
        stage='RCPT TO'
        response=exc.recipients.get(c.email)
    except smtplib.SMTPResponseException as exc:
        if isinstance(exc,smtplib.SMTPSenderRefused):stage='MAIL FROM'
        if isinstance(exc,smtplib.SMTPDataError):stage='DATA'
        if isinstance(exc,smtplib.SMTPAuthenticationError):stage='AUTH'
        response=(exc.smtp_code,exc.smtp_error)
    except Exception as exc:
        r['smtp_error_type']=type(exc).__name__
    finally:
        for name,original in originals.items():setattr(smtp,name,original)
    code,reply=final_data_reply or response or (None,None)
    r.update(smtp_details(stage,code,reply,password=password,message=msg,raw=raw))
    if final_data_reply and final_data_reply[0]==250:
        r['state']='accepted'
    elif code is not None and 400 <= code < 600:
        reason,recipient_invalid=smtp_failure(r)
        r.update(state='failed',reason=reason,recipient_invalid=recipient_invalid)
    else:
        r['reason']=f'{stage} 阶段未能确认服务器是否接受邮件'
    r['finished']=now();state='test_accepted' if test and r['state']=='accepted' else r['state']
    ledger.finish(ident,state,('服务器已接受（未确认客户收到）' if r['state']=='accepted' else r['reason'])+f"；{smtp_summary(r)} {r['smtp_response']}")
    atomic_json(dest/f'{ident}-result.json',r);return r

def verify_copies(cfg,password,results):
    if not cfg.get('imap_host') or not cfg.get('imap_sent_folder'):return '未配置IMAP/Sent文件夹；副本未核实，本地记录已保留'
    import mail_archive
    from email.parser import BytesParser
    client=mail_archive.connect(cfg,password)
    try:
        status,_=client.select(mail_archive.quoted(cfg['imap_sent_folder']),readonly=True)
        if status!='OK':raise ValueError('无法只读打开配置的Sent文件夹')
        status,data=client.uid('fetch','1:*','(UID FLAGS BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
        if status!='OK':raise ValueError('副本邮件头读取失败')
        ids=[]
        for item in data:
            if isinstance(item,tuple) and b'\\Deleted' not in item[0]:ids.append(str(BytesParser(policy=policy.default).parsebytes(item[1]).get('Message-ID','')).strip())
        for r in results:
            if r['state']=='accepted':r['sent_folder_matches']=ids.count(r['message_id'])
        return '只读核查已完成；副本可能延迟出现，未核实不触发APPEND或重发'
    finally:client.logout()

class ExcelResults:
    def __init__(self,cfg):
        self.cfg=cfg;self.source=Path(cfg['file']);self.source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        key=hashlib.sha256((str(self.source.resolve())+'|'+self.source_hash+'|'+cfg['sheet']+'|'+cfg['sender']).encode()).hexdigest()[:20]
        self.path=Path(cfg['storage'])/'data'/'results'/(self.source.stem+'_'+key+'_发送更新.xlsx');self.state=Path(cfg['storage'])/'data'/'results'/(key+'.json')
        self.rows=json.loads(self.state.read_text('utf-8')).get('rows',{}) if self.state.exists() else {}
    def record(self,r):
        if r.get('is_test') or r['state']=='skipped':return
        self.rows[str(r['row'])]=r;atomic_json(self.state,dict(rows=self.rows,source_sha256=self.source_hash,output=str(self.path)))
        self.write()
    def write(self):
        if self.source.suffix.lower()!='.xlsx':return
        if hashlib.sha256(self.source.read_bytes()).hexdigest()!=self.source_hash:raise ValueError('原客户表已变化，已保存发送日志并暂停，禁止覆盖或重发')
        from openpyxl import load_workbook
        from openpyxl.styles import PatternFill
        book=load_workbook(self.source)
        try:
            sh=book[self.cfg['sheet']];heads=[str(c.value or '').strip() for c in sh[1]];ci=heads.index(self.cfg['company_col'])+1
            def column(label):
                if label not in heads:heads.append(label);sh.cell(1,len(heads),label);sh.column_dimensions[sh.cell(1,len(heads)).column_letter].width=38
                return heads.index(label)+1
            ni=column(self.cfg['note_col'] or '备注');si=column('本工具发送状态');ti=column('本工具发送时间');mi=column('本工具Message-ID');ri=column('本工具SMTP回复');ai=column('本工具副本核对')
            for r in self.rows.values():
                n=r['row'];dt=datetime.fromisoformat(r['finished']);day=f'{dt.month}.{dt.day}';state=r['state'];note=''
                if state=='accepted':sh.cell(n,ci).fill=PatternFill('solid',fgColor='FFFFFF00');note=f'发送邮件开发信（{day}）'
                elif state=='failed':note=f'发送失败（{day}）：'+r.get('reason','')
                elif state=='unknown':note=f'发送状态待核实（{day}）'
                existing=str(sh.cell(n,ni).value or '')
                if note and note not in existing.splitlines():sh.cell(n,ni,note if not existing.strip() or existing.strip()=='待发送邮件开发信' else existing.rstrip()+'\n'+note)
                sh.cell(n,si,{'accepted':'SMTP服务器已接受，未确认客户收到','failed':'发送失败','unknown':'发送状态待核实'}[state]);sh.cell(n,ti,dt.replace(tzinfo=None)).number_format='yyyy-mm-dd hh:mm:ss'
                sh.cell(n,mi,r.get('message_id',''));sh.cell(n,ri,str(r.get('smtp_code',''))+' '+r.get('smtp_response',''));sh.cell(n,ai,'已核实'+str(r['sent_folder_matches'])+'份' if r.get('sent_folder_matches') else '未核实（不重发）')
            self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp.xlsx');book.save(temp);os.replace(temp,self.path)
        finally:book.close()
