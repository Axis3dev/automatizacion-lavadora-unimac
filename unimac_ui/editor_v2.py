# -*- coding: utf-8 -*-
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from typing import Optional, Callable, Dict

try:
    from .models import Step, Cycle
except ImportError:
    from unimac_ui.models import Step, Cycle


# =========================
#   TECLADOS EMBEBIDOS
# =========================
class KeyboardFrame(ttk.Frame):
    """
    Teclado embebido en un contenedor inferior.
    - mode: "text" (QWERTY) o "numeric"
    - Emite <<kb-ok>> al Entry activo al pulsar OK.
    - scale reduce levemente la fuente para 720p (evitar que se corte).
    """
    def __init__(self, master, mode="text", title="Teclado",
                 getter: Optional[Callable[[], Optional[tk.Entry]]] = None,
                 scale: float = 0.95):
        super().__init__(master, padding=4)
        self.mode = mode
        self.getter = getter
        self.shift = False

        base_size = int(14 * scale)
        key_font = tkfont.Font(size=max(12, base_size), weight="bold")

        ttk.Label(self, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        style = ttk.Style(self)
        style.configure("Kb.TButton", font=key_font)

        if mode == "numeric":
            layout = [
                ["7", "8", "9", "⌫"],
                ["4", "5", "6", "Limpiar"],
                ["1", "2", "3", "OK"],
                ["0", "."]
            ]
        else:
            layout = [
                list("1234567890"),
                list("qwertyuiop"),
                list("asdfghjkl"),
                ["⇧"] + list("zxcvbnm") + ["⌫"],
                ["ESPACIO", "Limpiar", "OK"]
            ]

        for row in layout:
            rowf = ttk.Frame(self)
            rowf.pack(fill="x")
            for key in row:
                ttk.Button(rowf, text=key, style="Kb.TButton",
                           command=lambda k=key: self._press(k))\
                    .pack(side="left", padx=3, pady=3, expand=True)

    def _target(self) -> Optional[tk.Entry]:
        return self.getter() if self.getter else None

    def _backspace(self, e: tk.Entry):
        try:
            start = e.index("sel.first"); end = e.index("sel.last")
            e.delete(start, end); return
        except tk.TclError:
            pass
        try:
            pos = e.index("insert")
        except Exception:
            return
        if pos > 0:
            e.delete(pos - 1, pos)

    def _press(self, key: str):
        e = self._target()
        if not isinstance(e, tk.Entry):
            return
        if key == "⌫":
            self._backspace(e); e.focus_set(); return
        if key == "Limpiar":
            e.delete(0, tk.END); e.focus_set(); return
        if key == "ESPACIO":
            e.insert("insert", " "); e.focus_set(); return
        if key == "⇧":
            self.shift = not self.shift; return
        if key == "OK":
            e.event_generate("<<kb-ok>>"); return
        char = key.upper() if (self.mode != "numeric" and self.shift) else key
        e.insert("insert", char); e.focus_set()


# =========================
#   EDITOR TÁCTIL (V2)
# =========================
class TouchCycleEditor(tk.Toplevel):
    ACTIONS = ["prelavado", "lavado", "enjuague", "centrifugado", "drenaje"]
    SPEEDS = ["bajo", "medio", "alto"]
    WATER_LEVELS = [("Ligero", "ligero"), ("Estándar", "estandar"), ("Intenso", "intenso")]
    CHEM_KEYS = [
        ("Detergente", "detergente"),
        ("Quitamanchas", "quitamanchas"),
        ("Suavizante", "suavizante"),
        ("Blanqueador", "blanqueador"),
    ]

    def __init__(self, master, on_save: Callable[[Cycle], None],
                 preload: Optional[Cycle] = None):
        super().__init__(master)
        self.title("Editar / Crear ciclo")
        self.attributes("-fullscreen", True)
        self.on_save = on_save

        # ¿Pantalla 720p?
        self.update_idletasks()
        self.is_720p = (self.winfo_screenheight() <= 720)

        # Estado UI
        self.active_entry = None  # type: Optional[tk.Entry]
        self.current_step_index = None  # type: Optional[int]
        self.temp_var = tk.StringVar(value=getattr(preload, "agua_temp", "fria") if preload else "fria")
        self.nombre_var = tk.StringVar(value=getattr(preload, "nombre", ""))

        # Modelo en edición (copia)
        self.working_cycle = Cycle(nombre=self.nombre_var.get().strip() or "Ciclo")
        self.working_cycle.pasos = []
        if preload:
            for p in preload.pasos:
                d = dict(
                    accion=getattr(p, "accion", "lavado"),
                    duracion=int(getattr(p, "duracion", 0)),
                    nivel_agua=getattr(p, "nivel_agua", "") or "",
                    quimicos=list(getattr(p, "quimicos", []) or []),
                    velocidad=getattr(p, "velocidad", None),
                )
                self.working_cycle.pasos.append(self._mk_step_obj(d))

        # Fuentes
        self.f_title = tkfont.Font(size=20, weight="bold")
        self.f_label = tkfont.Font(size=16, weight="bold")
        self.f_field = tkfont.Font(size=14)
        self.f_btn = tkfont.Font(size=16, weight="bold")
        self.f_list = tkfont.Font(size=20)

        # ---- Layout general ----
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True)

        # Barra superior (nombre + temperatura)
        top = ttk.Frame(root); top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Nombrar ciclo:", font=self.f_label).pack(side="left")
        self.name_entry = ttk.Entry(top, textvariable=self.nombre_var, font=self.f_field, width=34)
        self.name_entry.pack(side="left", padx=(6, 16))
        self.name_entry.bind("<FocusIn>", lambda e: self._show_keyboard("alpha", self.name_entry))
        self.name_entry.bind("<<kb-ok>>", lambda e: self._hide_keyboards())

        ttk.Label(top, text="Agua:", font=self.f_label).pack(side="left")
        tfr = ttk.Frame(top); tfr.pack(side="left", padx=(6, 16))
        ttk.Radiobutton(tfr, text="Fría", value="fria", variable=self.temp_var).pack(side="left", padx=6)
        ttk.Radiobutton(tfr, text="Caliente", value="caliente", variable=self.temp_var).pack(side="left", padx=6)

        # Botones rápidos para agregar pasos
        tpl = ttk.Frame(root); tpl.pack(fill="x", pady=(0, 8))
        ttk.Label(tpl, text="Agregar:", font=self.f_label).pack(side="left", padx=(0, 8))
        ttk.Button(tpl, text="+ Prelavado",   command=lambda: self._add_step("prelavado", 2)).pack(side="left", padx=2)
        ttk.Button(tpl, text="+ Lavado",      command=lambda: self._add_step("lavado", 10)).pack(side="left", padx=2)
        ttk.Button(tpl, text="+ Enjuague",    command=lambda: self._add_step("enjuague", 5)).pack(side="left", padx=2)
        ttk.Button(tpl, text="+ Centrifugado",command=lambda: self._add_step("centrifugado", 3)).pack(side="left", padx=2)
        ttk.Button(tpl, text="+ Drenaje",     command=lambda: self._add_step("drenaje", 1)).pack(side="left", padx=2)

        # Cuerpo recortado (reserva espacio al teclado)
        body = ttk.Frame(root); body.pack(fill="x", expand=False)
        if self.is_720p:
            h = int(self.winfo_screenheight() * 0.56)
            body.configure(height=h); body.pack_propagate(False)

        # Izquierda: lista + flechas
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        ttk.Label(left, text="Pasos", font=self.f_label).pack(anchor="w", pady=(0, 6))

        listrow = ttk.Frame(left); listrow.pack(fill="both", expand=True)
        self.lst_steps = tk.Listbox(listrow, exportselection=False, font=self.f_list, height=8 if self.is_720p else 12)
        self.lst_steps.grid(row=0, column=0, sticky="nsew")
        self.lst_steps.bind("<<ListboxSelect>>", self._on_list_select)

        arrows = ttk.Frame(listrow); arrows.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        up = ttk.Button(arrows, text="▲", command=lambda: self._scroll(-3), width=3)
        dn = ttk.Button(arrows, text="▼", command=lambda: self._scroll(3), width=3)
        up.pack(fill="y", expand=True, pady=(0, 6)); dn.pack(fill="y", expand=True)
        up.bind("<ButtonPress-1>",   lambda e: self._scroll_hold(-3))
        dn.bind("<ButtonPress-1>",   lambda e: self._scroll_hold( 3))
        up.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        dn.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        listrow.columnconfigure(0, weight=1); listrow.rowconfigure(0, weight=1)

        # Derecha: editor + químicos + botones Guardar/Cancelar
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Editor del paso", font=self.f_label).pack(anchor="w", pady=(0, 6))
        self.step_frame = ttk.Frame(right); self.step_frame.pack(fill="x", expand=False)
        self.chem_frame = ttk.LabelFrame(right, text="Químicos"); self.chem_frame.pack(fill="x", expand=False, pady=(6, 8))

        actions_row = ttk.Frame(right); actions_row.pack(fill="x", pady=(6, 0))
        ttk.Button(actions_row, text="Cancelar", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(actions_row, text="Guardar ciclo", command=self._save).pack(side="right")

        # Contenedor FIJO para el teclado (siempre reserva espacio)
        self.kb_container = ttk.Frame(root); self.kb_container.pack(fill="x", pady=(10, 0))
        self.kb_container.pack_propagate(False)
        kb_h = int(self.winfo_screenheight() * (0.36 if self.is_720p else 0.30))
        self.kb_container.configure(height=kb_h)

        kb_scale = 0.90 if self.is_720p else 0.95
        self.kb_alpha = KeyboardFrame(self.kb_container, mode="text",
                                      getter=lambda: self.active_entry, scale=kb_scale)
        self.kb_num   = KeyboardFrame(self.kb_container, mode="numeric",
                                      getter=lambda: self.active_entry, scale=kb_scale)
        self.kb_visible = None  # 'alpha' / 'num' / None

        # Inicializar lista
        self._refresh_steps_list()
        if self.lst_steps.size() > 0:
            self.lst_steps.selection_set(0)
            self.current_step_index = 0
            self._render_selected()

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    # ---------- utilidades UI ----------
    def _show_keyboard(self, which: str, entry: tk.Entry):
        self.active_entry = entry
        for w in self.kb_container.winfo_children():
            w.pack_forget()
        if which == "alpha":
            self.kb_alpha.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.kb_visible = "alpha"
        else:
            self.kb_num.pack(side="left", fill="x", expand=True)
            self.kb_visible = "num"

    def _hide_keyboards(self):
        for w in self.kb_container.winfo_children():
            w.pack_forget()
        self.kb_visible = None
        self.active_entry = None

    def _scroll(self, units):
        self.lst_steps.yview_scroll(units, "units")

    def _scroll_hold(self, units):
        self._scroll(units)
        self._hold_job = self.after(120, lambda: self._scroll_hold(units))

    def _scroll_release(self):
        if hasattr(self, "_hold_job") and self._hold_job:
            self.after_cancel(self._hold_job); self._hold_job = None

    # ---------- helpers de modelo ----------
    def _mk_step_obj(self, d: Dict) -> Step:
        accion = d.get("accion", "lavado")
        s = Step(accion=accion, duracion=int(d.get("duracion", 0)))
        setattr(s, "nivel_agua", d.get("nivel_agua", "") or "")
        setattr(s, "quimicos", list(d.get("quimicos", []) or []))
        vel_raw = d.get("velocidad", None)
        if accion in ("prelavado", "lavado", "enjuague", "centrifugado"):
            setattr(s, "velocidad", vel_raw or "medio")
        else:
            setattr(s, "velocidad", vel_raw if vel_raw else None)
        return s

    def _lb_text(self, i: int) -> str:
        s = self.working_cycle.pasos[i]
        acc = getattr(s, "accion", "?").capitalize()
        mins = int(getattr(s, "duracion", 0)) // 60
        extra = ""
        if getattr(s, "velocidad", None):
            extra = f" [{getattr(s, 'velocidad').capitalize()}]"
        return f"{i+1}. {acc} ({mins} min){extra}"

    def _refresh_steps_list(self):
        self.lst_steps.delete(0, "end")
        for i in range(len(self.working_cycle.pasos)):
            self.lst_steps.insert("end", self._lb_text(i))

    # ---------- selección en la lista ----------
    def _on_list_select(self, *_):
        sel = self.lst_steps.curselection()
        self.current_step_index = sel[0] if sel else None
        self._render_selected()

    # ---------- render de editor/químicos ----------
    def _render_selected(self):
        for w in self.step_frame.winfo_children(): w.destroy()
        for w in self.chem_frame.winfo_children(): w.destroy()
        idx = self.current_step_index
        if idx is None or idx < 0 or idx >= len(self.working_cycle.pasos): return
        s = self.working_cycle.pasos[idx]

        # Acción
        row1 = ttk.Frame(self.step_frame); row1.pack(fill="x", pady=(0, 6))
        ttk.Label(row1, text="Acción:", font=self.f_label).pack(side="left")
        cb = ttk.Combobox(row1, values=self.ACTIONS, state="readonly", width=16, font=self.f_field)
        cb.set(getattr(s, "accion", "lavado"))
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda e, i=idx, cb=cb: self._set_action(i, cb.get()))

        # Minutos
        row2 = ttk.Frame(self.step_frame); row2.pack(fill="x", pady=(0, 6))
        ttk.Label(row2, text="Minutos:", font=self.f_label).pack(side="left")
        e_min = ttk.Entry(row2, width=8, font=self.f_field)
        e_min.insert(0, str(max(0, int(getattr(s, "duracion", 0)) // 60)))
        e_min.pack(side="left", padx=(6, 16))
        e_min.bind("<FocusIn>", lambda e, ent=e_min: self._show_keyboard("num", ent))
        e_min.bind("<<kb-ok>>", lambda e, i=idx, ent=e_min: self._commit_minutes(i, ent))

        # Nivel de agua
        lvl_row = ttk.Frame(self.step_frame); lvl_row.pack(fill="x", pady=(0, 6))
        ttk.Label(lvl_row, text="Nivel de agua:", font=self.f_label).pack(side="left")
        lvl_var = tk.StringVar(value=getattr(s, "nivel_agua", "") or "")
        self._lvl_buttons = []
        for txt, val in self.WATER_LEVELS:
            rb = ttk.Radiobutton(lvl_row, text=txt, value=val, variable=lvl_var,
                                 command=lambda i=idx, v=lvl_var: self._set_level(i, v.get()))
            rb.pack(side="left", padx=6)
            self._lvl_buttons.append(rb)

        # Velocidad (para pasos con giro)
        self.spd_row = ttk.Frame(self.step_frame)
        if getattr(s, "accion", "") in ("prelavado", "lavado", "enjuague", "centrifugado"):
            self.spd_row.pack(fill="x", pady=(0, 6))
            ttk.Label(self.spd_row, text="Velocidad:", font=self.f_label).pack(side="left")
            spd_var = tk.StringVar(value=getattr(s, "velocidad", "medio") or "medio")
            for v in self.SPEEDS:
                ttk.Radiobutton(self.spd_row, text=v.capitalize(), value=v, variable=spd_var,
                                command=lambda i=idx, vv=spd_var: self._set_speed(i, vv.get())
                                ).pack(side="left", padx=6)

        # Enjuague final (activa suavizante)
        self.final_row = ttk.Frame(self.step_frame)
        if getattr(s, "accion", "") == "enjuague":
            self.final_row.pack(fill="x", pady=(0, 6))
            is_final = "suavizante" in (getattr(s, "quimicos", []) or [])
            fin_var = tk.BooleanVar(value=is_final)
            ttk.Checkbutton(self.final_row, text="Enjuague final (permite Suavizante)",
                            variable=fin_var,
                            command=lambda i=idx, v=fin_var: self._toggle_final(i, v.get())
                            ).pack(side="left")

        # Químicos
        ttk.Label(self.chem_frame, text="Selecciona químicos válidos para esta acción:",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        grid = ttk.Frame(self.chem_frame); grid.pack(fill="x", padx=6, pady=(0, 6))
        self.chem_vars = {}   # type: Dict[str, tk.BooleanVar]
        self.chem_checks = {} # type: Dict[str, ttk.Checkbutton]
        for col, (label, key) in enumerate(self.CHEM_KEYS):
            var = tk.BooleanVar(value=(key in (getattr(s, "quimicos", []) or [])))
            chk = ttk.Checkbutton(grid, text=label, variable=var,
                                  command=lambda k=key: self._chem_clicked(idx, k))
            chk.grid(row=0, column=col, sticky="w", padx=(0, 18))
            self.chem_vars[key] = var
            self.chem_checks[key] = chk

        self._apply_chem_rules_for_step(idx)

        # Eliminar paso (SIN confirmación)
        row3 = ttk.Frame(self.step_frame); row3.pack(fill="x", pady=(8, 0))
        ttk.Button(row3, text="Eliminar este paso",
                   command=self._delete_selected_step).pack(side="left")

        # Deshabilitar nivel de agua si no aplica
        if getattr(s, "accion", "") in ("centrifugado", "drenaje"):
            for rb in getattr(self, "_lvl_buttons", []):
                rb.state(["disabled"])

    # ---------- eventos de edición ----------
    def _set_action(self, idx: int, accion: str):
        s = self.working_cycle.pasos[idx]
        setattr(s, "accion", accion)
        if accion == "centrifugado":
            if not getattr(s, "velocidad", None):
                setattr(s, "velocidad", "medio")
            setattr(s, "nivel_agua", "")
        elif accion in ("prelavado", "lavado", "enjuague"):
            if not getattr(s, "velocidad", None):
                setattr(s, "velocidad", "medio")
            if not getattr(s, "nivel_agua", ""):
                setattr(s, "nivel_agua", "estandar")
        else:
            setattr(s, "velocidad", None)
            if accion not in ("centrifugado", "drenaje") and not getattr(s, "nivel_agua", ""):
                setattr(s, "nivel_agua", "estandar")

        qs = set(getattr(s, "quimicos", []) or [])
        s.quimicos = list(self._sanitize_quimicos(accion, qs, is_final=("suavizante" in qs)))
        self._refresh_steps_list(); self._render_selected()

    def _commit_minutes(self, idx: int, ent: tk.Entry):
        try:
            mins = max(0, int(float(ent.get())))
        except Exception:
            messagebox.showerror("Valor inválido", "Minutos deben ser numéricos.")
            return
        s = self.working_cycle.pasos[idx]
        setattr(s, "duracion", int(mins) * 60)
        self._refresh_steps_list()
        self._hide_keyboards()

    def _set_level(self, idx: int, lvl: str):
        s = self.working_cycle.pasos[idx]
        if getattr(s, "accion", "") in ("centrifugado", "drenaje"):
            setattr(s, "nivel_agua", "")
        else:
            setattr(s, "nivel_agua", lvl)

    def _set_speed(self, idx: int, spd: str):
        s = self.working_cycle.pasos[idx]
        if getattr(s, "accion", "") in ("prelavado", "lavado", "enjuague", "centrifugado"):
            setattr(s, "velocidad", spd)
            self._refresh_steps_list()

    def _toggle_final(self, idx: int, is_final: bool):
        s = self.working_cycle.pasos[idx]
        qs = set(getattr(s, "quimicos", []) or [])
        if getattr(s, "accion", "") == "enjuague":
            if is_final:
                qs.add("suavizante")
            else:
                qs.discard("suavizante")
        setattr(s, "quimicos", list(qs))
        self._apply_chem_rules_for_step(idx)
        self._refresh_steps_list()

    def _delete_selected_step(self):
        """Elimina el paso seleccionado sin pedir confirmación."""
        idx = self.current_step_index
        if idx is None:
            sel = self.lst_steps.curselection()
            idx = sel[0] if sel else None
        if idx is None or idx < 0 or idx >= len(self.working_cycle.pasos):
            return
        del self.working_cycle.pasos[idx]
        self._refresh_steps_list()
        if self.working_cycle.pasos:
            new_idx = min(idx, len(self.working_cycle.pasos) - 1)
            self.lst_steps.selection_clear(0, "end")
            self.lst_steps.selection_set(new_idx)
            self.current_step_index = new_idx
            self.lst_steps.event_generate("<<ListboxSelect>>")
        else:
            self.current_step_index = None
            for w in self.step_frame.winfo_children(): w.destroy()
            for w in self.chem_frame.winfo_children(): w.destroy()

    # ---------- reglas de químicos ----------
    def _allowed_by_action(self, accion: str, is_final: bool) -> Dict[str, bool]:
        allowed = {k: False for _, k in self.CHEM_KEYS}
        if accion == "prelavado":
            allowed["detergente"] = True
            allowed["quitamanchas"] = True
        elif accion == "lavado":
            allowed["detergente"] = True
            allowed["quitamanchas"] = True
            allowed["blanqueador"] = True
        elif accion == "enjuague":
            allowed["suavizante"] = bool(is_final)
        # drenaje/centrifugado: ninguno
        return allowed

    def _sanitize_quimicos(self, accion: str, qs: set, is_final: bool) -> set:
        allowed = self._allowed_by_action(accion, is_final)
        new = {q for q in qs if allowed.get(q, False)}
        if accion in ("prelavado", "lavado"):
            new.add("detergente")
        if "blanqueador" in new and "quitamanchas" in new:
            new.discard("quitamanchas")
        if accion == "enjuague" and is_final:
            new.add("suavizante")
        return new

    def _apply_chem_rules_for_step(self, idx: int):
        s = self.working_cycle.pasos[idx]
        accion = getattr(s, "accion", "lavado")
        is_final = "suavizante" in (getattr(s, "quimicos", []) or [])
        allowed = self._allowed_by_action(accion, is_final)

        for key, chk in self.chem_checks.items():
            if allowed.get(key, False):
                chk.state(["!disabled"])
            else:
                chk.state(["disabled"])
                if key in (getattr(s, "quimicos", []) or []):
                    self.chem_vars[key].set(False)

        qs = set(getattr(s, "quimicos", []) or [])
        qs = self._sanitize_quimicos(accion, qs, is_final)
        setattr(s, "quimicos", list(qs))
        for key, var in self.chem_vars.items():
            var.set(key in qs)

    def _chem_clicked(self, idx: int, key: str):
        s = self.working_cycle.pasos[idx]
        accion = getattr(s, "accion", "lavado")
        is_final = "suavizante" in (getattr(s, "quimicos", []) or [])
        allowed = self._allowed_by_action(accion, is_final)
        if not allowed.get(key, False):
            self.chem_vars[key].set(False); return

        qs = set(getattr(s, "quimicos", []) or [])
        if self.chem_vars[key].get():
            qs.add(key)
            if key == "blanqueador" and "quitamanchas" in qs:
                qs.discard("quitamanchas"); self.chem_vars["quitamanchas"].set(False)
            if key == "quitamanchas" and "blanqueador" in qs:
                qs.discard("blanqueador"); self.chem_vars["blanqueador"].set(False)
        else:
            qs.discard(key)

        if accion in ("prelavado", "lavado"):
            qs.add("detergente"); self.chem_vars["detergente"].set(True)
        if accion == "enjuague" and is_final:
            qs.add("suavizante"); self.chem_vars["suavizante"].set(True)

        setattr(s, "quimicos", list(qs))
        self._refresh_steps_list()

    # ---------- añadir pasos ----------
    def _add_step(self, accion: str, mins: int):
        d = dict(accion=accion, duracion=int(mins) * 60,
                 nivel_agua=("estandar" if accion not in ("centrifugado", "drenaje") else ""))
        if accion in ("prelavado", "lavado", "enjuague", "centrifugado"):
            d["velocidad"] = "medio"
        qs = set()
        if accion in ("prelavado", "lavado"):
            qs.add("detergente")
        d["quimicos"] = list(qs)

        s = self._mk_step_obj(d)
        self.working_cycle.pasos.append(s)
        self._refresh_steps_list()
        self.lst_steps.selection_clear(0, "end")
        self.lst_steps.selection_set("end")
        self.lst_steps.see("end")
        self.current_step_index = self.lst_steps.size() - 1
        self._render_selected()

    # ---------- guardar / cancelar ----------
    def _save(self):
        nombre = self.nombre_var.get().strip() or "Ciclo"
        ciclo = Cycle(nombre=nombre, pasos=list(self.working_cycle.pasos))
        setattr(ciclo, "agua_temp", self.temp_var.get())
        self.on_save(ciclo)
        self.destroy()

    def _cancel(self):
        """Cierra el editor sin confirmación."""
        try:
            self._hide_keyboards()
        except Exception:
            pass
        self.destroy()
