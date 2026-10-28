"""Audit only explicitly publishable files; never scan local user profiles."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
MODULES='account_guard app_paths app configure core credentials demo desktop desktop_runtime first_run html_signature mail_archive main mime_check v2_delivery v2_engine v2_gui v2_model setup_local'.split()
DOCUMENTS=['README.md','AGENTS.md','ARCHITECTURE.md','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','DEPENDENCIES.md','BUILDING.md','THIRD_PARTY_NOTICES.md','使用说明.md','邮箱配置说明.md','给其他AI的配置提示词.md','签名导入说明.md','故障排查.md','功能对照.md','本地开发验证记录.md']
OTHER=['.gitignore','LICENSE','THIRD_PARTY_MAILMERGE_LICENSE.txt','requirements.txt','requirements-windows-py312.lock.txt','config.example.json','install.bat','launch.bat','离线演示.bat','create_shortcut.ps1']
EXAMPLES=['examples/ai-config.example.json','examples/test-mail.example.json','examples/customers.example.csv','examples/signature/signature.example.html','examples/signature/logo.example.png','examples/templates/english.example.txt','examples/templates/spanish.example.txt','examples/templates/portuguese.example.txt','examples/templates/body.example.html']

def source_files():
    fixed=[ROOT/(n+'.py') for n in MODULES]+[ROOT/n for n in DOCUMENTS+OTHER+EXAMPLES]
    licenses=[p for p in (ROOT/'licenses').rglob('*') if p.is_file()]
    return sorted(set(fixed+list((ROOT/'tests').glob('test_*.py'))+list((ROOT/'tools').glob('*.py'))+licenses+list((ROOT/'.github').rglob('*.yml'))))

def audit():
    files=source_files();errors=[]
    for path in files:
        rel=path.relative_to(ROOT).as_posix()
        if not path.is_file():errors.append('missing: '+rel);continue
        if path.is_symlink():errors.append('symlink: '+rel)
        if path.suffix.lower() in {'.db','.sqlite','.eml','.log','.lnk','.exe','.dll','.pyd'}:errors.append('runtime file: '+rel)
        if path.suffix.lower() in {'.py','.md','.json','.bat','.ps1','.csv','.txt','.html'} and not rel.startswith('licenses/'):
            content=path.read_text(encoding='utf-8-sig')
            # Terms assembled to avoid this scanner matching itself.
            banned=['UNI'+'COIN','uni'+'coinrubber.com','同'+'事版','清空个人'+'资料后分享','同事独立'+'使用版']
            if any(word in content for word in banned):errors.append('private/obsolete branding: '+rel)
            if re.search(r'[A-Za-z]:[\\/]Users[\\/]',content):errors.append('machine path: '+rel)
    example=json.loads((ROOT/'examples/ai-config.example.json').read_text(encoding='utf-8'))
    if example.get('credential',{}).get('value'):errors.append('example credential must be empty')
    cfg=json.loads((ROOT/'config.example.json').read_text(encoding='utf-8'))
    if any(k in cfg for k in ('password','secret','token')):errors.append('secret config key')
    if errors:raise ValueError('\n'.join(errors))
    return files

if __name__=='__main__':
    files=audit();print(json.dumps({'ok':True,'source_files':len(files),'user_data_included':False},ensure_ascii=False))
