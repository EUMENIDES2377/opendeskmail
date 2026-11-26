"""Windows desktop UI: explicit local configuration, previews and live controls."""
import json,queue,threading,webbrowser,os
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from email.utils import getaddresses
from core import BASE,Customer,Ledger,now,sheet_names,export_csv,smtp_connect
from html_signature import preview_document
from v2_model import HOME,DEFAULT,STATES,load_config,save_config,validate_account,SecureStore,templates,save_template,import_html,paste_html,import_customers,build_message,customer_fields,language,public_config,decode_html,protect_source,ProjectProfiles
from v2_engine import Controller,Results,explain
from v2_delivery import submit,atomic_json
from account_guard import AccountLease

class Application:
    def __init__(self,root,home=HOME,controller=None,enable_projects=False):
        self.root = root
        self.projects = ProjectProfiles(home) if enable_projects else None
        self.controller = None
        try:
            self.project = self.projects.active if self.projects else ProjectProfiles.default
            self.home = self.projects.home(self.project) if self.projects else Path(home)
            self.cfg = self.projects.config(self.project) if self.projects else load_config(self.home)
            self.controller = controller or self.open_controller(self.project)
            self.build_window()
        except Exception:
            if self.controller:
                self.controller.close()
            if self.projects:
                self.projects.close()
            raise

    def open_controller(self, project):
        if not self.projects:
            return Controller(self.home)
        return Controller(self.projects.home(project), ledger_path=self.projects.ledger, project=project)

    def build_window(self):
        root = self.root
        self.password = ''
        self.aux_busy = False
        self.aux_queue = queue.Queue()
        self.preview_cfg = None
        self.preview_window = None
        root.title('OpenDesk Mail · 开源桌面邮件工具');root.geometry(f'{min(1220,root.winfo_screenwidth()-60)}x{min(880,root.winfo_screenheight()-80)}');root.minsize(900,650)
        import tkinter.font as font
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont'):font.nametofont(name).configure(family='Microsoft YaHei UI',size=10)
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=10,pady=8)
        self.send_page=ttk.Frame(self.tabs,padding=10);self.template_page=ttk.Frame(self.tabs,padding=10);self.signature_page=ttk.Frame(self.tabs,padding=10);self.help_page=ttk.Frame(self.tabs,padding=10)
        for frame,title in [(self.send_page,'客户与实时发送'),(self.template_page,'本地开发信模板'),(self.signature_page,'签名与最终预览'),(self.help_page,'帮助与本地配置')]:self.tabs.add(frame,text=title)
        self.build_send();self.build_templates();self.build_signature();self.build_help();self.load_project_widgets()
        root.protocol('WM_DELETE_WINDOW',self.close);self.poll()
        if not self.cfg.get('host') or not self.cfg.get('sender'):root.after(250,self.account_dialog)
    def save_project_widgets(self):
        cfg = dict(self.cfg, **{key: value.get().strip() for key, value in self.mapping.items()})
        save_config(cfg, self.home)
        self.controller.save()
        selection = self.tree.selection()
        atomic_json(self.home / 'drafts/editor.json', {
            'template_choice': self.template_choice.get(),
            'template_fields': {key: value.get() for key, value in self.tv.items()},
            'template_format': self.format.get(),
            'template_body': self.body.get('1.0', 'end-1c'),
            'edit_id': self.edit_id,
            'template_html': self.template_html,
            'resource_dir': self.resource_dir,
            'attachments': self.attachments,
            'signature_format': self.sig_format.get(),
            'signature_body': self.sig.get('1.0', 'end-1c'),
            'signature_resource': self.sig_resource.get(),
            'selected_row': selection[0] if selection else None,
        })

    def load_project_widgets(self):
        for key, value in self.mapping.items():
            value.set(self.cfg[key])
        self.sheet_box['values'] = sheet_names(self.cfg['file']) if self.cfg.get('file') and Path(self.cfg['file']).is_file() else ()
        self.new_template()
        self.refresh_templates()
        signature = self.cfg.get('signature_html')
        self.sig_format.set('html' if signature else 'text')
        self.sig_resource.set(str(Path(signature).parent) if signature else '')
        self.sig.delete('1.0', 'end')
        self.sig.insert('1.0', decode_html(signature) if signature and Path(signature).is_file() else self.cfg.get('signature_text', ''))
        self.sig_info.set(signature or '未配置HTML签名，可粘贴自己的HTML/文字。')
        self.variables_text.set('生成预览后可查看当前客户表字段。语言标签 ru 表示俄语。')
        draft_path = self.home / 'drafts/editor.json'
        draft = json.loads(draft_path.read_text('utf-8')) if draft_path.exists() else {}
        if draft:
            self.template_choice.set(draft['template_choice'])
            for key, value in self.tv.items():
                value.set(draft['template_fields'][key])
            self.format.set(draft['template_format'])
            self.body.delete('1.0', 'end')
            self.body.insert('1.0', draft['template_body'])
            self.edit_id = draft['edit_id']
            self.template_html = draft['template_html']
            self.resource_dir = draft['resource_dir']
            self.attachments = draft['attachments']
            self.sig_format.set(draft['signature_format'])
            self.sig_resource.set(draft['signature_resource'])
            self.sig.delete('1.0', 'end')
            self.sig.insert('1.0', draft['signature_body'])
        self.body.edit_reset()
        self.sig.edit_reset()
        self.tree.selection_remove(*self.tree.selection())
        self.show_rows()
        selected = draft.get('selected_row')
        if selected is None and self.controller.job:
            selected = next((str(i) for i, row in enumerate(self.controller.job['rows'])
                             if row['state'] == 'ready'), None)
        if selected is not None and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        log_path = self.home / 'logs/events.log'
        while True:
            try:
                self.controller.events.get_nowait()
            except queue.Empty:
                break
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        if log_path.exists():
            from collections import deque
            with log_path.open(encoding='utf-8') as log:
                self.log.insert('end', ''.join(deque(log, maxlen=250)))
        self.log.see('end')
        self.log.configure(state='disabled')

    def create_project(self):
        self.guard_edit()
        name = simpledialog.askstring('新建发送项目', '项目名称', parent=self.root)
        if name is None:
            return
        project = self.projects.create(name)
        self.project_box['values'] = list(self.projects.names.values())
        self.project_choice.set(self.projects.names[project])
        self.select_project()

    def select_project(self, _event=None):
        project = next(key for key, name in self.projects.names.items() if name == self.project_choice.get())
        if project == self.project:
            return
        try:
            self.guard_edit()
            self.save_project_widgets()
            cfg = self.projects.config(project)
            controller = self.open_controller(project)
            try:
                self.projects.select(project)
                self.controller.close()
            except Exception:
                controller.close()
                raise
            if self.preview_window is not None and self.preview_window.winfo_exists():
                self.preview_window.destroy()
            self.project = project
            self.home = self.projects.home(project)
            self.controller = controller
            self.cfg = cfg
            self.preview_cfg = None
            self.load_project_widgets()
        except Exception as exc:
            self.project_choice.set(self.projects.names[self.project])
            self.error(exc)

    def error(self,exc):messagebox.showerror('操作未执行或已暂停',explain(exc),parent=self.root)
    def guard_edit(self):
        if self.controller.busy or self.aux_busy:raise ValueError('请先安全停止当前任务，再修改配置或预览。')
    def button(self,parent,text,command):
        def guarded():
            try:command()
            except Exception as exc:self.error(exc)
        b=ttk.Button(parent,text=text,command=guarded);b.pack(side='left',padx=3,pady=3);return b
    def build_send(self):
        p = self.send_page
        if self.projects:
            selector = ttk.Frame(p)
            selector.pack(fill='x')
            self.sender_label = tk.StringVar(value=self.cfg['sender'])
            ttk.Label(selector, text='当前账号').pack(side='left', padx=(0, 6))
            ttk.Label(selector, textvariable=self.sender_label).pack(side='left', padx=(0, 20))
            ttk.Label(selector, text='发送项目').pack(side='left', padx=(0, 6))
            self.project_choice = tk.StringVar(value=self.projects.names[self.project])
            self.project_box = ttk.Combobox(selector, textvariable=self.project_choice,
                                           values=list(self.projects.names.values()), state='readonly', width=51)
            self.project_box.pack(side='left')
            self.project_box.bind('<<ComboboxSelected>>', self.select_project)
            self.new_project_button = self.button(selector, '新建项目', self.create_project)
        bar=ttk.Frame(p);bar.pack(fill='x');self.button(bar,'配置/修改账号',self.account_dialog);self.button(bar,'导入客户表',self.import_file);self.button(bar,'生成预览',self.prepare);self.button(bar,'预览选中客户',self.preview_selected)
        self.context=tk.StringVar();ttk.Label(p,textvariable=self.context,wraplength=1100).pack(fill='x',pady=5)
        self.mapping={};maps=ttk.Frame(p);maps.pack(fill='x')
        for key,label,width in [('sheet','工作表',18),('company_col','公司列',11),('email_col','邮箱列',11),('note_col','备注列',10),('language_col','语言列(可空)',10)]:
            ttk.Label(maps,text=label).pack(side='left');v=tk.StringVar(value=self.cfg.get(key,''));self.mapping[key]=v
            widget=ttk.Combobox(maps,textvariable=v,width=width) if key=='sheet' else ttk.Entry(maps,textvariable=v,width=width);widget.pack(side='left',padx=3)
            if key=='sheet':self.sheet_box=widget
        run=ttk.Frame(p);run.pack(fill='x',pady=5)
        for title,cmd in [('开始本批',self.start),('暂停',lambda:self.controller.pause()),('继续',self.resume),('安全停止',lambda:self.controller.stop()),('修复Excel副本',lambda:self.controller.repair()),('核查副本',self.check_copies),('导出日志',self.export)]:self.button(run,title,cmd)
        self.summary=tk.StringVar();self.detail=tk.StringVar();ttk.Label(p,textvariable=self.summary,font=('Microsoft YaHei UI',13,'bold'),wraplength=1100).pack(fill='x',pady=5);ttk.Label(p,textvariable=self.detail,wraplength=1100).pack(fill='x')
        treeframe=ttk.Frame(p);treeframe.pack(fill='both',expand=True,pady=6);self.tree=ttk.Treeview(treeframe,columns=('row','company','email','state','reason'),show='headings',height=8)
        for key,title,width in [('row','原表行',60),('company','公司名称',230),('email','邮箱',240),('state','状态',130),('reason','说明',360)]:self.tree.heading(key,text=title);self.tree.column(key,width=width,stretch=key!='row')
        sy=ttk.Scrollbar(treeframe,orient='vertical',command=self.tree.yview);sx=ttk.Scrollbar(treeframe,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);sy.pack(side='right',fill='y');sx.pack(side='bottom',fill='x');self.tree.pack(fill='both',expand=True)
        self.log=tk.Text(p,height=6,wrap='word',state='disabled');self.log.pack(fill='both',pady=4)
        ttk.Label(p,text='成功仅表示SMTP服务器已接受，未确认客户收件。首次/重启均不会自动开始；暂停和停止会等待当前提交落盘。',wraplength=1100).pack(fill='x')
    def build_templates(self):
        p=self.template_page;line=ttk.Frame(p);line.pack(fill='x');self.template_choice=tk.StringVar();self.template_box=ttk.Combobox(line,textvariable=self.template_choice,state='readonly',width=45);self.template_box.pack(side='left');self.template_box.bind('<<ComboboxSelected>>',lambda e:self.select_template())
        self.button(line,'新建',self.new_template);self.button(line,'导入TXT/HTML',self.import_template);self.button(line,'保存模板',self.save_template_ui)
        fields=ttk.Frame(p);fields.pack(fill='x',pady=6);self.tv={}
        for key,label,default,width in [('name','模板名称','',24),('language','语言标签','en',12),('subject','邮件主题','',48)]:
            ttk.Label(fields,text=label).pack(side='left');v=tk.StringVar(value=default);self.tv[key]=v;ttk.Entry(fields,textvariable=v,width=width).pack(side='left',padx=4)
        self.format=tk.StringVar(value='text');ttk.Combobox(p,textvariable=self.format,values=['text','html'],state='readonly',width=12).pack(anchor='w')
        self.body=tk.Text(p,wrap='word',height=15,undo=True);self.body.pack(fill='both',expand=True,pady=5)
        line=ttk.Frame(p);line.pack(fill='x');self.button(line,'添加附件',self.add_attachment);self.button(line,'清空附件',lambda:self.attachments.clear());self.attachment_label=tk.StringVar();ttk.Label(p,textvariable=self.attachment_label,wraplength=1100).pack(fill='x')
        self.variables_text=tk.StringVar(value='变量：{{company}}、{{email}}、{{note}}、{{sender}}；导入并预览后列出实际表头变量。缺失值、未知变量和未替换占位符会阻止发送。语言标签en/es/pt分别表示英/西/葡；不联网翻译。')
        ttk.Label(p,textvariable=self.variables_text,wraplength=1100).pack(fill='x',pady=6)
        self.edit_id='';self.attachments=[];self.template_html='';self.resource_dir=''
    def build_signature(self):
        p=self.signature_page;line=ttk.Frame(p);line.pack(fill='x');self.button(line,'导入自己的Foxmail HTML签名',self.import_signature);self.button(line,'保存粘贴签名',self.save_signature);self.button(line,'选中客户最终预览',self.preview_selected)
        self.sig_format=tk.StringVar(value='html');ttk.Combobox(p,textvariable=self.sig_format,values=['html','text'],state='readonly',width=12).pack(anchor='w',pady=5)
        self.sig=tk.Text(p,wrap='word',height=18,undo=True);self.sig.pack(fill='both',expand=True)
        self.sig_resource=tk.StringVar();row=ttk.Frame(p);row.pack(fill='x');ttk.Label(row,text='粘贴HTML时图片相对路径基准目录：').pack(side='left');ttk.Entry(row,textvariable=self.sig_resource,width=55).pack(side='left');self.button(row,'选择目录',lambda:self.sig_resource.set(filedialog.askdirectory() or self.sig_resource.get()))
        self.sig_info=tk.StringVar(value=self.cfg.get('signature_html') or '未配置HTML签名，可粘贴自己的HTML/文字。');ttk.Label(p,textvariable=self.sig_info,wraplength=1100).pack(fill='x',pady=5)
        ttk.Label(p,text='正文与签名分别保存，每封只追加一次已配置签名。模板自带签名时请先移除重复部分。图片以CID内嵌，最终显示需本人授权测试邮件后核对；不同客户端不能保证像素级一致。',wraplength=1100).pack(fill='x')
    def build_help(self):
        p=self.help_page;ttk.Label(p,text='本软件运行不调用Codex、ChatGPT、豆包或其他在线AI。配置/安装不等于授权群发。',wraplength=1000).pack(anchor='w',pady=10)
        for name in ['使用说明.md','邮箱配置说明.md','给其他AI的配置提示词.md','签名导入说明.md','故障排查.md','功能对照.md']:
            ttk.Button(p,text=name,command=lambda n=name:os.startfile(str(BASE/n))).pack(anchor='w',pady=5)
        ttk.Label(p,text='用户数据目录：'+str(self.home)+'\n凭据：Windows凭据管理器；不可用时只保留内存。\n账号、客户、签名与日志不保存在源码目录。可按用户授权使用AI安全配置入口。',wraplength=1000).pack(anchor='w',pady=12)
        for name in ('已发邮箱.txt','已回复邮箱.txt','不再联系.txt'):
            def edit(n=name):
                path=self.home/'config'/n;path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():path.write_text('','utf-8')
                os.startfile(str(path))
            ttk.Button(p,text='编辑'+name,command=edit).pack(anchor='w',pady=3)
    def account_dialog(self):
        self.guard_edit();top=tk.Toplevel(self.root);top.title('首次配置/修改自己的邮箱账号');top.geometry('780x710');top.transient(self.root)
        canvas=tk.Canvas(top,highlightthickness=0);scroll=ttk.Scrollbar(top,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True);f=ttk.Frame(canvas,padding=15);item=canvas.create_window(0,0,window=f,anchor='nw');f.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        values={};fields=[('market','市场/项目'),('sender_name','发件人显示名称'),('sender','邮箱地址'),('host','SMTP服务器'),('port','SMTP端口'),('security','SMTP加密方式'),('username','登录用户名(空=邮箱)'),('interval','间隔秒数(至少60)'),('batch','每批数量'),('cap','每日尝试上限(0=不限)'),('imap_host','IMAP服务器(可空)'),('imap_port','IMAP SSL/TLS端口'),('imap_sent_folder','实际Sent文件夹服务器名称')]
        if self.projects:
            fields = [(key, label) for key, label in fields if key != 'market']
        for i,(key,label) in enumerate(fields):
            ttk.Label(f,text=label).grid(row=i,column=0,sticky='w',pady=4);values[key]=tk.StringVar(value=str(self.cfg.get(key,'')));widget=ttk.Combobox(f,textvariable=values[key],values=['SSL/TLS','STARTTLS'],state='readonly') if key=='security' else ttk.Entry(f,textvariable=values[key],width=45);widget.grid(row=i,column=1,sticky='ew',pady=4)
        secret=tk.StringVar(value=self.password);remember=tk.BooleanVar(value=False);message=tk.StringVar(value='SMTP发送、IMAP读取副本。Foxmail只是客户端，服务器须按实际服务商核实。')
        ttk.Label(f,text='密码/授权码(掩码显示)').grid(row=13,column=0,sticky='w');ttk.Entry(f,textvariable=secret,show='*').grid(row=13,column=1,sticky='ew');ttk.Checkbutton(f,text='保存到Windows凭据管理器',variable=remember).grid(row=14,column=1,sticky='w')
        values['credential_kind']=tk.StringVar(value=self.cfg.get('credential_kind','password'))
        ttk.Label(f,text='凭据类型：password=登录密码；smtp_authorization_code=SMTP授权码',wraplength=650).grid(row=19,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Combobox(f,textvariable=values['credential_kind'],values=['password','smtp_authorization_code'],state='readonly').grid(row=20,column=1,sticky='ew')
        def config():
            cfg=dict(self.cfg,**{k:v.get().strip() for k,v in values.items()});return validate_account(cfg)
        def get_password(cfg):
            try:return secret.get() or SecureStore().read(cfg) or ''
            except Exception:return secret.get()
        def save():
            try:
                cfg=config();self.password=get_password(cfg)
                if remember.get() and self.password:
                    try:SecureStore().write(cfg,self.password)
                    except Exception:messagebox.showwarning('仅当次内存保存','Windows凭据管理器不可用；没有写入明文文件。',parent=top)
                if self.projects:
                    self.projects.save_account(cfg)
                save_config(cfg,self.home);self.cfg=cfg;secret.set('');top.destroy()
            except Exception as exc:message.set(explain(exc))
        def test():
            try:
                cfg=config();pwd=get_password(cfg)
                if not pwd:raise ValueError('请在本地掩码框输入密码或授权码。')
                self.run_aux(lambda:self.test_account(cfg,pwd),message)
            except Exception as exc:message.set(explain(exc))
        def delete():
            try:SecureStore().delete(config());secret.set('');self.password='';message.set('当前账号已保存凭据已删除。')
            except Exception as exc:message.set(explain(exc))
        buttons=ttk.Frame(f);buttons.grid(row=15,column=0,columnspan=2,sticky='w',pady=8);self.button(buttons,'测试连接和认证(不发信)',test);self.button(buttons,'保存配置',save);self.button(buttons,'删除凭据',delete)
        target=tk.StringVar();ttk.Label(f,text='明确选择测试发信时填写收件人：').grid(row=16,column=0,sticky='w');ttk.Entry(f,textvariable=target).grid(row=16,column=1,sticky='ew')
        def send_test():
            try:
                cfg=config();pwd=get_password(cfg)
                from core import valid_email
                if not valid_email(target.get().strip()):raise ValueError('请手动填写测试收件邮箱。')
                if self.template_choice.get() not in self.template_ids:raise ValueError('请先保存本地模板，再发送测试邮件。')
                template=templates(self.home)[self.template_ids[self.template_choice.get()]];c=Customer(0,'EXAMPLE TEST COMPANY',target.get().strip());msg=build_message(c,{},cfg,dict(template,subject='[TEST] '+template['subject']))
                if not messagebox.askyesno('确认仅一封测试邮件','仅发送至：'+target.get()+'\n不向客户发送，是否确认？',parent=top):return
                self.run_aux(lambda:self.single_test(cfg,pwd,c,msg),message)
            except Exception as exc:message.set(explain(exc))
        ttk.Button(f,text='明确发送一封测试邮件',command=send_test).grid(row=17,column=1,sticky='w',pady=8);ttk.Label(f,textvariable=message,wraplength=680).grid(row=18,column=0,columnspan=2,sticky='w',pady=8);f.columnconfigure(1,weight=1)
        def changed(*args):secret.set('');remember.set(False)
        for key in ('sender','host','port','security','username'):values[key].trace_add('write',changed)
        def cancel():
            if self.aux_busy:message.set('连接测试仍在进行，请等待完成再关闭。');return
            secret.set('');top.destroy()
        # Bind only this dialog's controls, never global wheel events in other tasks.
        def wheel(event):
            canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
        def bind_wheel(widget):
            widget.bind('<MouseWheel>',wheel)
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(top)
        top.protocol('WM_DELETE_WINDOW',cancel);top.grab_set();top.lift()
    def run_aux(self,fn,message=None):
        if self.controller.busy or self.aux_busy:raise ValueError('已有操作进行中，请等待。')
        self.aux_busy=True
        def work():
            try:text=fn()
            except Exception as exc:text=explain(exc)
            self.aux_queue.put((message,text))
        threading.Thread(target=work,daemon=False).start()
    def test_account(self,cfg,password):
        with self.controller.lease_factory(cfg['sender']):
            smtp=smtp_connect(cfg,password)
            try:smtp.noop()
            finally:smtp.close()
        return 'SMTP连接、TLS证书及认证成功；未发送邮件。'
    def single_test(self,cfg,password,c,msg):
        if not password:raise ValueError('缺少本地输入的凭据。')
        cfg=dict(cfg,storage=str(self.home))
        with self.controller.lease_factory(cfg['sender']) as lease:
            stop=threading.Event();lease.wait(stop);lease.reserve(cfg['interval']);smtp=None
            try:smtp=smtp_connect(cfg,password);r=submit(smtp,self.controller.ledger,c,msg,cfg,test=True,password=password)
            finally:
                lease.finished(cfg['interval'])
                if smtp:smtp.close()
        return '单封测试结果：'+STATES.get(r['state'],r['state'])+'；实收和显示效果仍需本人核对。'
    def import_file(self):
        self.guard_edit();path=filedialog.askopenfilename(filetypes=[('客户表','*.xlsx *.csv')])
        if not path:return
        self.cfg=import_customers(path,self.cfg,self.home);names=sheet_names(self.cfg['file']);self.sheet_box['values']=names;self.mapping['sheet'].set(names[0]);self.preview_cfg=None;save_config(self.cfg,self.home)
        self.controller.log('已导入快照，未修改原表。请选择表头映射后生成预览。')
    def collect_cfg(self):
        ident=self.template_ids.get(self.template_choice.get(),'');saved=templates(self.home).get(ident)
        if saved:
            expected=decode_html(saved['html_path']) if saved.get('format')=='html' else saved.get('body','')
            if self.body.get('1.0','end-1c')!=expected or self.tv['subject'].get().strip()!=saved['subject'] or self.attachments!=saved.get('attachments',[]) or self.format.get()!=saved.get('format','text') or language(self.tv['language'].get())!=saved['language']:raise ValueError('模板编辑尚未保存，请先保存模板并重新生成预览。')
        cfg=dict(self.cfg,**{k:v.get().strip() for k,v in self.mapping.items()});cfg['template_id']=ident;cfg['storage']=str(self.home);return validate_account(cfg)
    def prepare(self):
        self.guard_edit();cfg=self.collect_cfg()
        if not cfg.get('file'):raise ValueError('请先导入自己的客户表。')
        self.controller.prepare(cfg);self.cfg=cfg;self.preview_cfg=public_config(cfg);save_config(cfg,self.home);self.show_rows()
        fields=customer_fields(cfg);names=set().union(*(item.keys() for item in fields.values())) if fields else set();names|={'company','email','note','sender'};self.variables_text.set('允许变量：'+', '.join('{{'+name+'}}' for name in sorted(names))+'。缺失、重复表头所对应的变量或未知变量不能发送；不执行模板代码，不联网翻译。')
    def show_rows(self):
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(self.controller.job['rows'] if self.controller.job else []):self.tree.insert('','end',iid=str(i),values=(row['row'],row['company'],row['email'],STATES.get(row['state'],row['state']),row.get('reason','')))
        for item in selection:
            if self.tree.exists(item):
                self.tree.selection_add(item)

    def preview_selected(self):
        if not self.controller.job:raise ValueError('请先生成预览。')
        if self.projects:
            self.controller.check()
            if public_config(self.collect_cfg()) != self.controller.job['cfg']:
                raise ValueError('项目客户表、模板或签名已变化，请重新生成预览。')
        selection=self.tree.selection()
        if not selection:raise ValueError('请选中一位客户。')
        row = self.controller.job['rows'][int(selection[0])]
        self.show_message_preview(self.controller.message(row), 'final.html')

    def show_message_preview(self, msg, filename):
        path = self.home / 'preview' / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(preview_document(msg), 'utf-8')
        webbrowser.open(path.as_uri())
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.destroy()
        top=tk.Toplevel(self.root);self.preview_window=top;top.title('最终邮件预览（不发送）');text=tk.Text(top,width=90,height=23,wrap='word');text.pack(fill='both',expand=True);plain=msg.get_body(preferencelist=('plain',)).get_content();text.insert('1.0',f"发件人：{msg['From']}\n收件人：{msg['To']}\n主题：{msg['Subject']}\n附件：{', '.join(p.get_filename() or '' for p in msg.iter_attachments())}\n\n{plain}");text.configure(state='disabled')
    def password_for(self,cfg):
        if self.password:return self.password
        try:self.password=SecureStore().read(cfg) or ''
        except Exception:pass
        if not self.password:raise ValueError('请打开账号配置，在本地掩码框输入自己的密码/授权码并保存。')
        return self.password
    def start(self):
        self.guard_edit();cfg=self.collect_cfg()
        if not self.controller.job or public_config(cfg)!=self.controller.job['cfg']:raise ValueError('配置已变化或尚未预览，请重新生成预览。')
        ready=sum(r['state']=='ready' for r in self.controller.job['rows']);number=min(ready,cfg['batch'])
        if not number:raise ValueError('没有可发送客户。')
        if not messagebox.askyesno('确认发送本批',f"账号：{cfg['sender']}\n本批最多{number}封，间隔{cfg['interval']}秒，每日上限{cfg['cap']}。\n已失败/未知的邮件不会重发。是否确认？",parent=self.root):return
        self.controller.start(self.password_for(cfg))
    def resume(self):
        if self.controller.busy:self.controller.resume()
        else:self.start()
    def check_copies(self):
        self.guard_edit()
        if not self.controller.job:raise ValueError('没有任务记录。')
        cfg=self.controller.job['cfg'];results=[r['result'] for r in self.controller.job['rows'] if r.get('result')]
        def work():
            note=self.controller.copy_checker(cfg,self.password_for(cfg),results);self.controller.repair();return note+'；未知状态不会仅因缺少副本自动重试。'
        pwd=self.password_for(cfg)
        self.run_aux(lambda:(self.controller.copy_checker(cfg,pwd,results),self.controller.repair(),'只读副本核查完成，未发信；请查看工作副本。')[-1])
    def new_template(self):
        self.guard_edit();self.edit_id='';self.template_html='';self.attachments=[];self.tv['name'].set('');self.tv['subject'].set('');self.tv['language'].set('en');self.format.set('text');self.resource_dir='';self.body.delete('1.0','end')
    def refresh_templates(self):
        self.template_ids={v['name']+' ['+v['language']+']':k for k,v in templates(self.home).items()};self.template_box['values']=list(self.template_ids)
        selected=next((name for name,key in self.template_ids.items() if key==self.cfg.get('template_id')),next(iter(self.template_ids),''));self.template_choice.set(selected)
        if selected:self.select_template()
    def select_template(self):
        if self.controller.busy:return
        item=templates(self.home)[self.template_ids[self.template_choice.get()]];self.edit_id=item['id'];self.tv['name'].set(item['name']);self.tv['subject'].set(item['subject']);self.tv['language'].set(item['language']);self.format.set(item.get('format','text'));self.template_html=item.get('html_path','');self.resource_dir=str(Path(self.template_html).parent) if self.template_html else '';self.attachments=list(item.get('attachments',[]));self.body.delete('1.0','end');self.body.insert('1.0',decode_html(self.template_html) if self.template_html else item.get('body',''))
    def import_template(self):
        self.guard_edit();path=filedialog.askopenfilename(filetypes=[('本地模板','*.txt *.htm *.html')])
        if not path:return
        self.resource_dir=str(Path(path).parent);self.format.set('html' if Path(path).suffix.lower() in ('.html','.htm') else 'text');content=decode_html(path);self.body.delete('1.0','end');self.body.insert('1.0',content);self.tv['name'].set(Path(path).stem)
        messagebox.showinfo('请检查模板签名','如果模板正文已经包含签名，请移除其中的重复签名，或清空单独签名设置。本软件不会擅自删除正文内容。',parent=self.root)
    def add_attachment(self):
        self.guard_edit();self.attachments.extend(filedialog.askopenfilenames(title='选择本地附件'))
    def save_template_ui(self):
        self.guard_edit();item={k:v.get().strip() for k,v in self.tv.items()};item.update(id=self.edit_id,format=self.format.get(),body=self.body.get('1.0','end-1c'),attachments=list(dict.fromkeys(self.attachments)))
        if not item['name'] or not item['subject'] or not item['body'].strip():raise ValueError('请填写模板名称、主题和正文。')
        if item['format']=='html':item['html_path']=paste_html(item['body'],self.resource_dir,self.home,'template')
        ident=save_template(item,self.home);self.cfg['template_id']=ident;save_config(self.cfg,self.home);self.refresh_templates();self.controller.log('本地模板已保存，未生成或发送在线AI内容。')
    def import_signature(self):
        self.guard_edit();path=filedialog.askopenfilename(filetypes=[('Foxmail HTML签名','*.htm *.html')])
        if path:self.cfg['signature_html']=import_html(path,self.home);self.cfg['signature_text']='';save_config(self.cfg,self.home);self.sig_info.set(self.cfg['signature_html']);self.controller.log('签名及其引用图片已导入；原文件不变。')
    def save_signature(self):
        self.guard_edit();content=self.sig.get('1.0','end-1c')
        if self.sig_format.get()=='html' and content.strip():self.cfg['signature_html']=paste_html(content,self.sig_resource.get(),self.home);self.cfg['signature_text']=''
        else:self.cfg['signature_html']='';self.cfg['signature_text']=content
        save_config(self.cfg,self.home);self.sig_info.set(self.cfg['signature_html'] or '已保存文字签名（可为空）')
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV日志','*.csv')])
        if path:export_csv(protect_source(path),['开始时间','邮箱','公司','主题','状态','详情','Message-ID'],self.controller.ledger.rows())
    def poll(self):
        if self.projects:
            self.sender_label.set(self.cfg['sender'])
            busy = self.controller.busy or self.aux_busy
            self.project_box.configure(state='disabled' if busy else 'readonly')
            self.new_project_button.configure(state='disabled' if busy else 'normal')
        for page in (self.template_page,self.signature_page):self.tabs.tab(page,state='disabled' if self.controller.busy else 'normal')
        try:
            while True:
                line=self.controller.events.get_nowait();self.log.configure(state='normal');self.log.insert('end',line+'\n');self.log.see('end');self.log.configure(state='disabled')
                self.show_rows()
        except queue.Empty:pass
        try:
            while True:
                target,text=self.aux_queue.get_nowait();self.aux_busy=False
                if target is not None:target.set(text)
                self.controller.log(text)
        except queue.Empty:pass
        snap=self.controller.snapshot(self.cfg.get('sender') if not self.controller.job else None);c=snap['counts'];cfg=self.controller.job['cfg'] if self.controller.job else self.cfg
        self.context.set(f"当前账号：{cfg.get('sender','未配置')}　项目：{cfg.get('market','未配置')}\n客户快照：{cfg.get('file','未导入')}\n模板：{self.template_choice.get() or '未选择'}　工作副本：{self.controller.job.get('output','') if self.controller.job else ''}")
        self.summary.set(f"总数 {snap['total']}　待发送 {c['ready']}　成功(服务器接受) {c['accepted']}　失败 {c['failed']}　跳过 {c['skipped']}　待核实 {c['unknown']}")
        labels={'idle':'尚未开始','prepared':'预览完成','running':'运行中','waiting':'等待间隔','submitting':'当前邮件正在提交，请等待','paused':'已暂停','stopped':'已停止/等待本人继续','completed':'本表处理完毕','batch_done':'本批结束，等待确认下一批'}
        batch_text=f"{self.controller.job.get('batch_processed',0)}/{self.controller.job.get('batch_target',0)}" if self.controller.job else '0/0'
        self.detail.set(f"状态：{labels.get(snap['status'],snap['status'])}　下一封倒计时：{snap['countdown']}秒　批次：{snap['batch']}（已处理/本批计划 {batch_text}）　今日累计尝试：{snap['today']} / {cfg.get('cap',100)}\n当前客户：{snap['current']} <{snap['email']}>\n上一封/提示：{snap['last']}")
        self.attachment_label.set('附件：'+(', '.join(Path(p).name for p in self.attachments) or '无'))
        self._timer=self.root.after(250,self.poll)
    def close(self):
        if self.controller.busy or self.aux_busy:
            if messagebox.askyesno('安全关闭','当前操作尚未结束。是否请求安全停止？当前SMTP提交不会被强行中断，请完成后再关闭。',parent=self.root):self.controller.stop()
            return
        if self.projects:
            try:
                self.save_project_widgets()
            except Exception as exc:
                self.error(exc)
                return
        self.password='';self.controller.close();self.root.after_cancel(self._timer)
        if self.projects:
            self.projects.close()
        self.root.destroy()
