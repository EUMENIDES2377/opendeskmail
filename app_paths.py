"""Code and per-user state are separate in development and release builds."""
import os,re
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
APP_NAME='OpenDesk Mail'
VERSION='0.1.0'
def data_root(environ=None):
    env=os.environ if environ is None else environ;override=env.get('OPENDESK_MAIL_DATA_DIR')
    path=Path(override) if override else Path(env.get('LOCALAPPDATA') or Path.home()/'.local/share')/'OpenDeskMail'
    if not path.is_absolute():raise ValueError('OPENDESK_MAIL_DATA_DIR必须是源代码目录以外的绝对路径。')
    path=path.resolve()
    if path==CODE_ROOT or CODE_ROOT in path.parents:raise ValueError('用户运行数据必须放在程序/源代码目录以外。')
    return path
def profile_home(name='default',environ=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',name):raise ValueError('配置名称仅支持字母、数字、下划线和短横线。')
    return data_root(environ)/'profiles'/name
DATA_ROOT=data_root()
USER_HOME=profile_home()
