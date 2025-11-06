# -*- coding: utf-8 -*-
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable, Optional, Dict
import threading

try:
    from .serialconn import SerialConn
except ImportError:
    from unimac_ui.serialconn import SerialConn


class KeyboardFrame(ttk.Frame):
    def __init__(self, master, mode="numeric", title="Teclado",
                 getter=None, btn_pad=(4, 6), scale: float = 1.0):
        super().__init__(master, padding=int(3 * scale))
        ttk.Label(self, text=title, font=("Segoe UI", max(10, int(11 * scale)), "bold")).pack(anchor="w")
        self.mode = mode; self.shift = False; self.getter = getter
        base_size = 15; size = max(10, int(round(base_size * scale)))
        self.key_font = tkfont.Font(size=size, weight="bold")
        px, py = btn_pad; self.btn_pad = (max(2, int(px * scale)), max(2, int(py * scale)))
        self.pad_xy = max(2, int(4 * scale))
        if mode == "numeric":
            layout = [["7","8","9","⌫"],
                      ["4","5","6","Limpiar"],
                      ["1","2","3","OK"],
                      ["0"]]
        else:
            layout = [list("1234567890"),
                      list("qwertyuiop"),
                      list("asdfghjkl"),
                      ["⇧"]+list("zxcvbnm")+["⌫"],
                      ["ESPACIO","Limpiar","OK"]]
        style = ttk.Style(self); style.configure("Kb.TButton", font=self.key_font)
        for row in layout:
            rf = ttk.Frame(self); rf.pack(fill="x")
            for key in row:
                b = ttk.Button(rf, text=key, style="Kb.TButton", command=lambda k=key: self._press(k))
                b["padding"] = self.btn_pad; b.pack(side="left", padx=self.pad_xy, pady=self.pad_xy, expand=True)

    def _target(self): return self.getter() if self.getter else None
    def _backspace(self, e: tk.Entry):
        try: s=e.index("sel.first"); t=e.index("sel.last"); e.delete(s,t); return
        except tk.TclError: pass
        try: pos=e.index("insert")
        except Exception: return
        if pos>0: e.delete(pos-1,pos)
    def _press(self, key:str):
        e=self._target()
        if key=="OK":
            try: self.grid_remove()
            except Exception: pass
            if isinstance(e, tk.Entry): e.focus_set()
            return
        if key=="Limpiar" and isinstance(e, tk.Entry): e.delete(0,tk.END); e.focus_set(); return
        if key=="⌫" and isinstance(e, tk.Entry): self._backspace(e); e.focus_set(); return
        if key=="ESPACIO" and isinstance(e, tk.Entry): e.insert("insert"," "); e.focus_set(); return
        if key=="⇧": self.shift=not self.shift; return
        if isinstance(e, tk.Entry):
            char = key.upper() if (self.mode!="numeric" and self.shift) else key
            e.insert("insert", char); e.focus_set()


class SettingsDialog(tk.Toplevel):
    BAUDS = [9600, 19200, 38400, 57600, 115200, 250000]

    def __init__(self, master, serial: SerialConn,
                 on_save: Callable[[Optional[str], Optional[int], Dict[str,int], Dict[str,int], Dict[str,int], int], None]):
        super().__init__(master)
        self.title("Configuración"); self.attributes("-fullscreen", True); self.transient(master)
        self.serial = serial; self.on_save = on_save
        self.CFG = getattr(master, "CFG", {})

        self.f_title  = tkfont.Font(size=20, weight="bold")
        self.f_label  = tkfont.Font(size=16, weight="bold")
        self.f_field  = tkfont.Font(size=16)
        self.f_button = tkfont.Font(size=18, weight="bold")

        # Comunicación
        self.port_var = tk.StringVar(value=self.serial.preferred_port or "")
        self.baud_var = tk.IntVar(value=int(self.serial.baudrate or 115200))

        # Globals
        glb = self.CFG.get("globals", {})
        fill_legacy = glb.get("water_fill_seconds", {}) if isinstance(glb.get("water_fill_seconds", {}), dict) else {}
        dose_legacy = glb.get("chem_dose_seconds", {}) if isinstance(glb.get("chem_dose_seconds", {}), dict) else {}
        drain_legacy = glb.get("drain_seconds", {}) if isinstance(glb.get("drain_seconds", {}), dict) else {}

        def _ival(value, default):
            try:
                return int(value)
            except Exception:
                return default

        self.var_ligero   = tk.StringVar(value=str(_ival(glb.get("fill_seconds_ligero",   fill_legacy.get("ligero", 5)), 5)))
        self.var_estandar = tk.StringVar(value=str(_ival(glb.get("fill_seconds_estandar", fill_legacy.get("estandar", 8)), 8)))
        self.var_intenso  = tk.StringVar(value=str(_ival(glb.get("fill_seconds_intenso",  fill_legacy.get("intenso", 12)), 12)))

        self.var_q1 = tk.StringVar(value=str(_ival(glb.get("chem_seconds_detergente",  dose_legacy.get("Q1", 4)), 4)))
        self.var_q2 = tk.StringVar(value=str(_ival(glb.get("chem_seconds_quitamanchas", dose_legacy.get("Q2", 3)), 3)))
        self.var_q3 = tk.StringVar(value=str(_ival(glb.get("chem_seconds_suavizante",   dose_legacy.get("Q3", 2)), 2)))
        self.var_q4 = tk.StringVar(value=str(_ival(glb.get("chem_seconds_blanqueador",  dose_legacy.get("Q4", 2)), 2)))

        self.var_drain_l = tk.StringVar(value=str(_ival(glb.get("drain_seconds_ligero",   drain_legacy.get("ligero", 20)), 20)))
        self.var_drain_e = tk.StringVar(value=str(_ival(glb.get("drain_seconds_estandar", drain_legacy.get("estandar", 30)), 30)))
        self.var_drain_i = tk.StringVar(value=str(_ival(glb.get("drain_seconds_intenso",  drain_legacy.get("intenso", 45)), 45)))

        try:
            alt_def = int(glb.get("motor_alt_seconds", glb.get("alternancia_motor_s", 0)) or 0)
        except Exception:
            alt_def = 0
        self.var_alt = tk.StringVar(value=str(max(0, alt_def)))

        try:
            pause_def = int(glb.get("motor_pause_seconds", 2) or 0)
        except Exception:
            pause_def = 2
        self.var_motor_pause = tk.StringVar(value=str(max(0, pause_def)))

        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True)
        main = ttk.Frame(root); main.pack(fill="both", expand=True, pady=(0,8))
        main.columnconfigure(0, weight=1); main.columnconfigure(1, weight=1)

        # Comunicación
        comm = ttk.LabelFrame(main, text="Comunicación", padding=12)
        comm.grid(row=0, column=0, sticky="nsew", padx=(0,6), pady=(0,8))
        comm.columnconfigure(1, weight=1)
        ttk.Label(comm, text="Puerto:", font=self.f_label).grid(row=0,column=0,sticky="w",padx=(0,8),pady=(2,6))
        self.port_cb = ttk.Combobox(comm, textvariable=self.port_var, font=self.f_field, state="readonly", width=22)
        self.port_cb.grid(row=0,column=1,sticky="ew",pady=(2,6))
        ttk.Button(comm, text="Actualizar", command=self._refresh_ports).grid(row=0,column=2,padx=(8,0))
        ttk.Button(comm, text="Conectar", command=self._connect_now).grid(row=0,column=3,padx=(6,0))
        ttk.Label(comm, text="Baudrate:", font=self.f_label).grid(row=1,column=0,sticky="w",padx=(0,8),pady=(2,6))
        self.baud_cb = ttk.Combobox(comm, textvariable=self.baud_var, font=self.f_field,
                                    state="readonly", values=self.BAUDS, width=22)
        self.baud_cb.grid(row=1,column=1,sticky="ew",pady=(2,6))

        # Variables globales
        varsf = ttk.LabelFrame(main, text="Variables globales", padding=12)
        varsf.grid(row=0, column=1, sticky="nsew", padx=(6,0), pady=(0,8))
        varsf.columnconfigure(1, weight=1)

        ttk.Label(varsf, text="Nivel de agua Ligero (s):", font=self.f_label).grid(row=0,column=0,sticky="w",padx=(0,8),pady=4)
        e_l = ttk.Entry(varsf, textvariable=self.var_ligero, font=self.f_field, width=10, justify="right")
        e_l.grid(row=0,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Nivel de agua Estándar (s):", font=self.f_label).grid(row=1,column=0,sticky="w",padx=(0,8),pady=4)
        e_e = ttk.Entry(varsf, textvariable=self.var_estandar, font=self.f_field, width=10, justify="right")
        e_e.grid(row=1,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Nivel de agua Intenso (s):", font=self.f_label).grid(row=2,column=0,sticky="w",padx=(0,8),pady=4)
        e_i = ttk.Entry(varsf, textvariable=self.var_intenso, font=self.f_field, width=10, justify="right")
        e_i.grid(row=2,column=1,sticky="w",pady=4)

        sep1 = ttk.Separator(varsf); sep1.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8,6))
        ttk.Label(varsf, text="Tiempo dosificación (s)", font=self.f_label).grid(row=4,column=0,columnspan=2,sticky="w",pady=(0,6))

        ttk.Label(varsf, text="Q1 – Detergente (s):", font=self.f_label).grid(row=5,column=0,sticky="w",padx=(0,8),pady=4)
        e_q1 = ttk.Entry(varsf, textvariable=self.var_q1, font=self.f_field, width=10, justify="right")
        e_q1.grid(row=5,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Q2 – Quitamanchas (s):", font=self.f_label).grid(row=6,column=0,sticky="w",padx=(0,8),pady=4)
        e_q2 = ttk.Entry(varsf, textvariable=self.var_q2, font=self.f_field, width=10, justify="right")
        e_q2.grid(row=6,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Q3 – Suavizante (s):", font=self.f_label).grid(row=7,column=0,sticky="w",padx=(0,8),pady=4)
        e_q3 = ttk.Entry(varsf, textvariable=self.var_q3, font=self.f_field, width=10, justify="right")
        e_q3.grid(row=7,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Q4 – Blanqueador (s):", font=self.f_label).grid(row=8,column=0,sticky="w",padx=(0,8),pady=4)
        e_q4 = ttk.Entry(varsf, textvariable=self.var_q4, font=self.f_field, width=10, justify="right")
        e_q4.grid(row=8,column=1,sticky="w",pady=4)

        sep2 = ttk.Separator(varsf); sep2.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8,6))
        ttk.Label(varsf, text="Drenaje por nivel (s)", font=self.f_label).grid(row=10,column=0,columnspan=2,sticky="w",pady=(0,6))

        ttk.Label(varsf, text="Drenaje Ligero (s):", font=self.f_label).grid(row=11,column=0,sticky="w",padx=(0,8),pady=4)
        e_dl = ttk.Entry(varsf, textvariable=self.var_drain_l, font=self.f_field, width=10, justify="right")
        e_dl.grid(row=11,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Drenaje Estándar (s):", font=self.f_label).grid(row=12,column=0,sticky="w",padx=(0,8),pady=4)
        e_de = ttk.Entry(varsf, textvariable=self.var_drain_e, font=self.f_field, width=10, justify="right")
        e_de.grid(row=12,column=1,sticky="w",pady=4)

        ttk.Label(varsf, text="Drenaje Intenso (s):", font=self.f_label).grid(row=13,column=0,sticky="w",padx=(0,8),pady=4)
        e_di = ttk.Entry(varsf, textvariable=self.var_drain_i, font=self.f_field, width=10, justify="right")
        e_di.grid(row=13,column=1,sticky="w",pady=4)

        sep3 = ttk.Separator(varsf); sep3.grid(row=14, column=0, columnspan=2, sticky="ew", pady=(8,6))
        ttk.Label(varsf, text="Alternancia motor (s):", font=self.f_label).grid(row=15, column=0, sticky="w", padx=(0,8), pady=4)
        e_alt = ttk.Entry(varsf, textvariable=self.var_alt, font=self.f_field, width=10, justify="right")
        e_alt.grid(row=15, column=1, sticky="w", pady=4)

        ttk.Label(varsf, text="Pausa entre alternancias (s):", font=self.f_label).grid(row=16, column=0, sticky="w", padx=(0,8), pady=4)
        e_alt_pause = ttk.Entry(varsf, textvariable=self.var_motor_pause, font=self.f_field, width=10, justify="right")
        e_alt_pause.grid(row=16, column=1, sticky="w", pady=4)

        only_num = (self.register(lambda P: P.isdigit() or P==""), "%P")
        for ent in (e_l, e_e, e_i, e_q1, e_q2, e_q3, e_q4, e_dl, e_de, e_di, e_alt, e_alt_pause):
            ent.configure(validate="key", validatecommand=only_num)
            ent.bind("<FocusIn>", lambda ev, widget=ent: self._show_kb(widget))

        sysf = ttk.LabelFrame(main, text="Sistema", padding=12)
        sysf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0,8))
        ttk.Button(sysf, text="Apagar sistema", command=self._close_app).pack(side="left", padx=(0,8), pady=(4,4))

        bottom = ttk.Frame(root); bottom.pack(fill="x")
        ttk.Button(bottom, text="Cancelar", command=self._on_cancel).pack(side="right", padx=(0,8))
        ttk.Button(bottom, text="Guardar", command=self._on_save).pack(side="right", padx=(0,8))

        kbwrap = ttk.Frame(root); kbwrap.pack(fill="x", pady=(6,0))
        self._focused_entry: Optional[tk.Entry] = None
        self.kb_num = KeyboardFrame(kbwrap, mode="numeric", title="Teclado numérico",
                                    getter=lambda: self._focused_entry, scale=0.95)
        self.kb_num.pack(fill="x"); self.kb_num.pack_forget()
        self.bind_all("<Button-1>", self._global_click_filter, add="+")

        self._refresh_ports()
        self.bind("<Escape>", lambda e: self._on_cancel())

    # teclado
    def _show_kb(self, entry: tk.Entry):
        self._focused_entry = entry
        self.kb_num.pack(fill="x"); self.kb_num.lift()
    def _hide_kb(self):
        try: self.kb_num.pack_forget()
        except Exception: pass
    def _is_descendant(self, c: tk.Widget, p: tk.Widget) -> bool:
        try:
            w=c
            while w is not None:
                if w is p: return True
                w=w.master
        except Exception: pass
        return False
    def _global_click_filter(self, event):
        w = event.widget
        if self._is_descendant(w, self.kb_num): return
        if isinstance(w, tk.Entry): return
        self._hide_kb()

    # comunicación
    def _refresh_ports(self):
        try:
            from .serialconn import SerialConn as _SC
        except ImportError:
            from unimac_ui.serialconn import SerialConn as _SC

        ports = []
        try:
            ports = _SC.list_available_ports()
        except Exception:
            ports = []

        self.port_cb["values"] = ports

        current = (self.port_var.get() or "").strip()

        if not ports:
            self.port_var.set("")
            return

        if current and current in ports:
            self.port_var.set(current)
        else:
            self.port_var.set(ports[0])

    def _connect_now(self):
        """Conectar sin salir de Configuración."""
        sel_port = (self.port_var.get() or "").strip() or None
        try:
            sel_baud = int(self.baud_var.get() or 115200)
        except Exception:
            sel_baud = 115200

        def task():
            ok = False
            err_msg = ""
            try:
                self.serial.baudrate = sel_baud
                if sel_port:
                    ok = self.serial.connect(sel_port)
                else:
                    ok = self.serial.connect_auto()

                if ok:
                    try:
                        self.master.serial.preferred_port = self.serial.port_name
                    except Exception:
                        pass

                    try:
                        watcher = getattr(self.master, "comm_watcher", None)
                        if watcher:
                            watcher.stop()
                            watcher.join(timeout=1.0)
                    except Exception:
                        pass

                    try:
                        from .serialconn import CommWatcher as _CW
                    except ImportError:
                        from unimac_ui.serialconn import CommWatcher as _CW

                    self.master.comm_watcher = _CW(
                        self.master.serial,
                        poll_sec=0.5,
                        on_connect=getattr(self.master, "_on_comm_connected", None),
                        on_disconnect=getattr(self.master, "_on_comm_disconnected", None),
                        tk_after=self.master.after,
                    )
                    self.master.comm_watcher.start()
            except Exception as exc:
                err_msg = str(exc)
                ok = False

            self.after(0, lambda: self._post_connect_ui(ok, err_msg))

        threading.Thread(target=task, daemon=True).start()

    def _post_connect_ui(self, ok: bool, err: str = ""):
        if ok and self.serial.port_name:
            try:
                self.port_var.set(self.serial.port_name)
            except Exception:
                pass

        try:
            self.master._update_comm_panel_now()
        except Exception:
            pass

        if ok:
            try:
                self.master.toast("Conectado")
            except Exception:
                pass
        else:
            msg = "No se pudo conectar"
            if err:
                msg = f"{msg}: {err}"
            try:
                self.master.toast(msg)
            except Exception:
                pass

    # sistema
    def _close_app(self):
        try: self.master.destroy()
        except Exception: os._exit(0)
    def _on_cancel(self): self.destroy()

    def _on_save(self):
        fills={}
        for key,var in (("fill_seconds_ligero",self.var_ligero),
                        ("fill_seconds_estandar",self.var_estandar),
                        ("fill_seconds_intenso",self.var_intenso)):
            try: v=int(var.get() or "0")
            except Exception: v=0
            fills[key]=max(0,v)

        doses={}
        for key,var in (("chem_seconds_detergente",self.var_q1),
                        ("chem_seconds_quitamanchas",self.var_q2),
                        ("chem_seconds_suavizante",self.var_q3),
                        ("chem_seconds_blanqueador",self.var_q4)):
            try: v=int(var.get() or "0")
            except Exception: v=0
            doses[key]=max(0,v)

        drains={}
        for key,var in (("drain_seconds_ligero",self.var_drain_l),
                        ("drain_seconds_estandar",self.var_drain_e),
                        ("drain_seconds_intenso",self.var_drain_i)):
            try: v=int(var.get() or "0")
            except Exception: v=0
            drains[key]=max(0,v)

        try: alt = int(self.var_alt.get() or "0")
        except Exception: alt = 0
        alt = max(0, alt)

        try:
            motor_pause = int(self.var_motor_pause.get() or "0")
        except Exception:
            motor_pause = 0
        motor_pause = max(0, motor_pause)

        glb = self.CFG.setdefault("globals", {})
        glb["motor_pause_seconds"] = motor_pause

        port = (self.port_var.get().strip() or None)
        try: baud = int(self.baud_var.get() or 0)
        except Exception: baud = None

        self.on_save(port, baud, fills, doses, drains, alt)
        self.destroy()
