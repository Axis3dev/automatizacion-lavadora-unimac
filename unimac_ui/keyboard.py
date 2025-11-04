# =========================
#   TECLADOS EMBEBIDOS (con scale)
# =========================
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Optional, Callable

class KeyboardFrame(ttk.Frame):
    """
    Teclado embebido que escribe en el Entry objetivo.
    Nuevo: parámetro 'scale' para reducir/agrandar todo proporcionalmente.
    """
    def __init__(self, master, mode="text", title="Teclado", key_font=None,
                 getter: Optional[Callable[[], Optional[tk.Entry]]]=None,
                 btn_pad=(4,6), scale: float = 1.0):
        super().__init__(master, padding=int(3*scale))
        ttk.Label(self, text=title, font=("Segoe UI", max(10, int(11*scale)), "bold")).pack(anchor="w")
        self.mode=mode; self.shift=False; self.getter=getter

        # --- tamaño base y padding escalados ---
        base_size = 15
        if isinstance(key_font, tkfont.Font):
            base_size = int(key_font.cget("size"))
        elif key_font and isinstance(key_font, (tuple,list)) and len(key_font) > 1:
            try: base_size = int(key_font[1])
            except Exception: pass
        size = max(10, int(round(base_size * scale)))
        self.key_font = tkfont.Font(size=size, weight="bold")
        px, py = btn_pad
        self.btn_pad = (max(2, int(px*scale)), max(2, int(py*scale)))
        self.pad_xy = max(2, int(4*scale))

        if mode=="numeric":
            layout=[["7","8","9","⌫"],
                    ["4","5","6","Limpiar"],
                    ["1","2","3"],
                    ["0"]]
        else:
            layout=[
                list("1234567890"),
                list("qwertyuiop"),
                list("asdfghjkl"),
                ["⇧"] + list("zxcvbnm") + ["⌫"],
                ["ESPACIO","Limpiar"]
            ]

        style=ttk.Style(self); style.configure("Kb.TButton", font=self.key_font)
        for row in layout:
            rowf=ttk.Frame(self); rowf.pack(fill="x")
            for key in row:
                b=ttk.Button(rowf, text=key, style="Kb.TButton",
                             command=lambda k=key: self._press(k))
                b["padding"]=self.btn_pad
                b.pack(side="left", padx=self.pad_xy, pady=self.pad_xy, expand=True)

    def _target(self) -> Optional[tk.Entry]:
        return self.getter() if self.getter else None

    def _backspace(self, e: tk.Entry):
        try: s=e.index("sel.first"); t=e.index("sel.last"); e.delete(s,t); return
        except tk.TclError: pass
        try: pos=e.index("insert")
        except Exception: return
        if pos>0: e.delete(pos-1,pos)

    def _press(self, key:str):
        e=self._target()
        if not isinstance(e, tk.Entry): return
        if key=="⌫": self._backspace(e); e.focus_set(); return
        if key=="Limpiar": e.delete(0,tk.END); e.focus_set(); return
        if key=="ESPACIO": e.insert("insert"," "); e.focus_set(); return
        if key=="⇧": self.shift=not self.shift; return
        char=key.upper() if (self.mode!="numeric" and self.shift) else key
        e.insert("insert", char); e.focus_set()
