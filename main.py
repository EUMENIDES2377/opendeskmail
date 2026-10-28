"""Production entrypoint, no AI SDK or online generation dependency."""
import tkinter as tk
from tkinter import messagebox
from v2_gui import Application
def main():
    root=tk.Tk()
    try:Application(root)
    except Exception as exc:messagebox.showerror('无法启动',str(exc),parent=root);root.destroy();return
    root.mainloop()
if __name__=='__main__':main()
