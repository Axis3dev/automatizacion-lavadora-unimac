# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk

def toast(parent: tk.Misc, text: str, ms: int = 1500):
    """
    Toast no modal, centrado abajo. Se cierra solo.
    parent: root o Toplevel
    """
    top = tk.Toplevel(parent)
    try:
        top.transient(parent)
    except Exception:
        pass
    top.overrideredirect(True)
    top.attributes("-topmost", True)

    frm = ttk.Frame(top, padding=10, relief="solid", borderwidth=1)
    ttk.Label(frm, text=text).pack()
    frm.pack()

    parent.update_idletasks()
    w, h = top.winfo_reqwidth(), top.winfo_reqheight()
    sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
    top.geometry(f"{w}x{h}+{(sw - w)//2}+{sh - h - 80}")

    top.after(ms, top.destroy)
