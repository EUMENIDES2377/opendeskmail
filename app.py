"""Local Windows/Tkinter desktop application; no web server or cloud credentials."""
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from email.header import decode_header, make_header
from pathlib import Path
from core import (BASE, Customer, Ledger, STATUSES, address_file, export_csv,
                  normalize, read_customers, render_message, send_one,
                  sheet_names, smtp_connect, valid_email)
from app_paths import USER_HOME as BASE
from credentials import CredentialStore, CredentialUnavailable
from html_signature import load_signature, message_plain, preview_document

DEFAULT_SUBJECT = ''
DEFAULT_SETTINGS = {
    'file':'', 'sheet':'', 'company_col':'公司名称', 'email_col':'邮箱', 'note_col':'备注',
    'host':'', 'port':'465', 'security':'SSL/TLS', 'sender':'',
    'username':'', 'sender_name':'', 'password':'',
    'interval':'60', 'cap':'100', 'batch':'10', 'test_to':'', 'subject':DEFAULT_SUBJECT,
    'signature_html':'', 'imap_host':'', 'imap_port':'993', 'imap_security':'SSL/TLS',
    'archive_status':'尚未核实服务器自动保存；当前仅保留本工具本地发送记录',
    'imap_sent_folder':'',
}

class App:
    smtp_for_check=staticmethod(smtp_connect)
    def __init__(self, root):
        self.root = root
        root.title('OpenDesk Mail')
        root.geometry(f'{min(1120, root.winfo_screenwidth()-80)}x{min(840, root.winfo_screenheight()-100)}')
        root.minsize(760, 540)
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            tkfont.nametofont(name).configure(family='Microsoft YaHei UI', size=10)
        self.ledger = Ledger(BASE/'data'/'send_history.sqlite3')
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.customers, self.plan, self.stamp = [], [], None
        self.v = {key:tk.StringVar(value=value) for key,value in DEFAULT_SETTINGS.items()}
        self.remember = tk.BooleanVar(value=False)
        self.archive_enabled = tk.BooleanVar(value=False)
        self.credential_status = tk.StringVar(value='凭据仅在本次运行内存中；可选 Windows 凭据管理器。')
        settings = BASE/'settings.json'
        if settings.exists():
            try:
                data = json.loads(settings.read_text(encoding='utf-8'))
                for key,value in data.items():
                    if key in self.v and key != 'password':
                        self.v[key].set(str(value))
                self.archive_enabled.set(data.get('archive_enabled') is True)
            except (OSError, ValueError):
                pass
        report_path=BASE/'verification'/'email-verification.json'
        if report_path.exists():
            try:
                report=json.loads(report_path.read_text(encoding='utf-8'))
                if report.get('sender')==self.v['sender'].get() and report.get('smtp_host')==self.v['host'].get():
                    self.v['archive_status'].set(report.get('sent_copy','尚未核实'))
                    self.v['imap_sent_folder'].set(report.get('sent_folder',''))
            except (OSError,ValueError):
                pass
        self.build()
        self.load_credential()
        for key in ('host', 'port', 'security', 'sender', 'username'):
            self.v[key].trace_add('write', self.account_changed)
        if self.v['file'].get() and Path(self.v['file'].get()).is_file():
            try:
                self.sheets['values'] = sheet_names(self.v['file'].get())
            except Exception:
                self.status.set('已保存客户文件不可读取，请重新选择。')
        self._poll_job=root.after(150, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def entry(self, parent, label, key, row, col, width=22, secret=False):
        ttk.Label(parent, text=label).grid(row=row,column=col,sticky='w',padx=5,pady=4)
        widget = ttk.Entry(parent,textvariable=self.v[key],width=width,show='*' if secret else '')
        widget.grid(row=row,column=col+1,sticky='ew',padx=5,pady=4)
        return widget

    def button(self, parent, text, cmd):
        b = ttk.Button(parent,text=text,command=cmd)
        b.pack(side='left',padx=4,pady=5)
        self.actions.append(b)
        return b

    def scroll_page(self, parent):
        frame = ttk.Frame(parent)
        canvas = tk.Canvas(frame, highlightthickness=0)
        bar = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas, padding=10)
        item = canvas.create_window(0, 0, window=content, anchor='nw')
        content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        def wheel(event):
            canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), 'units')
        def bind_widgets(widget):
            if not isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
                widget.bind('<MouseWheel>', wheel, add='+')
            for child in widget.winfo_children():
                bind_widgets(child)
        self.root.after_idle(lambda: bind_widgets(content))
        return frame, content

    def build(self):
        self.actions=[]
        outer=ttk.Frame(self.root,padding=10)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='OpenDesk Mail',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w')
        ttk.Label(outer,text='导入客户 → 生成预览 → 核对名单 → 逐封发送。密码可仅保留内存或保存到 Windows 凭据管理器。',wraplength=720).pack(anchor='w',pady=(2,8))
        tabs=ttk.Notebook(outer)
        tabs.pack(fill='both',expand=True)
        page_frame,page=self.scroll_page(tabs)
        smtp_frame,smtp=self.scroll_page(tabs)
        tabs.add(page_frame,text='客户与邮件')
        tabs.add(smtp_frame,text='邮箱设置与发送速度')
        source=ttk.LabelFrame(page,text='客户表（第1行是表头，支持 .xlsx / UTF-8 CSV）',padding=6)
        source.pack(fill='x')
        self.entry(source,'文件','file',0,0,70)
        self.choose=ttk.Button(source,text='选择文件',command=self.pick)
        self.choose.grid(row=0,column=2,padx=5)
        self.actions.append(self.choose)
        ttk.Label(source,text='工作表').grid(row=1,column=0,sticky='w',padx=5)
        self.sheets=ttk.Combobox(source,textvariable=self.v['sheet'],state='readonly')
        self.sheets.grid(row=1,column=1,sticky='ew',padx=5)
        columns=ttk.Frame(source)
        columns.grid(row=2,column=0,columnspan=3,sticky='w')
        self.entry(columns,'公司列','company_col',0,0,13)
        self.entry(columns,'邮箱列','email_col',0,2,13)
        self.entry(columns,'备注列','note_col',0,4,13)
        source.columnconfigure(1,weight=1)
        ttk.Label(page,text='主题').pack(anchor='w',pady=(7,0))
        ttk.Entry(page,textvariable=self.v['subject']).pack(fill='x')
        ttk.Label(page,text='正文（{{company}} 自动替换公司名；{{email}} 邮箱；{{note}} 备注）').pack(anchor='w',pady=(6,0))
        body_frame=ttk.Frame(page)
        body_frame.pack(fill='both',expand=True,pady=3)
        self.body=tk.Text(body_frame,height=11,wrap='word',font=('Microsoft YaHei UI',10),undo=True)
        body_bar=ttk.Scrollbar(body_frame,command=self.body.yview)
        self.body.configure(yscrollcommand=body_bar.set)
        body_bar.pack(side='right',fill='y')
        self.body.pack(side='left',fill='both',expand=True)
        self.body.insert('1.0',(BASE/'email_body.txt').read_text(encoding='utf-8'))
        controls=ttk.Frame(page)
        controls.pack(fill='x')
        self.button(controls,'1. 生成预览',self.preview)
        self.button(controls,'查看选中邮件',self.show_selected)
        controls2=ttk.Frame(page)
        controls2.pack(fill='x')
        self.button(controls2,'2. 正式发送本批',self.send_batch)
        self.stop_button=ttk.Button(controls2,text='暂停后续发送',command=self.stop_event.set)
        self.stop_button.pack(side='left',padx=4)
        self.button(controls2,'导出名单与记录',self.export)
        tree_frame=ttk.Frame(page)
        tree_frame.pack(fill='both',expand=True,pady=5)
        self.tree=ttk.Treeview(tree_frame,columns=('row','company','email','status'),show='headings',height=6,selectmode='browse')
        for name,label,width in [('row','原表行号',70),('company','公司名',300),('email','邮箱',300),('status','状态',220)]:
            self.tree.heading(name,text=label)
            self.tree.column(name,width=width,stretch=name!='row')
        tree_bar=ttk.Scrollbar(tree_frame,orient='vertical',command=self.tree.yview)
        tree_x=ttk.Scrollbar(tree_frame,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_bar.set,xscrollcommand=tree_x.set)
        tree_bar.pack(side='right',fill='y')
        tree_x.pack(side='bottom',fill='x')
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<Double-1>',lambda e:self.show_selected())
        self.status=tk.StringVar(value='尚未生成预览。SMTP默认值不代表已核实的公司邮箱配置。')
        status_label=ttk.Label(outer,textvariable=self.status,wraplength=700)
        status_label.pack(anchor='w',pady=(8,0),fill='x')
        status_label.bind('<Configure>',lambda e:status_label.configure(wraplength=max(240,e.width)))
        self.entry(smtp,'SMTP服务器','host',0,0,35)
        self.entry(smtp,'端口','port',1,0,35)
        ttk.Label(smtp,text='加密方式').grid(row=2,column=0,sticky='w',padx=5)
        ttk.Combobox(smtp,textvariable=self.v['security'],values=['SSL/TLS','STARTTLS'],state='readonly').grid(row=2,column=1,sticky='ew',padx=5)
        self.entry(smtp,'发件邮箱','sender',3,0,35)
        self.entry(smtp,'登录用户名（空=邮箱）','username',4,0,35)
        self.entry(smtp,'发件人显示名称','sender_name',5,0,35)
        self.entry(smtp,'密码 / SMTP授权码','password',6,0,35,True)
        self.entry(smtp,'发送间隔（秒）','interval',7,0,35)
        self.entry(smtp,'每日尝试上限（0=不限）','cap',8,0,35)
        self.entry(smtp,'每批最多发送','batch',9,0,35)
        self.entry(smtp,'测试邮件收件邮箱','test_to',10,0,35)
        btns=ttk.Frame(smtp)
        btns.grid(row=11,column=0,columnspan=2,sticky='w',pady=8)
        self.button(btns,'保存设置（不含密码）',self.save)
        self.button(btns,'仅测试连接',self.test_connection)
        self.button(btns,'发送测试邮件',self.test_mail)
        creds=ttk.Frame(smtp)
        creds.grid(row=12,column=0,columnspan=3,sticky='w')
        ttk.Checkbutton(creds,text='记住凭据（Windows 凭据管理器）',variable=self.remember).pack(side='left')
        self.button(creds,'输入 / 更新凭据',self.prompt_credential)
        self.button(creds,'删除已保存凭据',self.delete_credential)
        ttk.Label(smtp,textvariable=self.credential_status,wraplength=640).grid(row=13,column=0,columnspan=3,sticky='w',pady=6)
        files=ttk.Frame(smtp)
        files.grid(row=14,column=0,columnspan=3,sticky='w')
        self.button(files,'编辑已发邮箱',lambda:self.open_local('已发邮箱.txt'))
        self.button(files,'编辑不再联系名单',lambda:self.open_local('不再联系.txt'))
        self.button(files,'编辑纯文字签名',lambda:self.open_local('signature.txt'))
        self.entry(smtp,'HTML签名文件','signature_html',15,0,44)
        self.button_frame=ttk.Frame(smtp)
        self.button_frame.grid(row=16,column=0,columnspan=3,sticky='w')
        self.button(self.button_frame,'选择原HTML签名',self.pick_signature)
        self.button(self.button_frame,'预览HTML签名',self.preview_signature)
        ttk.Label(smtp,textvariable=self.v['archive_status'],wraplength=640).grid(row=17,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Label(smtp,text='速度和上限请以邮箱服务商规定为准，每日上限含失败和测试邮件。\nHTML签名使用原始样式和CID内嵌图片；纯文字签名仅在无HTML签名时使用。\n已接受及结果未知的客户邮件不会自动重发。副本失败不改变发送已接受状态。\n标黄支持公司名单元格直接实色RGB/索引色；主题色、条件格式请另补已发名单。\n原Excel保持不变；独立版逐封保存结果Excel及本地记录。',wraplength=640,justify='left').grid(row=18,column=0,columnspan=3,sticky='w',padx=5,pady=12)
        verification=ttk.Frame(smtp)
        verification.grid(row=19,column=0,columnspan=3,sticky='w')
        # Account validation is available through explicit connection/test buttons.
        self.entry(smtp,'IMAP服务器','imap_host',20,0,44)
        self.entry(smtp,'IMAP SSL/TLS端口','imap_port',21,0,44)
        self.entry(smtp,'实际Sent文件夹（服务器编码）','imap_sent_folder',22,0,44)
        ttk.Label(smtp,text='副本仅按Message-ID只读核查；不自动追加归档，不因此重发。').grid(row=23,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Label(smtp,text='IMAP可选；服务器和Sent文件夹须向邮箱管理员核实。未配置时显示副本未核实，本地发送记录始终保留。',wraplength=640).grid(row=24,column=0,columnspan=3,sticky='w')

    def verify_deployment(self):
        if self.busy:
            return
        self.test_connection()

    def config(self):
        cfg={k:v.get().strip() for k,v in self.v.items() if k!='password'}
        cfg['archive_enabled']=self.archive_enabled.get()
        for key in ('port','cap','batch'):
            cfg[key]=int(cfg[key])
            if cfg[key]<(0 if key=='cap' else 1):
                raise ValueError('端口、每日上限、每批数量必须是正整数。')
        cfg['interval']=float(cfg['interval'])
        if not 1<=cfg['port']<=65535 or not 60<=cfg['interval']<=86400:
            raise ValueError('端口或发送间隔不正确。')
        cfg['sender']=normalize(cfg['sender'])
        return cfg

    def account_changed(self, *_):
        self.v['password'].set('')
        self.remember.set(False)
        self.credential_status.set('账号或服务器已变化，已清空内存凭据。连接前将查询对应账号的凭据管理器。')

    def load_credential(self):
        try:
            saved=CredentialStore().read(self.config())
            if saved:
                self.v['password'].set(saved)
                self.remember.set(True)
                self.credential_status.set('已从 Windows 凭据管理器读取当前账号凭据（掩码显示）。')
            return bool(saved)
        except CredentialUnavailable as exc:
            self.credential_status.set(str(exc))
        except ValueError:
            self.credential_status.set('请先完成服务器配置，再读取该账号的已保存凭据。')
        return False

    def prompt_credential(self, on_ready=None):
        try:
            cfg=self.config()
            if not cfg['host']:
                raise ValueError('缺少SMTP服务器：Foxmail右上角菜单 → 设置 → 账号 → 您自己的账号 → 服务器。')
        except Exception as exc:
            self.error(exc)
            return
        top=tk.Toplevel(self.root)
        top.title('本地邮箱凭据输入（不会写入配置或日志）')
        top.transient(self.root)
        top.resizable(False,False)
        ttk.Label(top,text=f"{cfg['sender']}\n{cfg['host']}:{cfg['port']}  {cfg['security']}\n请输入邮箱密码或服务商要求的SMTP授权码。",padding=12).pack(anchor='w')
        secret=tk.StringVar()
        field=ttk.Entry(top,textvariable=secret,show='*',width=46)
        field.pack(padx=12,pady=5,fill='x')
        remember=tk.BooleanVar(value=self.remember.get())
        ttk.Checkbutton(top,text='记住凭据（仅保存到 Windows 凭据管理器）',variable=remember).pack(padx=12,pady=5,anchor='w')
        ttk.Label(top,text='取消后可继续使用导入和预览功能，不会发送邮件。',padding=12).pack(anchor='w')
        def accept():
            value=secret.get()
            if not value:
                field.focus_set()
                return
            self.v['password'].set(value)
            self.remember.set(remember.get())
            if remember.get():
                try:
                    CredentialStore().write(cfg,value)
                    self.credential_status.set('凭据已保存到 Windows 凭据管理器；可随时更新或删除。')
                except CredentialUnavailable as exc:
                    self.remember.set(False)
                    self.credential_status.set(str(exc))
                    messagebox.showwarning('仅本次运行可用',str(exc),parent=top)
            else:
                self.credential_status.set('凭据仅保留在本次运行内存中。')
            secret.set('')
            top.destroy()
            if on_ready:
                self.root.after_idle(on_ready)
        def cancel():
            secret.set('')
            top.destroy()
            self.status.set('未输入凭据；SMTP认证及测试邮件尚未执行。')
        buttons=ttk.Frame(top,padding=10)
        buttons.pack(fill='x')
        ttk.Button(buttons,text='确认输入',command=accept).pack(side='left',padx=5)
        ttk.Button(buttons,text='取消',command=cancel).pack(side='left',padx=5)
        top.protocol('WM_DELETE_WINDOW',cancel)
        top.bind('<Return>',lambda e:accept())
        self.root.deiconify()
        top.update_idletasks()
        x=max(0,(top.winfo_screenwidth()-top.winfo_reqwidth())//2)
        y=max(0,(top.winfo_screenheight()-top.winfo_reqheight())//2)
        top.geometry(f'+{x}+{y}')
        top.deiconify()
        top.lift()
        # The user must enter credentials locally. Keep this short-lived modal
        # visible rather than silently leaving it behind the chat window.
        top.attributes('-topmost',True)
        top.grab_set()
        field.focus_force()

    def delete_credential(self):
        try:
            CredentialStore().delete(self.config())
            self.v['password'].set('')
            self.remember.set(False)
            self.credential_status.set('当前账号的已保存凭据及内存凭据已清除。')
        except Exception as exc:
            self.error(exc)

    def require_credential(self, resume):
        if self.v['password'].get() or self.load_credential():
            return True
        self.prompt_credential(resume)
        return False

    def pick_signature(self):
        path=filedialog.askopenfilename(filetypes=[('原HTML签名','*.htm *.html')])
        if path:
            try:
                load_signature(path)
                self.v['signature_html'].set(path)
                self.stamp=None
            except Exception as exc:
                self.error(exc)

    def render(self,customer,subject,cfg):
        return render_message(customer,subject,self.body.get('1.0','end-1c'),cfg['sender'],cfg['sender_name'],
                              (BASE/'signature.txt').read_text(encoding='utf-8-sig'),
                              signature_html=cfg.get('signature_html') or None)

    def open_html_preview(self,msg):
        import webbrowser
        path=BASE/'data'/'preview.html'
        path.parent.mkdir(exist_ok=True)
        path.write_text(preview_document(msg),encoding='utf-8')
        webbrowser.open(path.resolve().as_uri())
        self.status.set('已在浏览器打开HTML渲染预览（不会发送）；实际收信外观仍需核对。')

    def preview_signature(self):
        try:
            cfg=self.config()
            if not cfg.get('signature_html'):
                raise ValueError('请先选择原HTML签名文件。')
            self.open_html_preview(self.render(Customer(0,'TEST COMPANY',cfg['sender']), '[TEST] '+cfg['subject'],cfg))
        except Exception as exc:
            self.error(exc)

    def save(self):
        try:
            cfg=self.config()
            (BASE/'settings.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
            (BASE/'email_body.txt').write_text(self.body.get('1.0','end-1c'),encoding='utf-8')
            if self.remember.get() and self.v['password'].get():
                try:
                    CredentialStore().write(cfg,self.v['password'].get())
                    self.credential_status.set('当前凭据已更新到 Windows 凭据管理器。')
                except CredentialUnavailable as exc:
                    self.remember.set(False)
                    self.credential_status.set(str(exc))
                    messagebox.showwarning('凭据仅保留在内存',str(exc))
            self.status.set('设置和正文已保存；密码未写入文件。')
        except Exception as exc:
            self.error(exc)

    def pick(self):
        path=filedialog.askopenfilename(filetypes=[('客户表','*.xlsx *.csv')])
        if not path:
            return
        try:
            names=sheet_names(path)
            self.v['file'].set(path)
            self.sheets['values']=names
            self.v['sheet'].set(names[0])
            self.stamp=None
        except Exception as exc:
            self.error(exc)

    def load_plan(self):
        cfg=self.config()
        signature=(BASE/'signature.txt').read_text(encoding='utf-8-sig')
        if cfg.get('signature_html'):
            signature=load_signature(cfg['signature_html']).fingerprint
        history=address_file(BASE/'已发邮箱.txt') | self.ledger.blocked()
        customers=read_customers(cfg['file'],cfg['sheet'],cfg['company_col'],cfg['email_col'],cfg['note_col'],history,address_file(BASE/'不再联系.txt'))
        body=self.body.get('1.0','end-1c')
        planned=[]
        for c in customers:
            if c.status=='ready' and len(planned)<cfg['batch']:
                msg=self.render(c,cfg['subject'],cfg)
                planned.append((c,msg))
        # Exclude regenerated Date/Message-ID from the preview fingerprint.
        stamp=hashlib.sha256(json.dumps([cfg,body,signature,[c.__dict__ for c in customers]],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return cfg,customers,planned,stamp

    def preview(self):
        try:
            _,self.customers,self.plan,self.stamp=self.load_plan()
            self.tree.delete(*self.tree.get_children())
            for i,c in enumerate(self.customers):
                self.tree.insert('', 'end', iid=str(i),values=(c.row,c.company,c.email,STATUSES[c.status]))
            ready=sum(c.status=='ready' for c in self.customers)
            self.status.set(f'共 {len(self.customers)} 行，待发送 {ready}，跳过 {len(self.customers)-ready}；本批 {len(self.plan)} 封。生成预览没有发送邮件。')
        except Exception as exc:
            self.stamp=None
            self.error(exc)

    def show_selected(self):
        try:
            selection=self.tree.selection()
            if not selection:
                raise ValueError('请先生成预览并选中一行。')
            c=self.customers[int(selection[0])]
            cfg=self.config()
            msg=self.render(c,cfg['subject'],cfg)
            top=tk.Toplevel(self.root)
            top.title('邮件预览（不会发送）')
            top.geometry(f'{min(950,self.root.winfo_screenwidth()-100)}x{min(720,self.root.winfo_screenheight()-140)}')
            text=tk.Text(top,wrap='word',width=95,height=30,font=('Microsoft YaHei UI',10))
            subject=str(make_header(decode_header(msg['Subject'])))
            payload=message_plain(msg)
            text.insert('1.0',f'收件人：{c.email}\n主题：{subject}\n状态：{STATUSES[c.status]}\n\n{payload}')
            text.config(state='disabled')
            bar=ttk.Scrollbar(top,command=text.yview)
            text.configure(yscrollcommand=bar.set)
            ttk.Button(top,text='打开HTML渲染预览',command=lambda:self.open_html_preview(msg)).pack(side='bottom',fill='x')
            bar.pack(side='right',fill='y')
            text.pack(side='left',fill='both',expand=True)
        except Exception as exc:
            self.error(exc)

    def start(self, fn):
        if self.busy:
            return
        self.busy=True
        self.stop_event.clear()
        for b in self.actions:
            b.config(state='disabled')
        def run():
            try:
                fn()
            except Exception as exc:
                self.events.put(('error',self.safe_error(exc)))
            finally:
                self.events.put(('done',None))
        threading.Thread(target=run,daemon=True).start()

    @staticmethod
    def safe_error(exc):
        import smtplib
        import ssl
        if isinstance(exc,smtplib.SMTPAuthenticationError):
            response=exc.smtp_error.decode('utf-8',errors='ignore') if isinstance(exc.smtp_error,bytes) else ''
            if any(word in response.lower() for word in ('oauth','xoauth2')):
                next_step='服务器响应要求OAuth；需要适配OAuth登录，不能继续使用普通密码。'
            elif any(word in response.lower() for word in ('授权码','授权密码','app password','authorization code')):
                next_step='服务器响应要求客户端授权码；请在服务商账号安全设置中生成，并在本地输入框更新。'
            else:
                next_step='请核实客户端授权码、账号权限或OAuth要求；仅凭此错误不能断定具体原因。'
            return f'SMTPAuthenticationError（{exc.smtp_code}）：服务器拒绝认证，已停止且不自动重试。'+next_step
        if isinstance(exc,ssl.SSLCertVerificationError):
            return 'SSLCertVerificationError：TLS证书验证失败，已停止；不会关闭证书校验。'
        if isinstance(exc,ValueError):
            return str(exc)
        return type(exc).__name__+'：操作已暂停；请核查配置和记录。不会自动重发。'

    def send_batch(self):
        try:
            cfg,_,plan,stamp=self.load_plan()
            if self.stamp!=stamp:
                raise ValueError('名单、模板或设置已变化，请先重新生成预览。')
            if not plan:
                raise ValueError('没有可以发送的客户。')
            if not self.require_credential(self.send_batch):
                return
            password=self.v['password'].get()
            if not cfg['host'] or not password:
                raise ValueError('请先填写SMTP服务器和密码/授权码。')
            if not messagebox.askyesno('正式发送',f'将从 {cfg["sender"]} 逐封发送 {len(plan)} 封邮件。\n请确认本轮手动已发客户已补入记录。\n\n现在启动本批发送？'):
                return
            self.start(lambda:self.deliver(cfg,password,plan))
        except Exception as exc:
            self.error(exc)

    def deliver(self,cfg,password,plan,test=False):
        smtp=smtp_connect(cfg,password)
        archive_client=None
        archive_error=None
        def archive(msg):
            nonlocal archive_client,archive_error
            import mail_archive
            try:
                if archive_error:
                    raise archive_error
                if not cfg.get('imap_sent_folder'):
                    raise ValueError('缺少已核实的Sent文件夹；当前仅保留本地记录。')
                if archive_client is None:
                    archive_client=mail_archive.connect(cfg,password)
                mail_archive.archive_to_verified_sent(archive_client,cfg['imap_sent_folder'],msg)
                self.events.put(('archive_status','IMAP副本已保存，或已查到服务器自动保存的同一Message-ID。'))
            except Exception as exc:
                archive_error=exc
                self.events.put(('archive_status','发送已接受，副本保存失败（'+type(exc).__name__+'）；禁止因此重发，后续副本不自动重试登录。'))
                raise
        try:
            for i,(c,msg) in enumerate(plan):
                if self.stop_event.is_set():
                    break
                # Re-read external suppression files before each message.
                if c.email in address_file(BASE/'不再联系.txt') | address_file(BASE/'已发邮箱.txt'):
                    self.events.put(('status',f'已跳过 {c.company}：外部名单已更新'))
                    continue
                state=send_one(smtp,self.ledger,c,msg,cfg['sender'],cfg['cap'],test=test,
                               archive=archive if cfg.get('archive_enabled') else None)
                self.events.put(('status',f'{i+1}/{len(plan)} {c.company}：'+('服务器已接受' if state=='accepted' else '已有记录，已跳过')))
                if i<len(plan)-1 and self.stop_event.wait(cfg['interval']):
                    break
        finally:
            smtp.close()
            if archive_client is not None:
                try:
                    archive_client.logout()
                except Exception:
                    pass
        self.events.put(('status','本批已结束。请查看发送记录；继续下一批前重新生成预览。'))

    def test_connection(self):
        try:
            if not self.require_credential(self.test_connection):
                return
            cfg=self.config()
            password=self.v['password'].get()
            def work():
                smtp=smtp_connect(cfg,password)
                try:
                    smtp.noop()
                finally:
                    smtp.close()
                self.events.put(('status','SMTP连接与认证成功；未发送邮件。'))
            self.start(work)
        except Exception as exc:
            self.error(exc)

    def test_mail(self):
        try:
            if not self.require_credential(self.test_mail):
                return
            cfg=self.config()
            email=normalize(cfg['test_to'])
            if not valid_email(email):
                raise ValueError('请填写用于接收测试邮件的邮箱。')
            c=Customer(0,'TEST COMPANY',email)
            msg=self.render(c,'[TEST] '+cfg['subject'],cfg)
            if messagebox.askyesno('发送测试邮件',f'仅发送一封测试邮件至：\n{email}\n\n确认发送？'):
                password=self.v['password'].get()
                self.start(lambda:self.deliver(cfg,password,[(c,msg)],test=True))
        except Exception as exc:
            self.error(exc)

    def export(self):
        directory=filedialog.askdirectory(title='选择结果保存文件夹')
        if not directory:
            return
        try:
            from datetime import datetime
            tag=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            path=Path(directory)
            export_csv(path/f'发送记录_{tag}.csv',['开始时间_北京时间','邮箱','公司名','主题','状态','说明','Message-ID'],self.ledger.rows())
            export_csv(path/f'客户预览_{tag}.csv',['原表行号','公司名','邮箱','状态'],[(c.row,c.company,c.email,STATUSES[c.status]) for c in self.customers])
            self.status.set('已导出发送记录与最近一次客户预览。原Excel未修改。')
        except Exception as exc:
            self.error(exc)

    def open_local(self, name):
        path=str(BASE/name)
        if sys.platform=='win32':
            os.startfile(path)
        elif sys.platform=='darwin':
            subprocess.Popen(['open',path])
        else:
            subprocess.Popen(['xdg-open',path])

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='done':
                    self.busy=False
                    self.stamp=None
                    for b in self.actions:
                        b.config(state='normal')
                elif kind=='error':
                    self.status.set(value)
                    messagebox.showerror('操作暂停',value)
                elif kind=='archive_status':
                    self.v['archive_status'].set(value)
                else:
                    self.status.set(value)
        except queue.Empty:
            pass
        self._poll_job=self.root.after(150,self.poll)

    def error(self,exc):
        messagebox.showerror('请检查',str(exc))

    def close(self):
        if self.busy:
            self.stop_event.set()
            messagebox.showinfo('正在暂停','已请求暂停。请等待当前SMTP操作结束后再关闭。')
            return
        self.v['password'].set('')
        self.root.after_cancel(self._poll_job)
        self.root.destroy()

if __name__=='__main__':
    from main import main
    main()

