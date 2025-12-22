# -*- coding: utf-8 -*-
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from typing import Optional, Dict

try:
    from .models import Cycle
    from .storage import list_cycles, load_cycle_from_txt, save_cycle_to_txt, CICLOS_DIR
    from unimac_serial.serial_manager import SerialManager, BAUDRATE, PREFERRED_PORT, CFG, save_config
    from .hardware import HardwareIO
    from .executor import Executor
    from .settings import SettingsDialog
    from .editor_v2 import TouchCycleEditor
    from .dialogs import BusyDialog
    from .alerts import toast
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from unimac_ui.models import Cycle
    from unimac_ui.storage import list_cycles, load_cycle_from_txt, save_cycle_to_txt, CICLOS_DIR
    from unimac_serial.serial_manager import SerialManager, BAUDRATE, PREFERRED_PORT, CFG, save_config
    from unimac_ui.hardware import HardwareIO
    from unimac_ui.executor import Executor
    from unimac_ui.settings import SettingsDialog
    from unimac_ui.editor_v2 import TouchCycleEditor
    from unimac_ui.dialogs import BusyDialog
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

        # Serial manager dedicado (hilo daemon con reconexión y handshake)
        self.serial = SerialManager(
            baudrate=BAUDRATE,
            preferred_port=PREFERRED_PORT,
            on_json=self._on_serial_json,
            on_connect=self._on_comm_connected,
            on_disconnect=self._on_comm_disconnected,
            tk_after=self.after,
        )
        self._comm_last_state = self.serial.is_connected()
        self.serial.start()

        self.CFG = CFG

        # HW / Controller / Executor
        self.hw = HardwareIO(
            get_fill_seconds=self._fill_table,
            get_dose_seconds=self._chem_table,
        )
        self.executor = Executor(
            self.hw,
            self._update_status_text,
            self._on_tick,
            self._on_step_change,
            self._on_finish,
            send_event=lambda payload: self.serial.send_json(payload),
            get_fill_seconds=self._fill_table,
            get_chem_seconds=self._chem_table,
            get_drain_seconds=self._drain_table,
            get_motor_alt_seconds=self._motor_alt_seconds,
        )
        self.executor.ui_send_event = lambda ev, **kw: (
            self._send_speed(kw.get("valor")) if ev == "speed" else self.serial.send_json({"event": ev, **kw})
        )
        self.executor.serial = self.serial
        globals_cfg = self.CFG.get("globals", {}) if isinstance(self.CFG, dict) else {}

        def _cfg_int(value, default):
            try:
                return int(value)
            except Exception:
                return default

        fill_defaults = globals_cfg.get("water_fill_seconds", {}) if isinstance(globals_cfg.get("water_fill_seconds"), dict) else {}
        self.executor.cfg_fill = {
            "ligero": _cfg_int(globals_cfg.get("fill_seconds_ligero", fill_defaults.get("ligero", 5)), 5),
            "estandar": _cfg_int(globals_cfg.get("fill_seconds_estandar", fill_defaults.get("estandar", 8)), 8),
            "intenso": _cfg_int(globals_cfg.get("fill_seconds_intenso", fill_defaults.get("intenso", 12)), 12),
        }

        chem_defaults = globals_cfg.get("chem_dose_seconds", {}) if isinstance(globals_cfg.get("chem_dose_seconds"), dict) else {}
        self.executor.cfg_chems = {
            "detergente": _cfg_int(globals_cfg.get("chem_seconds_detergente", chem_defaults.get("Q1", 5)), 5),
            "quitamanchas": _cfg_int(globals_cfg.get("chem_seconds_quitamanchas", chem_defaults.get("Q2", 5)), 5),
            "suavizante": _cfg_int(globals_cfg.get("chem_seconds_suavizante", chem_defaults.get("Q3", 5)), 5),
            "blanqueador": _cfg_int(globals_cfg.get("chem_seconds_blanqueador", chem_defaults.get("Q4", 5)), 5),
        }

        alt_default = globals_cfg.get("alternancia_motor_s", globals_cfg.get("motor_alt_seconds", 0))
        pause_default = globals_cfg.get("motor_pause_seconds", 0)
        self.executor.cfg_motor = {
            "alt_every_s": _cfg_int(globals_cfg.get("motor_alt_seconds", alt_default), 0),
            "alt_pause_s": _cfg_int(globals_cfg.get("motor_pause_seconds", pause_default), 0),
        }

        # Estado puerta / control ejecución
        self.door_state: Optional[bool] = None
        self.door_var = tk.StringVar(value="Puerta: —")
        self.door_locked: bool = True
        self.door_btn_text = tk.StringVar(value="Desbloquear puerta")
        self.run_btn_text = tk.StringVar(value="▶  Ejecutar")
        self._run_btn_default_text = self.run_btn_text.get()
        self._run_btn_normal_foreground = ""
        self._run_btn_holder: Optional[ttk.Frame] = None

        # Estado UI
        self._settings_win = None
        self._editor_win = None
        self.selected_cycle: Optional[Cycle] = None
        self._scroll_job = None
        self.current_cycle_total = 0
        self.current_step_name = tk.StringVar(value="—")
        self._latched_cycle: Optional[Cycle] = None
        self._latched_total_steps: int = 0

        self._build_ui()
        self._apply_door_state(None)
        self._load_cycle_list()
        self.after(0, self._cache_run_button_size)
        self._sync_run_button_state()

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
        self.btn_edit = ttk.Button(bar, text="✎  Editar Ciclo", style="Top.TButton",
                                   command=self._select_or_edit)
        self.btn_edit.pack(side="left", padx=(0,8))
        self.btn_create = ttk.Button(bar, text="+  Crear Ciclo", style="Top.TButton",
                                     command=self._create_cycle_dialog)
        self.btn_create.pack(side="left", padx=(0,8))
        self.btn_delete = ttk.Button(bar, text="X  Eliminar", style="Top.TButton",
                                     command=self._delete_selected_cycle)
        self.btn_delete.pack(side="left", padx=(0,8))
        self.btn_settings = ttk.Button(bar, text="⚙  Configuración", style="Top.TButton",
                                       command=self._open_settings)
        self.btn_settings.pack(side="right")

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
        run_holder = ttk.Frame(controls)
        run_holder.pack(side="left", padx=(0,8))
        self._run_btn_holder = run_holder
        self.btn_run = ttk.Button(run_holder, textvariable=self.run_btn_text, style="Ctrl.TButton", command=self._start_execution)
        self.btn_run.pack()
        self.btn_pause = ttk.Button(controls, text="⏸  Pausar", style="Ctrl.TButton",
                                    command=self._pause_resume, state="disabled")
        self.btn_pause.pack(side="left", padx=(0,8))
        self.btn_stop  = ttk.Button(controls, text="■  Detener", style="Ctrl.TButton",
                                    command=self._stop_execution, state="disabled")
        self.btn_stop.pack(side="left")
        self.btn_door = ttk.Button(controls, textvariable=self.door_btn_text, style="Ctrl.TButton",
                                    command=self._toggle_door_lock)
        self.btn_door.pack(side="right")

        footer = ttk.Frame(root); footer.pack(fill="x", pady=(4,0))
        ttk.Label(footer, textvariable=self.current_step_name, font=("Segoe UI", 12 if self.is_720p else 14, "bold")).pack(anchor="w", pady=(0,2))
        self.status = tk.Label(footer, text="Estado actual: Inactivo", font=("Segoe UI", 12 if self.is_720p else 14, "bold"), anchor="w")
        self.status.pack(side="left", padx=(0,10))
        self.lbl_door = ttk.Label(footer, textvariable=self.door_var, font=self.status.cget("font"))
        self.lbl_door.pack(side="left", padx=(0,10))
        try:
            self.lbl_door.configure(foreground="#95a5a6")
        except Exception:
            pass
        self.pb_var = tk.IntVar(value=0)
        self.pb = ttk.Progressbar(footer, variable=self.pb_var, maximum=100, style="Green.Horizontal.TProgressbar")
        self.pb.pack(side="left", fill="x", expand=True)
        self.pb_pct = ttk.Label(footer, text="0%", font=("Segoe UI", 11 if self.is_720p else 12, "bold"))
        self.pb_pct.pack(side="left", padx=8)

    def _cache_run_button_size(self):
        holder = getattr(self, "_run_btn_holder", None)
        if not holder or not getattr(self, "btn_run", None):
            return
        try:
            self.update_idletasks()
            width = max(1, self.btn_run.winfo_reqwidth())
            height = max(1, self.btn_run.winfo_reqheight())
            holder.configure(width=width, height=height)
            holder.pack_propagate(False)
            if not self._run_btn_normal_foreground:
                try:
                    self._run_btn_normal_foreground = self.btn_run.cget("foreground") or ""
                except Exception:
                    self._run_btn_normal_foreground = ""
        except Exception:
            pass

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
        label = getattr(self.serial, "port_label", "") or getattr(self.serial, "port_path", None) or (self.serial.preferred_port or "—")
        self.comm_port_var.set(label)

    def _update_comm_panel_periodic(self):
        self._update_comm_panel_now()
        self.after(self.COMM_UI_MS, self._update_comm_panel_periodic)

    def _send_event(self, event: str, **kw): self.serial.send_json({"event": event, **kw})

    def _send_speed(self, nivel: Optional[str]):
        nivel = (nivel or "medio").lower()
        if nivel not in ("bajo", "medio", "alto"):
            nivel = "medio"
        self.serial.send_json({"event": "speed", "nivel": nivel})

    def _on_serial_json(self, data: Dict) -> None:
        if not isinstance(data, dict):
            return
        payload = dict(data)
        self.after(0, lambda d=payload: self._handle_serial_json(d))

    def _handle_serial_json(self, data: Dict) -> None:
        if not isinstance(data, dict):
            return
        event = data.get("event")
        if event == "door":
            closed_val = data.get("closed")
            closed_state = None if closed_val is None else bool(closed_val)
            self._apply_door_state(closed_state)
        elif data.get("ack") == "door":
            if "lock" in data:
                self.door_locked = bool(data.get("lock"))
            self._sync_door_button_state()
        elif event == "blocked":
            if data.get("reason") == "door_open":
                self.toast("Operación bloqueada: puerta abierta.")
            else:
                self.toast("Operación bloqueada.")

    # configuración global normalizada
    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _globals_cfg(self) -> Dict:
        return self.CFG.setdefault("globals", {})

    def _fill_table(self) -> Dict[str, int]:
        g = self._globals_cfg()
        return {
            "ligero":   self._safe_int(g.get("fill_seconds_ligero", 5), 5),
            "estandar": self._safe_int(g.get("fill_seconds_estandar", 8), 8),
            "intenso":  self._safe_int(g.get("fill_seconds_intenso", 12), 12),
        }

    def _chem_table(self) -> Dict[str, int]:
        g = self._globals_cfg()
        return {
            "Q1": self._safe_int(g.get("chem_seconds_detergente", 4), 4),
            "Q2": self._safe_int(g.get("chem_seconds_quitamanchas", 3), 3),
            "Q3": self._safe_int(g.get("chem_seconds_suavizante", 2), 2),
            "Q4": self._safe_int(g.get("chem_seconds_blanqueador", 2), 2),
        }

    def _drain_table(self) -> Dict[str, int]:
        g = self._globals_cfg()
        return {
            "ligero":   self._safe_int(g.get("drain_seconds_ligero", 20), 20),
            "estandar": self._safe_int(g.get("drain_seconds_estandar", 30), 30),
            "intenso":  self._safe_int(g.get("drain_seconds_intenso", 45), 45),
        }

    def _motor_alt_seconds(self) -> int:
        return self._safe_int(self._globals_cfg().get("motor_alt_seconds", 0), 0)

    # agua/drenaje helpers
    def _action_uses_water(self, accion: str) -> bool:
        a = (accion or "").strip().lower()
        return a in ("prelavado", "lavado", "enjuague")

    def _fill_seconds_for_level(self, level: Optional[str]) -> int:
        g = self._fill_table()
        key = (level or "estandar").strip().lower()
        return g.get(key, g.get("estandar", 8))

    def _drain_seconds_for_level(self, level: Optional[str]) -> int:
        g = self._drain_table()
        key = (level or "estandar").strip().lower()
        return g.get(key, g.get("estandar", 30))

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
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            return

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
        if not (self._latched_cycle and self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD)):
            self.status.config(text=f"Estado actual: {text}")

    def _fmt_secs(self, s:int)->str:
        m,sec = divmod(max(0,s),60); return f"{m}:{sec:02d}"

    def _update_progress(self, total_remaining:int):
        if not self.current_cycle_total:
            self.pb_var.set(0); self.pb_pct.config(text="0%"); return
        done = self.current_cycle_total - total_remaining
        pct = max(0,min(100,int(done*100/self.current_cycle_total)))
        self.pb_var.set(pct); self.pb_pct.config(text=f"{pct}%")

    def _apply_door_state(self, closed: Optional[bool]) -> None:
        state = closed if isinstance(closed, bool) else None
        self.door_state = state
        if state is None:
            self.door_var.set("Puerta: —")
            color = "#95a5a6"
        else:
            self.door_var.set("Puerta: Cerrada" if state else "Puerta: Abierta")
            color = "#27ae60" if state else "#e74c3c"
        try:
            self.lbl_door.configure(foreground=color)
        except Exception:
            pass

        if state is False and self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            self._stop_execution(reason="Paro por puerta abierta")
            try:
                self.toast("⚠ Puerta abierta: ciclo detenido.")
            except Exception:
                messagebox.showwarning("Puerta abierta", "Ciclo detenido por seguridad.")

        self._sync_run_button_state()
        self._sync_door_button_state()

    def _sync_run_button_state(self):
        if not getattr(self, "btn_run", None):
            return
        desired_state = "normal"
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            desired_state = "disabled"
        elif self.door_state is not True or not self.door_locked:
            desired_state = "disabled"
        self.run_btn_text.set(self._run_btn_default_text)
        try:
            self.btn_run.configure(state=desired_state)
        except Exception:
            pass
        try:
            self.btn_run.configure(foreground=self._run_btn_normal_foreground or "")
        except Exception:
            pass

    def _sync_door_button_state(self):
        if not getattr(self, "btn_door", None):
            return
        try:
            self.door_btn_text.set("Desbloquear puerta" if self.door_locked else "Bloquear puerta")
        except Exception:
            pass
        state = "normal"
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            state = "disabled"
        try:
            self.btn_door.configure(state=state)
        except Exception:
            pass

    def _on_tick(self, step_idx:int, step_remaining:int, total_remaining:int):
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            cycle = self._latched_cycle or self.selected_cycle
            total = self._latched_total_steps or (len(cycle.pasos) if cycle else 0)
            step_n = step_idx + 1
            if total <= 0:
                total = max(1, step_n)
            if self.executor.state == Executor.PAUSED:
                label_state = "Pausado"
            elif getattr(self.executor, "in_drain_pause", False):
                label_state = "Drenando"
            else:
                label_state = "Lavando"
            self.status.config(text=f"Estado actual: {label_state} - Paso {step_n} de {total} - Tiempo restante: {self._fmt_secs(total_remaining)}")
        self._update_progress(total_remaining)

    def _on_step_change(self, i:int):
        cycle = self._latched_cycle or self.selected_cycle
        if not cycle: return
        try: s = cycle.pasos[i]
        except IndexError: return
        self.current_cycle_total = cycle.total_duracion
        self.current_step_name.set(f"Paso actual: {s.accion.capitalize()}")

    def _on_finish(self):
        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.pb_var.set(100); self.pb_pct.config(text="100%")
        self.current_step_name.set("—")
        self._latched_cycle = None
        self._latched_total_steps = 0
        self._set_run_ui_lock(False)
        self._sync_run_button_state()
        self._sync_door_button_state()

    def _center_window(self, win: tk.Toplevel) -> None:
        try:
            win.update_idletasks()
            w = win.winfo_reqwidth()
            h = win.winfo_reqheight()
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    # ejecución
    def _start_execution(self):
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            self.toast("Ya hay un ciclo en ejecución."); return
        door_status = self.door_state
        if door_status is not True or not self.door_locked:
            try:
                self.toast("La puerta debe estar cerrada y bloqueada para iniciar el ciclo.")
            except Exception:
                messagebox.showwarning("Puerta abierta", "La puerta debe estar cerrada y bloqueada para iniciar el ciclo.")
            return
        if not self.selected_cycle:
            self.toast("Selecciona un ciclo primero."); return
        self._latched_cycle = self.selected_cycle
        self._latched_total_steps = len(self.selected_cycle.pasos)
        self.executor.load_cycle(self.selected_cycle)
        self.current_cycle_total = self.selected_cycle.total_duracion
        self.executor.start()
        self._set_run_ui_lock(True)
        self._update_progress(self.executor.total_remaining)
        self.btn_run.config(state="disabled")
        self.btn_pause.config(state="normal", text="⏸  Pausar")
        self.btn_stop.config(state="normal")
        self._sync_run_button_state()
        self._sync_door_button_state()

    def _pause_resume(self):
        self.executor.pause()
        if self.executor.state == Executor.PAUSED:
            self.btn_pause.config(text="▶  Reanudar")
        else:
            self.btn_pause.config(text="⏸  Pausar")

    def _stop_execution(self, reason: Optional[str] = None):
        self.executor.stop()
        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.pb_var.set(0); self.pb_pct.config(text="0%"); self.current_step_name.set("—")
        self._latched_cycle = None
        self._latched_total_steps = 0
        self._set_run_ui_lock(False)
        self._sync_run_button_state()
        self._sync_door_button_state()
        if reason:
            try:
                self.status.config(text=f"Estado actual: {reason}")
            except Exception:
                pass

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

        fills = new_fills or {}
        doses = new_doses or {}
        drains = new_drains or {}

        g["fill_seconds_ligero"] = self._safe_int(fills.get("fill_seconds_ligero", g.get("fill_seconds_ligero", 5)), 5)
        g["fill_seconds_estandar"] = self._safe_int(fills.get("fill_seconds_estandar", g.get("fill_seconds_estandar", 8)), 8)
        g["fill_seconds_intenso"] = self._safe_int(fills.get("fill_seconds_intenso", g.get("fill_seconds_intenso", 12)), 12)

        g["chem_seconds_detergente"] = self._safe_int(doses.get("chem_seconds_detergente", g.get("chem_seconds_detergente", 4)), 4)
        g["chem_seconds_quitamanchas"] = self._safe_int(doses.get("chem_seconds_quitamanchas", g.get("chem_seconds_quitamanchas", 3)), 3)
        g["chem_seconds_suavizante"] = self._safe_int(doses.get("chem_seconds_suavizante", g.get("chem_seconds_suavizante", 2)), 2)
        g["chem_seconds_blanqueador"] = self._safe_int(doses.get("chem_seconds_blanqueador", g.get("chem_seconds_blanqueador", 2)), 2)

        g["drain_seconds_ligero"] = self._safe_int(drains.get("drain_seconds_ligero", g.get("drain_seconds_ligero", 20)), 20)
        g["drain_seconds_estandar"] = self._safe_int(drains.get("drain_seconds_estandar", g.get("drain_seconds_estandar", 30)), 30)
        g["drain_seconds_intenso"] = self._safe_int(drains.get("drain_seconds_intenso", g.get("drain_seconds_intenso", 45)), 45)

        g["motor_alt_seconds"] = self._safe_int(alt_seconds, 0)

        # mantener estructura heredada para compatibilidad hacia atrás
        g["water_fill_seconds"] = {
            "ligero": g["fill_seconds_ligero"],
            "estandar": g["fill_seconds_estandar"],
            "intenso": g["fill_seconds_intenso"],
        }
        g["chem_dose_seconds"] = {
            "Q1": g["chem_seconds_detergente"],
            "Q2": g["chem_seconds_quitamanchas"],
            "Q3": g["chem_seconds_suavizante"],
            "Q4": g["chem_seconds_blanqueador"],
        }
        g["drain_seconds"] = {
            "ligero": g["drain_seconds_ligero"],
            "estandar": g["drain_seconds_estandar"],
            "intenso": g["drain_seconds_intenso"],
        }
        g["alternancia_motor_s"] = g["motor_alt_seconds"]

        save_config(CFG)

        if changed:
            busy = BusyDialog(self, "Aplicando configuración y reconectando…")

            def task():
                try:
                    self.serial.stop()
                    self.serial.start()
                finally:
                    self.after(0, lambda: (busy.destroy(), self._update_comm_panel_now(), self.toast("Conexión actualizada.")))

            import threading
            threading.Thread(target=task, daemon=True).start()
        else:
            self._update_comm_panel_now(); self.toast("Configuración guardada.")

    # loop/cierre
    def _loop_logic(self):
        self.executor.tick()
        self.after(self.TICK_MS, self._loop_logic)

    def _set_run_ui_lock(self, locked: bool):
        state = "disabled" if locked else "normal"
        try:
            self.listbox.configure(state=state)
        except Exception:
            pass
        for btn in (getattr(self, "btn_edit", None),
                    getattr(self, "btn_create", None),
                    getattr(self, "btn_delete", None),
                    getattr(self, "btn_settings", None)):
            if btn:
                try:
                    btn.configure(state=state)
                except Exception:
                    pass

    def _toggle_door_lock(self):
        if self.executor.state in (Executor.RUNNING, Executor.PAUSED, Executor.HOLD):
            return
        target = not self.door_locked
        self.serial.send_json({"cmd": "door", "lock": target})

    def _on_comm_connected(self, port: Optional[str]):
        def _cb():
            first = not self._comm_last_state
            self._comm_last_state = True
            self._update_comm_panel_now()
            if first:
                if port:
                    self.toast(f"Conectado a {port}")
                else:
                    self.toast("Dispositivo conectado")
            if hasattr(self.executor, "on_serial_reconnected"):
                self.executor.on_serial_reconnected()
            if self.serial.is_connected():
                self.serial.send_json({"cmd": "door?"})
        self.after(0, _cb)

    def _on_comm_disconnected(self):
        def _cb():
            was_connected = self._comm_last_state
            self._comm_last_state = False
            self._update_comm_panel_now()
            if was_connected:
                self.toast("Dispositivo desconectado")
            self._apply_door_state(None)
        self.after(0, _cb)

    def _on_close(self):
        try:
            self.serial.stop()
        finally:
            self.destroy()


def main():
    try: os.makedirs(CICLOS_DIR, exist_ok=True)
    except Exception: pass
    app = WasherUI(); app.mainloop()

if __name__ == "__main__":
    main()
