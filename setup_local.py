"""Build this installation's environment without modifying other tools."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def main():
    if sys.version_info<(3,10):raise RuntimeError('需要Python 3.10或更高版本。请从https://www.python.org/downloads/windows/安装含Tkinter的官方Windows版本。')
    import tkinter
    os.chdir(ROOT);python=ROOT/'.venv/Scripts/python.exe'
    if not python.exists():subprocess.run([sys.executable,'-m','venv',str(ROOT/'.venv')],check=True)
    else:subprocess.run([sys.executable,'-m','venv','--upgrade',str(ROOT/'.venv')],check=True)
    subprocess.run([str(python),'-c','import tkinter,sys;assert sys.version_info>=(3,10)'],check=True)
    args=[str(python),'-m','pip','install']
    if (ROOT/'wheelhouse').is_dir():args+=['--no-index','--find-links',str(ROOT/'wheelhouse')]
    locked=ROOT/'requirements-windows-py312.lock.txt'
    if sys.version_info[:2]==(3,12) and locked.exists():args+=['--require-hashes','-r',str(locked)]
    else:args+=['-r',str(ROOT/'requirements.txt')]
    subprocess.run(args,check=True)
    subprocess.run([str(python),'-m','unittest','discover','-s','tests','-q'],check=True)
    shortcut=ROOT/'create_shortcut.ps1'
    if '--no-shortcut' not in sys.argv:subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(shortcut)],check=True)
    print('Installation complete. Double-click launch.bat. No email has been sent.')

if __name__=='__main__':
    try:main()
    except Exception as exc:print('Installation failed:',str(exc));raise SystemExit(1)
