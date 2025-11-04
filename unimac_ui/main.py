# -*- coding: utf-8 -*-
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Optional, Dict

try:
    from .models import Cycle
    from .storage import list_cycles, load_cycle_from_txt, save_cycle_to_txt, CICLOS_DIR
    from .serialconn import SerialConn, CommWatcher, BAUDRATE, PREFERRED_PORT, CFG, save_config
    from .hardware import HardwareIO
    from .executor import Executor
    from .settings import SettingsDialog
    from .editor_v2 import TouchCycleEditor
    from .dialogs import BusyDialog
    from .esp32proto import Esp32Controller
    from .alerts import toast
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from unimac_ui.models import Cycle
    from unimac_ui.storage import list_cycles, load_cycle_from_txt, save_cycle_to_txt, CICLOS_DIR
    from unimac_ui.serialconn import SerialConn, CommWatcher, BAUDRATE, PREFERRED_PORT, CFG, save_config
    from unimac_ui.hardware import HardwareIO
    from unimac_ui.executor import Executor
    from unimac_ui.settings import SettingsDialog
    from unimac_ui.editor_v2 import TouchCycleEditor
    from unimac_ui.dialogs import BusyDialog
    from unimac_ui.esp32proto import Esp32Controller
    from unimac_ui.alerts import toast


class WasherUI(tk.Tk):
    TICK_MS = 200
    COMM_UI_MS = 250

    def __init__(self):
        super().__init__()
        self.title("Lavadora Industrial")
        self.attributes("-fullscreen", True)

        self.update_idletasks()
        screen_h = self.winfo_screenheight()
        self.is_720p = screen_h <= 720

        self._bump_fonts(2 if self.is_720p else 3)
        self.header_font = tkfont.Font(size=(16 if self.is_720p else 18), weight="bold")

        self.style = ttk.Style(self)
        self.style.configure("Arrow.TButton",
                             font=("Segoe UI", 16 if self.is_720p else 18, "bold"),
                             padding=(6, 8) if self.is_720p else (8, 10), width=3)
        self.style.configure("Top.TButton",
                             font=("Segoe UI", (21 if self.is_720p else 23), "bold"),
                             padding=((18, 14) if self.is_720p else (22, 16)))
        self.style.configure("Ctrl.TButton",
                             font=("Segoe UI", (22 if self.is_720p else 24), "bold"),
                             padding=((18, 14) if self.is_720p else (22, 16)))
        self.style.configure("Green.Horizontal.TProgressbar", background="#2ecc71")

        # Serial
        self.serial = SerialConn(baudrate=BAUDRATE, preferred_port=PREFERRED_PORT)
        self.comm_watcher = CommWatcher(self.serial, poll_sec=0.5)
        self.comm_watcher.start()

        self.CFG = CFG

        # HW / Executor
        self.hw = HardwareIO(
            get_fill_seconds=lambda: self.CFG.get("globals", {}).get("water_fill_seconds", {"ligero":5,"estandar":8,"intenso":12}),
            get_dose_seconds=lambda: self.CFG.get("globals", {}).get("chem_dose_seconds", {"Q1":4,"Q2":3,"Q3":2,"Q4":2})
        )
        self.executor = Executor(self.hw,
                                 self._update_status_text,
                                 self._on_tick,
                                 self._on_step_change,
                                 self._on_finish)

        # Controller con accessors a config (dosis y alternancia)
        self.controller = Esp32Controller(
            after=self.after,
            cancel_after=self.after_cancel,
            send=lambda obj: self.serial.send_json(obj),
            on_info=lambda s: self.toast(s),
            get_dose_seconds=lambda: self.CFG.get("globals", {}).get("chem_dose_seconds",
                               {"Q1":4,"Q2":3,"Q3":2,"Q4":2}),
            get_alt_seconds=lambda: int(self.CFG.get("globals", {}).get("alternancia_motor_s", 0) or 0),
            get_fill_seconds=lambda: self.CFG.get("globals", {}).get("water_fill_seconds", {"ligero":5,"estandar":8,"intenso":12})
        )

        # Estado UI
        self._settings_win = None
        self._editor_win = None
        self.selected_cycle: Optional[Cycle] = None
        self._scroll_job = None
        self.current_cycle_total = 0
        self.current_step_name = tk.StringVar(value="—")

        self._build_ui()
        self._load_cycle_list()

        self.after(self.TICK_MS, self._loop_logic)
        self.after(self.COMM_UI_MS, self._update_comm_panel_periodic)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- utils ----------
    def _bump_fonts(self, delta=2):
        for name in ("TkDefaultFont","TkTextFont","TkHeadingFont","TkMenuFont",
                     "TkTooltipFont","TkCaptionFont","TkSmallCaptionFont","TkFixedFont","TkIconFont"):
            try:
                f = tkfont.nametofont(name); f.configure(size=max(10, f.cget("size")+delta))
            except Exception:
                pass

    def toast(self, text: str, ms: int = 1500): toast(self, text, ms)

    # ---------- UI ----------
    def _build_ui(self):
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True)

        bar = ttk.Frame(root); bar.pack(fill="x", pady=(0,8))
        ttk.Button(bar, text="✎  Editar Ciclo", style="Top.TButton",
                   command=self._select_or_edit).pack(side="left", padx=(0,8))
        ttk.Button(bar, text="+  Crear Ciclo", style="Top.TButton",
                   command=self._create_cycle_dialog).pack(side="left", padx=(0,8))
        ttk.Button(bar, text="X  Eliminar", style="Top.TButton",
                   command=self._delete_selected_cycle).pack(side="left", padx=(0,8))
        ttk.Button(bar, text="⚙  Configuración", style="Top.TButton",
                   command=self._open_settings).pack(side="right")

        body = ttk.Frame(root); body.pack(fill="both", expand=True)

        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        comm = ttk.Frame(left); comm.pack(fill="x", pady=(0,6))
        ttk.Label(comm, text="Comunicación", font=self.header_font).grid(row=0,column=0,sticky="w",padx=(0,8))
        self.comm_canvas = tk.Canvas(comm, width=16, height=16, highlightthickness=0)
        self.comm_light = self.comm_canvas.create_oval(2,2,14,14,fill="#e74c3c")
        self.comm_canvas.grid(row=0,column=1,sticky="w")
        self.comm_status_var = tk.StringVar(value="Desconectado")
        ttk.Label(comm, textvariable=self.comm_status_var).grid(row=0,column=2,sticky="w",padx=(6,12))
        ttk.Label(comm, text="Puerto:").grid(row=0,column=3,sticky="e")
        self.comm_port_var = tk.StringVar(value="—")
        ttk.Label(comm, textvariable=self.comm_port_var, font=("Segoe UI",11,"bold")).grid(row=0,column=4,sticky="w",padx=(4,0))
        comm.columnconfigure(5, weight=1); self._update_comm_panel_now()

        ttk.Label(left, text="Ciclos Disponibles", font=self.header_font).pack(anchor="w", pady=(6,6))
        list_row = ttk.Frame(left); list_row.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_row, exportselection=False, font=("Segoe UI", 18 if not self.is_720p else 16))
        self.listbox.grid(row=0,column=0,sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_list_select())
        arrows = ttk.Frame(list_row); arrows.grid(row=0,column=1,sticky="ns",padx=(6,0))
        up = ttk.Button(arrows, text="▲", style="Arrow.TButton", command=lambda: self._scroll_once("up"))
        dn = ttk.Button(arrows, text="▼", style="Arrow.TButton", command=lambda: self._scroll_once("down"))
        up.pack(fill="x",pady=(0,6)); dn.pack(fill="x")
        up.bind("<ButtonPress-1>", lambda e: self._scroll_hold("up"))
        dn.bind("<ButtonPress-1>", lambda e: self._scroll_hold("down"))
        up.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        dn.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        list_row.columnconfigure(0,weight=1); list_row.rowconfigure(0,weight=1)

        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Detalles", font=self.header_font).pack(anchor="w", pady=(0,6))
        self.details = tk.Text(right, height=18, wrap="word", state="disabled", font=("Segoe UI", 16 if not self.is_720p else 14))
        self.details.pack(fill="both", expand=True)

        controls = ttk.Frame(root); controls.pack(fill="x", pady=8)
        self.btn_run = ttk.Button(controls, text="▶  Ejecutar", style="Ctrl.TButton", command=self._start_execution)
        self.btn_run.pack(side="left", padx=(0,8))
        self.btn_pause = ttk.Button(controls, text="⏸  Pausar", style="Ctrl.TButton",
                                    command=self._pause_resume, state="disabled")
        self.btn_pause.pack(side="left", padx=(0,8))
        self.btn_stop  = ttk.Button(controls, text="■  Detener", style="Ctrl.TButton",
                                    command=self._stop_execution, state="disabled")
        self.btn_stop.pack(side="left")

        footer = ttk.Frame(root); footer.pack(fill="x", pady=(4,0))
        ttk.Label(footer, textvariable=self.current_step_name, font=("Segoe UI", 12 if self.is_720p else 14, "bold")).pack(anchor="w", pady=(0,2))
        self.status = tk.Label(footer, text="Estado actual: Inactivo", font=("Segoe UI", 12 if self.is_720p else 14, "bold"), anchor="w")
        self.status.pack(side="left", padx=(0,10))
        self.pb_var = tk.IntVar(value=0)
        self.pb = ttk.Progressbar(footer, variable=self.pb_var, maximum=100, style="Green.Horizontal.TProgressbar")
        self.pb.pack(side="left", fill="x", expand=True)
        self.pb_pct = ttk.Label(footer, text="0%", font=("Segoe UI", 11 if self.is_720p else 12, "bold"))
        self.pb_pct.pack(side="left", padx=8)

    # scroll
    def _scroll_once(self, direction: str): self.listbox.yview_scroll(-3 if direction=="up" else 3, "units")
    def _scroll_hold(self, direction: str):
        self._scroll_once(direction); self._scroll_job = self.after(120, lambda: self._scroll_hold(direction))
    def _scroll_release(self):
        if self._scroll_job: self.after_cancel(self._scroll_job); self._scroll_job=None

    # comunicación
    def _update_comm_panel_now(self):
        ok = self.serial.is_connected()
        self.comm_canvas.itemconfig(self.comm_light, fill="#2ecc71" if ok else "#e74c3c")
        self.comm_status_var.set("Conectado" if ok else "Desconectado")
        self.comm_port_var.set(self.serial.port_name or (self.serial.preferred_port or "—"))

    def _update_comm_panel_periodic(self):
        self._update_comm_panel_now(); self.after(self.COMM_UI_MS, self._update_comm_panel_periodic)

    def _send_event(self, event: str, **kw): self.serial.send_json({"event": event, **kw})

    # agua/drenaje helpers
    def _action_uses_water(self, accion: str) -> bool:
        a = (accion or "").strip().lower()
        return a in ("prelavado", "lavado", "enjuague")

    def _fill_seconds_for_level(self, level: Optional[str]) -> int:
        g = self.CFG.get("globals", {}).get("water_fill_seconds", {"ligero":5,"estandar":8,"intenso":12})
        key = (level or "estandar").strip().lower()
        try: return int(g.get(key, g.get("estandar", 8)))
        except Exception: return 8

    def _drain_seconds_for_level(self, level: Optional[str]) -> int:
        g = self.CFG.get("globals", {}).get("drain_seconds", {"ligero":20,"estandar":30,"intenso":45})
        key = (level or "estandar").strip().lower()
        try: return int(g.get(key, g.get("estandar", 30)))
        except Exception: return 30

    # ciclos
    def _select_or_edit(self):
        if self.selected_cycle: self._open_editor_for(self.selected_cycle)
        else: self._load_cycle_list(); self.toast("Lista de ciclos actualizada.")

    def _open_editor_for(self, cycle: Cycle):
        if self._editor_win and self._editor_win.winfo_exists():
            self._editor_win.lift(); self._editor_win.focus_force(); return
        self._editor_win = TouchCycleEditor(self, on_save=self._on_cycle_saved, preload=cycle)

    def _create_cycle_dialog(self):
        if self._editor_win and self._editor_win.winfo_exists():
            self._editor_win.lift(); self._editor_win.focus_force(); return
        self._editor_win = TouchCycleEditor(self, on_save=self._on_cycle_saved)

    def _on_cycle_saved(self, cycle: Cycle):
        fname = cycle.nombre.replace(" ", "_") + ".txt"
        save_cycle_to_txt(cycle, os.path.join(CICLOS_DIR, fname))
        self._load_cycle_list(); self.toast(f"Ciclo '{cycle.nombre}' guardado.")
        try:
            idx = list_cycles().index(fname)
            self.listbox.selection_clear(0,"end"); self.listbox.selection_set(idx)
            self.listbox.event_generate("<<ListboxSelect>>")
        except ValueError: pass
        self._editor_win = None

    def _delete_selected_cycle(self):
        idx = self.listbox.curselection()
        if not idx: self.toast("Selecciona un ciclo para eliminar."); return
        filename = list_cycles()[idx[0]]
        path = os.path.join(CICLOS_DIR, filename)
        try: os.remove(path); self.toast("Ciclo eliminado.")
        except Exception as e: self.toast(f"Error: {e}")
        self._load_cycle_list(); self.selected_cycle=None; self._render_details(None)

    def _load_cycle_list(self):
        self.listbox.delete(0,"end")
        for f in list_cycles(): self.listbox.insert("end", f[:-4].replace("_"," "))

    def _on_list_select(self):
        idx = self.listbox.curselection()
        if not idx: self.selected_cycle=None; self._render_details(None); return
        path = os.path.join(CICLOS_DIR, list_cycles()[idx[0]])
        self.selected_cycle = load_cycle_from_txt(path)
        self._render_details(self.selected_cycle)

    def _render_details(self, cycle: Optional[Cycle]):
        self.details.config(state="normal"); self.details.delete("1.0","end")
        if not cycle:
            self.details.insert("end","Selecciona un ciclo para ver sus detalles.")
        else:
            temp = f" (Agua {cycle.agua_temp})" if getattr(cycle,"agua_temp",None) else ""
            self.details.insert("end", f"{cycle.nombre}{temp}\n\n")
            for i,p in enumerate(cycle.pasos,1):
                self.details.insert("end", p.to_human(i)+"\n")
        self.details.config(state="disabled")

    # estado/progreso
    def _update_status_text(self, text: str):
        if text=="Ejecutando" and self.selected_cycle:
            self._send_event("start", cycle=self.selected_cycle.nombre,
                             steps=len(self.selected_cycle.pasos),
                             total=self.selected_cycle.total_duracion)
        elif text=="Pausado": self._send_event("pause")
        elif text=="Reanudado": self._send_event("resume")
        elif text.startswith("Detenido"): self._send_event("stop")
        if not (self.selected_cycle and self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD)):
            self.status.config(text=f"Estado actual: {text}")

    def _fmt_secs(self, s:int)->str:
        m,sec = divmod(max(0,s),60); return f"{m}:{sec:02d}"

    def _update_progress(self, total_remaining:int):
        if not self.current_cycle_total:
            self.pb_var.set(0); self.pb_pct.config(text="0%"); return
        done = self.current_cycle_total - total_remaining
        pct = max(0,min(100,int(done*100/self.current_cycle_total)))
        self.pb_var.set(pct); self.pb_pct.config(text=f"{pct}%")

    def _on_tick(self, step_idx:int, step_remaining:int, total_remaining:int):
        if self.selected_cycle and self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            step_n = step_idx + 1; total = len(self.selected_cycle.pasos)
            label_state = "Pausado" if self.executor.state==Executor.PAUSED else ("Drenando" if self.executor.state==Executor.HOLD else "Lavando")
            self.status.config(text=f"Estado actual: {label_state} - Paso {step_n} de {total} - Tiempo restante: {self._fmt_secs(total_remaining)}")
        self._update_progress(total_remaining)

    def _on_step_change(self, i:int):
        if not self.selected_cycle: return
        try: s = self.selected_cycle.pasos[i]
        except IndexError: return
        self.current_cycle_total = self.selected_cycle.total_duracion
        self.current_step_name.set(f"Paso actual: {s.accion.capitalize()}")

        # duración mínima por llenado si aplica
        if self._action_uses_water(s.accion):
            level = getattr(s,"nivel_agua", getattr(self.selected_cycle,"nivel_agua","estandar"))
            fill_sec = self._fill_seconds_for_level(level)
            try: cur = int(getattr(s,"duracion",0) or 0)
            except Exception: cur = 0
            if cur < fill_sec:
                s.duracion = fill_sec
                self.toast(f"Duración de '{s.accion}' ajustada a {fill_sec}s para completar llenado.")

        # evento
        self._send_event("step",
                         index=i,
                         accion=s.accion,
                         duracion=int(getattr(s,"duracion",0) or 0),
                         nivel=getattr(s,"nivel_agua",None),
                         quimicos=getattr(s,"quimicos",[]),
                         velocidad=getattr(s,"velocidad",None))

        # drenaje entre pasos con PAUSA REAL
        prev_step = None
        if i>0 and self.selected_cycle:
            try: prev_step = self.selected_cycle.pasos[i-1]
            except Exception: prev_step = None

        def start_current_step():
            # al empezar el paso, asegurar estado "Ejecutando"
            self.executor._clear_hold()
            self.current_step_name.set(f"Paso actual: {s.accion.capitalize()}")
            self.controller.run_step(
                accion=s.accion,
                duracion=int(getattr(s,"duracion",0) or 0),
                nivel_agua=getattr(s,"nivel_agua", getattr(self.selected_cycle,"nivel_agua","estandar")),
                agua=(getattr(self.selected_cycle,"agua_temp",None) or getattr(s,"agua",None)),
                quimicos=list(getattr(s,"quimicos",[])),
                velocidad=getattr(s,"velocidad",None),
            )

        if prev_step and self._action_uses_water(prev_step.accion):
            next_is_spin_or_drain = (s.accion or "").strip().lower() in ("centrifugado","spin","drenaje","descarga")
            if not next_is_spin_or_drain:
                prev_level = getattr(prev_step,"nivel_agua", getattr(self.selected_cycle,"nivel_agua","estandar"))
                dsec = self._drain_seconds_for_level(prev_level)
                self.current_step_name.set("Drenando…")
                self.executor.hold_for(dsec, label="Drenando…")
                self.controller.run_drain(dsec)
                self.after(dsec*1000 + 200, start_current_step)
            else:
                start_current_step()
        else:
            start_current_step()

    def _on_finish(self):
        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.btn_run.config(state="normal")
        self.controller.finish_cycle()
        self._send_event("finish")
        self.pb_var.set(100); self.pb_pct.config(text="100%")
        self.current_step_name.set("—")

    # ejecución
    def _start_execution(self):
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            self.toast("Ya hay un ciclo en ejecución."); return
        if not self.selected_cycle:
            self.toast("Selecciona un ciclo primero."); return
        self.executor.load_cycle(self.selected_cycle)
        self.current_cycle_total = self.selected_cycle.total_duracion
        self.executor.start()
        self.controller.start_cycle()
        self._update_progress(self.executor.total_remaining)
        self.btn_run.config(state="disabled")
        self.btn_pause.config(state="normal", text="⏸  Pausar")
        self.btn_stop.config(state="normal")

    def _pause_resume(self):
        self.executor.pause()
        if self.executor.state == Executor.PAUSED:
            self.controller.cancel_all()
            self.btn_pause.config(text="▶  Reanudar")
        else:
            self.btn_pause.config(text="⏸  Pausar")

    def _stop_execution(self):
        self.executor.stop()
        self.controller.cancel_all()
        # estado seguro mínimo
        self.serial.send_json({"cmd":"vfd","run":"off"})
        self.serial.send_json({"cmd":"out","target":"WATER_COLD","on":0})
        self.serial.send_json({"cmd":"out","target":"WATER_HOT","on":0})
        self.serial.send_json({"cmd":"out","target":"DRAIN","on":0})
        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.btn_run.config(state="normal")
        self.pb_var.set(0); self.pb_pct.config(text="0%"); self.current_step_name.set("—")

    # settings
    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift(); self._settings_win.focus_force(); return
        self._settings_win = SettingsDialog(self, self.serial, on_save=self._on_settings_saved)

    def _on_settings_saved(self,
                           new_port: Optional[str],
                           new_baud: Optional[int],
                           new_fills: Dict[str,int],
                           new_doses: Dict[str,int],
                           new_drains: Dict[str,int],
                           alt_seconds: int):
        changed = False
        if new_port and new_port != self.serial.preferred_port:
            self.serial.preferred_port = new_port; CFG["serial_port"] = new_port; changed=True
        if new_baud and new_baud != self.serial.baudrate:
            self.serial.baudrate = new_baud; CFG["baudrate"] = new_baud; changed=True

        g = CFG.setdefault("globals", {})
        g["water_fill_seconds"] = dict(new_fills or {})
        g["chem_dose_seconds"]  = {
            "Q1": int((new_doses or {}).get("Q1",4)),
            "Q2": int((new_doses or {}).get("Q2",3)),
            "Q3": int((new_doses or {}).get("Q3",2)),
            "Q4": int((new_doses or {}).get("Q4",2)),
        }
        g["drain_seconds"]      = {
            "ligero":   int((new_drains or {}).get("ligero",20)),
            "estandar": int((new_drains or {}).get("estandar",30)),
            "intenso":  int((new_drains or {}).get("intenso",45)),
        }
        g["alternancia_motor_s"] = int(alt_seconds or 0)

        save_config(CFG)

        if changed:
            try:
                self.comm_watcher.stop(); self.comm_watcher.join(timeout=1.0)
            except Exception: pass
            busy = BusyDialog(self, "Aplicando configuración y reconectando…")
            import threading
            def task():
                try:
                    if self.serial.is_connected(): self.serial.close()
                    ok = False
                    if self.serial.preferred_port: ok = self.serial.connect(self.serial.preferred_port)
                    if not ok: self.serial.connect_auto()
                finally:
                    self.after(0, lambda: self._after_reconnect(busy))
            threading.Thread(target=task, daemon=True).start()
        else:
            self._update_comm_panel_now(); self.toast("Configuración guardada.")

    def _after_reconnect(self, busy):
        try: busy.destroy()
        except Exception: pass
        self.comm_watcher = CommWatcher(self.serial, poll_sec=0.5)
        self.comm_watcher.start()
        self._update_comm_panel_now()
        self.toast("Conexión actualizada.")

    # loop/cierre
    def _loop_logic(self):
        self.executor.tick()
        self.after(self.TICK_MS, self._loop_logic)

    def _on_close(self):
        try:
            self.comm_watcher.stop(); self.comm_watcher.join(timeout=1.0)
            self.serial.close()
        finally:
            self.destroy()


def main():
    try: os.makedirs(CICLOS_DIR, exist_ok=True)
    except Exception: pass
    app = WasherUI(); app.mainloop()

if __name__ == "__main__":
    main()
