"""Authorized local AI configuration bridge. Secrets are stdin/memory only."""
import argparse,json,sys,msvcrt,ssl,smtplib,threading
from pathlib import Path
from contextlib import contextmanager
from app_paths import USER_HOME,DATA_ROOT
from v2_model import DEFAULT,load_config,public_config,validate_account,save_config,SecureStore,build_message
from account_guard import AccountLease
from core import smtp_connect,Customer,Ledger,valid_email
from v2_delivery import submit

class ProfileBusyError(RuntimeError):pass

@contextmanager
def profile_lock(home):
    home=Path(home);home.mkdir(parents=True,exist_ok=True);path=home/'instance.lock';f=path.open('a+b');f.seek(0)
    if path.stat().st_size==0:f.write(b'0');f.flush()
    f.seek(0)
    try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:f.close();raise ProfileBusyError('配置目录正在被软件使用，请先安全停止并关闭。')
    try:yield
    finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1);f.close()

def safe_error(exc):
    from credentials import CredentialUnavailable
    if isinstance(exc,ProfileBusyError):return {'ok':False,'error':'profile_busy','next':'本软件配置目录正在使用；先通过其界面安全停止并关闭，不要结束其他邮件程序。'}
    if isinstance(exc,CredentialUnavailable):return {'ok':False,'error':'secure_storage_unavailable','next':'没有明文降级或写入配置；可检查系统安全存储，或使用GUI当次内存模式。'}
    if isinstance(exc,smtplib.SMTPAuthenticationError):return {'ok':False,'error':'authentication_failed','code':exc.smtp_code,'next':'核实SMTP授权码、登录密码、SMTP权限或OAuth要求；本次不重试。'}
    if isinstance(exc,ssl.SSLCertVerificationError):return {'ok':False,'error':'tls_certificate_failed','next':'核对主机名、系统时间与证书链；不会关闭验证。'}
    return {'ok':False,'error':type(exc).__name__,'next':'操作未完成。请检查配置、授权及安全存储可用性；不回显输入或异常原文。'}

def consent(payload,name):
    if payload.get('consent',{}).get(name) is not True:raise ValueError('缺少操作授权。')

def connection_test(cfg,password,connector=smtp_connect,lease_factory=AccountLease):
    if not password:raise ValueError('缺少当前账号凭据。')
    with lease_factory(cfg['sender']):
        client=connector(cfg,password)
        try:client.noop()
        finally:client.close()

def apply_configuration(payload,home=USER_HOME,store=None,connector=smtp_connect,lease_factory=AccountLease):
    """Public API for local AI tools; returns no secret values or raw exceptions."""
    consent(payload,'configure');consent(payload,'test_connection')
    account=payload.get('account',{})
    if any(k not in DEFAULT for k in account):raise ValueError('账户配置包含不支持字段。凭据应通过credential传入。')
    # Account edits preserve this user's existing limits, templates and import references.
    cfg=dict(load_config(home),**public_config(account));cfg=validate_account(cfg)
    credential=payload.get('credential',{});kind=credential.get('kind',cfg['credential_kind'])
    if kind not in ('password','smtp_authorization_code'):raise ValueError('不支持的凭据类型。')
    cfg['credential_kind']=kind;value=credential.get('value')
    with profile_lock(home):
        storage=store if store is not None else SecureStore()
        if value:
            if not isinstance(value,str):raise ValueError('凭据须为文字。')
            storage.write(cfg,value)
        else:value=storage.read(cfg)
        if not value:raise ValueError('当前账号没有可用凭据。')
        # No plain-text fallback. Do not save file if secure storage failed.
        save_config(cfg,home)
        try:connection_test(cfg,value,connector,lease_factory)
        finally:value=None
    return {'ok':True,'configured':True,'authentication':'success','emails_sent':0,'bulk_authorized':False}

def test_saved_configuration(payload,home=USER_HOME,store=None,connector=smtp_connect,lease_factory=AccountLease):
    consent(payload,'test_connection');cfg=validate_account(load_config(home))
    with profile_lock(home):
        storage=store if store is not None else SecureStore();value=storage.read(cfg)
        try:connection_test(cfg,value,connector,lease_factory)
        finally:value=None
    return {'ok':True,'authentication':'success','emails_sent':0,'bulk_authorized':False}

def send_test_message(payload,home=USER_HOME,store=None,connector=smtp_connect,lease_factory=AccountLease):
    consent(payload,'send_test');spec=payload.get('test_mail',{});recipient=spec.get('to','').strip()
    if not valid_email(recipient):raise ValueError('必须明确指定单一测试收件人。')
    cfg=validate_account(load_config(home));cfg['storage']=str(home)
    template=dict(format='text',body=spec.get('body') or 'This is a user-authorized OpenDesk Mail test.',subject='[TEST] '+spec.get('subject','OpenDesk Mail'),attachments=[])
    customer=Customer(0,'EXAMPLE TEST COMPANY',recipient);msg=build_message(customer,{},cfg,template)
    with profile_lock(home):
        storage=store if store is not None else SecureStore();value=storage.read(cfg)
        if not value:raise ValueError('当前账号凭据不可用。')
        with lease_factory(cfg['sender']) as lease:
            lease.wait(threading.Event());lease.reserve(cfg['interval']);client=None
            try:client=connector(cfg,value);result=submit(client,Ledger(Path(home)/'data/history.sqlite3'),customer,msg,cfg,test=True)
            finally:
                lease.finished(cfg['interval']);value=None
                if client:client.close()
    return {'ok':result['state']=='accepted','state':result['state'],'message_id':result.get('message_id'),'recipient_receipt_confirmed':False,'bulk_authorized':False}

class QuietParser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('参数无效。为防止回显，不显示原参数。')

def cli(argv=None,stdin=None,out=None):
    stream=sys.stdin if stdin is None else stdin;output=sys.stdout if out is None else out
    try:
        parser=QuietParser(description='OpenDesk Mail授权本机配置；JSON经标准输入传入，不接受命令行密码。')
        group=parser.add_mutually_exclusive_group(required=True)
        for name in ('apply','test-connection','send-test','validate-only'):group.add_argument('--'+name,action='store_true')
        args=parser.parse_args(argv)
        if hasattr(stream,'isatty') and stream.isatty():raise ValueError('请使用本机工具的安全标准输入或GUI，避免在回显终端粘贴凭据。')
        payload=json.load(stream)
        if args.validate_only:
            validate_account(dict(DEFAULT,**public_config(payload.get('account',{}))));result={'ok':True,'validated':True,'stored':False,'emails_sent':0,'bulk_authorized':False}
        elif args.apply:result=apply_configuration(payload)
        elif args.test_connection:result=test_saved_configuration(payload)
        else:result=send_test_message(payload)
    except Exception as exc:result=safe_error(exc)
    output.write(json.dumps(result,ensure_ascii=False)+'\n');return 0 if result.get('ok') else 1

if __name__=='__main__':
    for stream in (sys.stdin,sys.stdout):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    raise SystemExit(cli())
