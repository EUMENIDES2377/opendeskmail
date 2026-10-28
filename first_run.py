"""Local setup wizard; never asks for passwords in chat or writes secrets."""
import json,mimetypes
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from core import BASE,valid_email,normalize
from app_paths import USER_HOME as BASE
from html_signature import load_signature

def import_signature(path):
    sig=load_signature(path);folder=BASE/'signature'/sig.fingerprint[:20];images=folder/'images';images.mkdir(parents=True,exist_ok=True)
    markup=sig.markup
    for asset in sig.images:
        filename=asset.cid.split('@')[0]+(mimetypes.guess_extension(asset.media_type) or '.bin')
        (images/filename).write_bytes(asset.data);markup=markup.replace('cid:'+asset.cid,'images/'+filename)
    target=folder/'signature.html';target.write_text('<meta charset="utf-8">'+markup,encoding='utf-8');load_signature(target)
    return str(target.relative_to(BASE))

def ensure_configured(root,defaults):
    path=BASE/'settings.json'
    if path.exists():
        try:
            old=json.loads(path.read_text('utf-8'))
            if old.get('market') and old.get('sender') and old.get('host'):return True
        except (OSError,ValueError):pass
    top=tk.Toplevel(root);top.title('OpenDesk Mail · 首次本地配置');top.geometry(f'780x{min(760,top.winfo_screenheight()-80)}');top.minsize(680,620)
    if root.winfo_viewable():top.transient(root)
    frame=ttk.Frame(top,padding=18);frame.pack(fill='both',expand=True);values={};done=[False]
    ttk.Label(frame,text='请填写您自己的资料；此处不连接邮箱、不发送邮件。',font=('Microsoft YaHei UI',12,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=8)
    fields=[('market','市场名称',''),('sender','发件邮箱',''),('sender_name','发件人显示名称',''),('host','SMTP服务器（向管理员确认）',''),('port','SMTP端口（向管理员确认）',''),('username','登录用户名（空则使用邮箱）',''),('subject','开发信主题',''),('signature_html','自己的HTML签名（可留空）','')]
    for row,(key,label,value) in enumerate(fields,1):
        values[key]=tk.StringVar(value=value);ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',padx=4,pady=5);ttk.Entry(frame,textvariable=values[key],width=48).grid(row=row,column=1,sticky='ew',padx=4,pady=5)
    def choose():
        selected=filedialog.askopenfilename(parent=top,filetypes=[('HTML签名','*.htm *.html')])
        if selected:values['signature_html'].set(selected)
    ttk.Button(frame,text='选择签名及所需图片',command=choose).grid(row=9,column=1,sticky='w')
    values['security']=tk.StringVar(value='SSL/TLS');ttk.Label(frame,text='SMTP加密方式').grid(row=10,column=0,sticky='w');ttk.Combobox(frame,textvariable=values['security'],values=['SSL/TLS','STARTTLS'],state='readonly').grid(row=10,column=1,sticky='ew',pady=5)
    ttk.Label(frame,text='正文（用 {{company}} 自动替换公司名称）').grid(row=11,column=0,columnspan=2,sticky='w',pady=5)
    body=tk.Text(frame,height=8,wrap='word',font=('Microsoft YaHei UI',10));body.grid(row=12,column=0,columnspan=2,sticky='nsew')
    ttk.Label(frame,text='密码在主界面的本地掩码框中填写，可选Windows凭据管理器。\n签名只复制所需图片，不复制邮件或通讯录；原签名保持不变。',wraplength=680).grid(row=13,column=0,columnspan=2,sticky='w',pady=8)
    def save():
        try:
            cfg=defaults.copy();cfg.update({k:v.get().strip() for k,v in values.items()});cfg.pop('password',None)
            if not cfg['market'] or not valid_email(normalize(cfg['sender'])) or not cfg['host'] or not cfg['subject'] or not body.get('1.0','end-1c').strip():raise ValueError('请填写市场、有效发件邮箱、SMTP服务器、主题和正文。')
            if not 1<=int(cfg['port'])<=65535:raise ValueError('端口须在1至65535之间。')
            cfg['sender']=normalize(cfg['sender']);cfg['test_to']=cfg['sender']
            if cfg['signature_html']:cfg['signature_html']=import_signature(cfg['signature_html'])
            path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8');(BASE/'email_body.txt').write_text(body.get('1.0','end-1c'),encoding='utf-8');done[0]=True;top.destroy()
        except Exception as exc:messagebox.showerror('请检查配置',str(exc),parent=top)
    ttk.Button(frame,text='保存自己的配置并进入程序（不发送）',command=save).grid(row=14,column=0,columnspan=2,pady=8)
    frame.columnconfigure(1,weight=1);frame.rowconfigure(12,weight=1);top.deiconify();top.grab_set();top.lift();top.focus_force();root.wait_window(top);return done[0]

