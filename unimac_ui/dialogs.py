# -*- coding: utf-8 -*-
from tkinter import ttk
import tkinter as tk

class BusyDialog(tk.Toplevel):
    def __init__(self, master, text="Procesando…"):
        super().__init__(master)
        self.title("Por favor espera")
        self.resizable(False, False)
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=text).pack()
        self.grab_set()
        self.update_idletasks()
