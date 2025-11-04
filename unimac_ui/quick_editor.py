# -*- coding: utf-8 -*-
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from typing import Callable, Optional, List, Dict

try:
    from .models import Step, Cycle
except ImportError:
    from unimac_ui.models import Step, Cycle

# =============== Teclados simples ===============
class KeyboardFrame(ttk.Frame):
    def __init__(self, master, mode="text", title="Teclado", getter=None):
        super().__init__(master, padding=4)
        ttk.Label(self, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.mode = mode
        self.getter = getter
        self.shift = False
        key_font = tkfont.Font(size=14, weight="bold")
        style = ttk.Style(self); style.configure("Kb.TButton", font=key_font)

        if mode == "numeric":
            layout = [["7","8","9","⌫"],
                      ["4","5","6","Limpiar"],
                      ["1","2","3","OK"],
                      ["0","."]]
        else:
            layout = [
                list("1234567890"),
                list("qwertyuiop"),
                list("asdfghjkl"),
                ["⇧"] + list("zxcvbnm") + ["⌫"],
                ["ESPACIO","Limpiar","OK"]
            ]

        for row in layout:
            rowf = ttk.Frame(self); rowf.pack(fill="x")
            for key in row:
                ttk.Button(rowf, text=key, style="Kb.TButton",
                           command=lambda k=key: self._press(k)).pack(side="left", padx=3, pady=3, expand=True)

    def _target(self) -> Optional[tk.Entry]:
        return self.getter() if self.getter else None

    def _backspace(self, e: tk.Entry):
        try:
            start=e.index("sel.first"); end=e.index("sel.last"); e.delete(start,end); return
        except tk.TclError:
            pass
        try:
            pos=e.index("insert")
        except Exception:
            return
        if pos>0: e.delete(pos-1,pos)

    def _press(self, key: str):
        e = self._target()
        if not isinstance(e, tk.Entry): return
        if key=="⌫": self._backspace(e); e.focus_set(); return
        if key=="Limpiar": e.delete(0, tk.END); e.focus_set(); return
        if key=="ESPACIO": e.insert("insert", " "); e.focus_set(); return
        if key=="⇧": self.shift = not self.shift; return
        if key=="OK": e.event_generate("<<kb-ok>>"); return
        char = key.upper() if (self.mode!="numeric" and self.shift) else key
        e.insert("insert", char); e.focus_set()


# =============== Creador Rápido de Ciclos ===============
class QuickCycleWizard(tk.Toplevel):
    """
    Creador rápido: pasos con ACCIÓN + MINUTOS + (opcional) VELOCIDAD + QUÍMICOS por acción.
    Reglas:
      - Prelavado: Detergente/Quitamanchas (no Suavizante/Blanqueador).
      - Lavado: Detergente + (Quitamanchas o Blanqueador, excluyentes).
      - Enjuague: Suavizante SOLO si 'Enjuague final' está activo.
      - Centrifugado/Drenaje: sin químicos.
      - Nivel de agua por defecto: 'estandar' salvo centrifugado/drenaje (sin agua).
    """
    ACTIONS = ["prelavado", "lavado", "enjuague", "centrifugado", "drenaje"]
    SPEEDS  = ["bajo", "medio", "alto"]
    CHEM_KEYS = [
        ("Detergente",   "detergente"),
        ("Quitamanchas", "quitamanchas"),
        ("Suavizante",   "suavizante"),
        ("Blanqueador",  "blanqueador"),
    ]

    def __init__(self, master, on_save: Callable[[Cycle], None]):
        super().__init__(master)
        self.title("Creador rápido – Nuevo ciclo")
        self.attributes("-fullscreen", True)
        self.on_save = on_save

        # Estado
        self.active_entry: Optional[tk.Entry] = None
        # Cada paso: {"accion":str, "min":int, "velocidad":str?, "rinse_final":bool, "quimicos":set()}
        self.steps: List[Dict] = []
        self.nombre_var = tk.StringVar(value="")
        self.temp_var = tk.StringVar(value="fria")

        # Fuentes
        self.f_title = tkfont.Font(size=20, weight="bold")
        self.f_label = tkfont.Font(size=14, weight="bold")
        self.f_field = tkfont.Font(size=13)
        self.f_btn   = tkfont.Font(size=16, weight="bold")
        self.f_list  = tkfont.Font(size=18)

        # Layout
        root = ttk.Frame(self, padding=12); root.pack(fill="both", expand=True)

        top = ttk.Frame(root); top.pack(fill="x", pady=(0,10))
        ttk.Label(top, text="Nombrar ciclo:", font=self.f_label).pack(side="left")
        self.name_entry = ttk.Entry(top, textvariable=self.nombre_var, font=self.f_field, width=32)
        self.name_entry.pack(side="left", padx=(6,16))
        self.name_entry.bind("<FocusIn>", lambda e: self._set_active(self.name_entry, "alpha"))

        ttk.Label(top, text="Agua:", font=self.f_label).pack(side="left")
        tfr = ttk.Frame(top); tfr.pack(side="left", padx=(6,16))
        for lbl, val in (("Fría","fria"),("Caliente","caliente")):
            ttk.Radiobutton(tfr, text=lbl, value=val, variable=self.temp_var).pack(side="left", padx=6)

        # Plantillas rápidas
        tpl = ttk.Frame(root); tpl.pack(fill="x", pady=(0,8))
        ttk.Label(tpl, text="Plantillas:", font=self.f_label).pack(side="left", padx=(0,8))
        ttk.Button(tpl, text="Rápido", command=lambda: self._apply_template("rapido")).pack(side="left", padx=4)
        ttk.Button(tpl, text="Estándar", command=lambda: self._apply_template("estandar")).pack(side="left", padx=4)
        ttk.Button(tpl, text="Industrial", command=lambda: self._apply_template("industrial")).pack(side="left", padx=4)

        body = ttk.Frame(root); body.pack(fill="both", expand=True)

        # Izquierda: lista + botones añadir
        left = ttk.Frame(body); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        ttk.Label(left, text="Pasos (simple)", font=self.f_label).pack(anchor="w", pady=(0,6))

        addrow = ttk.Frame(left); addrow.pack(fill="x", pady=(0,6))
        ttk.Button(addrow, text="+ Prelavado", command=lambda: self._add_step("prelavado", 2)).pack(side="left", padx=2)
        ttk.Button(addrow, text="+ Lavado", command=lambda: self._add_step("lavado", 10)).pack(side="left", padx=2)
        ttk.Button(addrow, text="+ Enjuague", command=lambda: self._add_step("enjuague", 5)).pack(side="left", padx=2)
        ttk.Button(addrow, text="+ Centrifugado", command=lambda: self._add_step("centrifugado", 3)).pack(side="left", padx=2)
        ttk.Button(addrow, text="+ Drenaje", command=lambda: self._add_step("drenaje", 1)).pack(side="left", padx=2)

        listrow = ttk.Frame(left); listrow.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(listrow, exportselection=False, height=14, font=self.f_list)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        arrows = ttk.Frame(listrow); arrows.grid(row=0, column=1, sticky="ns", padx=(6,0))
        ttk.Button(arrows, text="▲", command=lambda: self._scroll(-3), width=3).pack(fill="x", pady=(0,6))
        ttk.Button(arrows, text="▼", command=lambda: self._scroll( 3), width=3).pack(fill="x")
        listrow.columnconfigure(0, weight=1); listrow.rowconfigure(0, weight=1)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._render_selected())

        # Derecha: editor del paso + QUÍMICOS
        right = ttk.Frame(body); right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Editor del paso (simple)", font=self.f_label).pack(anchor="w", pady=(0,6))
        self.step_frame = ttk.Frame(right); self.step_frame.pack(fill="x", expand=False, pady=(0,6))
        self.chem_frame = ttk.LabelFrame(right, text="Químicos"); self.chem_frame.pack(fill="x", expand=False)

        # Abajo: teclados + acciones
        kbrow = ttk.Frame(root); kbrow.pack(fill="x", pady=(10,0))
        self.kb_alpha = KeyboardFrame(kbrow, mode="text", getter=lambda: self.active_entry)
        self.kb_num   = KeyboardFrame(kbrow, mode="numeric", getter=lambda: self.active_entry)
        self.kb_alpha.pack(side="left", fill="x", expand=True, padx=(0,8))
        self.kb_num.pack(side="left", fill="x", expand=True)

        bot = ttk.Frame(root); bot.pack(fill="x", pady=(8,0))
        ttk.Button(bot, text="Cancelar", command=self.destroy).pack(side="right", padx=(8,0))
        ttk.Button(bot, text="Guardar ciclo", command=self._save).pack(side="right")

        # arranque: una plantilla básica
        self._apply_template("estandar")

    # ------- helpers -------
    def _set_active(self, entry: tk.Entry, which: str):
        self.active_entry = entry
        if which == "alpha":
            self.kb_alpha.lift(); self.kb_num.lower()
        else:
            self.kb_num.lift(); self.kb_alpha.lower()

    def _scroll(self, units):
        self.listbox.yview_scroll(units, "units")

    def _lb_text(self, i: int) -> str:
        s = self.steps[i]
        acc = s["accion"].capitalize()
        mins = s["min"]
        suffix = ""
        if s["accion"] == "enjuague" and s.get("rinse_final"):
            suffix = " (final)"
        if s["accion"] == "centrifugado" and s.get("velocidad"):
            suffix += f" [{s['velocidad']}]"
        return f"{i+1}. {acc} ({mins} min){suffix}"

    def _refresh_lb(self):
        self.listbox.delete(0, "end")
        for i in range(len(self.steps)):
            self.listbox.insert("end", self._lb_text(i))

    # ------- plantillas -------
    def _apply_template(self, name: str):
        self.steps.clear()
        if name == "rapido":
            base = [
                {"accion":"prelavado","min":2},
                {"accion":"lavado","min":8},
                {"accion":"enjuague","min":4},
                {"accion":"centrifugado","min":3,"velocidad":"alto"},
            ]
        elif name == "industrial":
            base = [
                {"accion":"prelavado","min":4},
                {"accion":"lavado","min":15},
                {"accion":"enjuague","min":5},
                {"accion":"enjuague","min":5},
                {"accion":"centrifugado","min":4,"velocidad":"alto"},
            ]
        else:  # estandar
            base = [
                {"accion":"prelavado","min":3},
                {"accion":"lavado","min":12},
                {"accion":"enjuague","min":5},
                {"accion":"enjuague","min":5},
                {"accion":"centrifugado","min":4,"velocidad":"medio"},
            ]

        # defaults químicos por acción
        self.steps = []
        last_rinse_idx = max([i for i,s in enumerate(base) if s["accion"]=="enjuague"], default=-1)
        for i, s in enumerate(base):
            d = dict(s)
            d["rinse_final"] = (s["accion"]=="enjuague" and i==last_rinse_idx)
            d["quimicos"] = set()
            if s["accion"] in ("prelavado","lavado"):
                d["quimicos"].add("detergente")
            if s["accion"]=="enjuague" and d["rinse_final"]:
                d["quimicos"].add("suavizante")
            self.steps.append(d)

        self._refresh_lb()
        if self.listbox.size():
            self.listbox.selection_clear(0,"end")
            self.listbox.selection_set(0)
            self._render_selected()

    # ------- pasos -------
    def _add_step(self, accion: str, minutos: int):
        d = {"accion":accion, "min":minutos, "rinse_final":False, "quimicos":set()}
        if accion == "centrifugado":
            d["velocidad"] = "alto"
        if accion in ("prelavado","lavado"):
            d["quimicos"].add("detergente")
        self.steps.append(d)
        # si es enjuague y es el único, márcalo final por comodidad
        if accion=="enjuague" and not any(s["accion"]=="enjuague" and s.get("rinse_final") for s in self.steps):
            d["rinse_final"] = True
            d["quimicos"].add("suavizante")
        self._refresh_lb()
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set("end")
        self.listbox.see("end")
        self._render_selected()

    def _render_selected(self):
        # limpiar UI
        for w in self.step_frame.winfo_children(): w.destroy()
        for w in self.chem_frame.winfo_children(): w.destroy()
        sel = self.listbox.curselection()
        if not sel: return
        i = sel[0]; s = self.steps[i]

        # --- Editor simple del paso ---
        row1 = ttk.Frame(self.step_frame); row1.pack(fill="x", pady=(0,6))
        ttk.Label(row1, text="Acción:", font=("Segoe UI", 13, "bold")).pack(side="left")
        cb = ttk.Combobox(row1, values=self.ACTIONS, width=16, state="readonly")
        cb.set(s["accion"])
        cb.pack(side="left", padx=(6,16))
        cb.bind("<<ComboboxSelected>>", lambda e,i=i,cb=cb: self._set_action(i, cb.get()))

        row2 = ttk.Frame(self.step_frame); row2.pack(fill="x", pady=(0,6))
        ttk.Label(row2, text="Minutos:", font=("Segoe UI", 13, "bold")).pack(side="left")
        e_min = ttk.Entry(row2, width=8)
        e_min.insert(0, str(s["min"]))
        e_min.pack(side="left", padx=(6,16))
        e_min.bind("<FocusIn>", lambda e: self._set_active(e_min, "num"))
        e_min.bind("<<kb-ok>>", lambda e,i=i,ent=e_min: self._commit_minutes(i, ent))

        # Velocidad solo si centrifugado
        self.spd_row = ttk.Frame(self.step_frame)
        if s["accion"] == "centrifugado":
            self.spd_row.pack(fill="x", pady=(0,6))
            ttk.Label(self.spd_row, text="Velocidad:", font=("Segoe UI", 13, "bold")).pack(side="left")
            spd = ttk.Combobox(self.spd_row, values=self.SPEEDS, width=10, state="readonly")
            spd.set(s.get("velocidad","alto"))
            spd.pack(side="left", padx=(6,16))
            spd.bind("<<ComboboxSelected>>", lambda e,i=i,cb=spd: self._set_speed(i, cb.get()))

        # Enjuague final (solo visible si acción=enjuague)
        self.final_row = ttk.Frame(self.step_frame)
        if s["accion"]=="enjuague":
            self.final_row.pack(fill="x", pady=(0,6))
            fin_var = tk.BooleanVar(value=s.get("rinse_final", False))
            chk = ttk.Checkbutton(self.final_row, text="Enjuague final (permite Suavizante)", variable=fin_var,
                                  command=lambda i=i,v=fin_var: self._toggle_final(i, v.get()))
            chk.pack(side="left")

        # --- Químicos (debajo) ---
        ttk.Label(self.chem_frame, text="Selecciona químicos válidos para esta acción:",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6,2))

        grid = ttk.Frame(self.chem_frame); grid.pack(fill="x", padx=6, pady=(0,6))
        self.chem_vars: Dict[str, tk.BooleanVar] = {}
        self.chem_checks: Dict[str, ttk.Checkbutton] = {}

        def mk_cmd(key:str):
            return (lambda k=key: self._chem_clicked(i, k))

        col = 0
        for label, key in self.CHEM_KEYS:
            var = tk.BooleanVar(value=(key in s["quimicos"]))
            chk = ttk.Checkbutton(grid, text=label, variable=var, command=mk_cmd(key))
            chk.grid(row=0, column=col, sticky="w", padx=(0,18))
            self.chem_vars[key] = var
            self.chem_checks[key] = chk
            col += 1

        # Aplicar reglas de habilitado/inhabilitado según acción
        self._apply_chem_rules_for_step(i)

        # Botón eliminar paso
        row3 = ttk.Frame(self.step_frame); row3.pack(fill="x", pady=(8,0))
        ttk.Button(row3, text="Eliminar este paso",
                   command=lambda i=i: self._delete_step(i)).pack(side="left")

    # ------- Reglas/acciones -------
    def _set_action(self, idx: int, accion: str):
        s = self.steps[idx]
        s["accion"] = accion
        # reset velocidad si cambia a/desde centrifugado
        if accion == "centrifugado":
            s["velocidad"] = s.get("velocidad","alto")
        else:
            s.pop("velocidad", None)
        # reset enjuague final si no es enjuague
        if accion != "enjuague":
            s["rinse_final"] = False
        # limpiar químicos fuera de regla, re-agregar defaults
        s["quimicos"] = self._sanitize_quimicos(accion, s.get("rinse_final", False), s.get("quimicos", set()))
        self._refresh_lb()
        self._render_selected()

    def _commit_minutes(self, idx: int, ent: tk.Entry):
        try:
            val = max(0, int(float(ent.get())))
        except Exception:
            messagebox.showerror("Valor inválido", "Minutos deben ser número.")
            return
        self.steps[idx]["min"] = val
        self._refresh_lb()

    def _set_speed(self, idx: int, spd: str):
        if self.steps[idx]["accion"] == "centrifugado":
            self.steps[idx]["velocidad"] = spd
            self._refresh_lb()

    def _toggle_final(self, idx: int, is_final: bool):
        s = self.steps[idx]
        s["rinse_final"] = is_final
        # si se quita "final", se quita suavizante
        if not is_final and "suavizante" in s["quimicos"]:
            s["quimicos"].discard("suavizante")
        # actualizar habilitados
        self._apply_chem_rules_for_step(idx)
        self._refresh_lb()

    def _delete_step(self, idx: int):
        if idx < 0 or idx >= len(self.steps): return
        del self.steps[idx]
        self._refresh_lb()
        if self.listbox.size():
            self.listbox.selection_set(min(idx, self.listbox.size()-1))
            self._render_selected()
        else:
            for w in self.step_frame.winfo_children(): w.destroy()
            for w in self.chem_frame.winfo_children(): w.destroy()

    # ------- Químicos: reglas / exclusiones -------
    def _allowed_by_action(self, accion: str, rinse_final: bool) -> Dict[str, bool]:
        # True = permitido, False = prohibido
        allowed = {k: False for _,k in self.CHEM_KEYS}
        if accion == "prelavado":
            allowed["detergente"] = True
            allowed["quitamanchas"] = True
        elif accion == "lavado":
            allowed["detergente"] = True
            allowed["quitamanchas"] = True
            allowed["blanqueador"] = True
        elif accion == "enjuague":
            allowed["suavizante"] = bool(rinse_final)  # solo si final
        # centrifugado/drenaje: ninguno
        return allowed

    def _sanitize_quimicos(self, accion: str, rinse_final: bool, current: set) -> set:
        allowed = self._allowed_by_action(accion, rinse_final)
        new = {q for q in current if allowed.get(q, False)}
        # defaults
        if accion in ("prelavado","lavado"):
            new.add("detergente")
        if accion == "lavado" and ("blanqueador" in new and "quitamanchas" in new):
            # exclusión: mantener el último es complejo sin historial;
            # política simple: priorizar blanqueador y quitar quitamanchas
            new.discard("quitamanchas")
        if accion == "enjuague" and rinse_final:
            new.add("suavizante")
        return new

    def _apply_chem_rules_for_step(self, idx: int):
        """Habilita/deshabilita checks según acción y estado 'final' + aplica exclusiones."""
        s = self.steps[idx]
        accion = s["accion"]; is_final = s.get("rinse_final", False)
        allowed = self._allowed_by_action(accion, is_final)

        # Crear mapas si no existen (cuando venimos de _render_selected)
        if not hasattr(self, "chem_vars") or not hasattr(self, "chem_checks"):
            return

        # Habilitar / deshabilitar visual y limpiar seleccionados no válidos
        for key, chk in self.chem_checks.items():
            if allowed.get(key, False):
                chk.state(["!disabled"])
            else:
                chk.state(["disabled"])
                if key in s["quimicos"]:
                    s["quimicos"].discard(key)
                    self.chem_vars[key].set(False)

        # Forzar defaults mínimos
        if accion in ("prelavado","lavado"):
            s["quimicos"].add("detergente")
            self.chem_vars["detergente"].set(True)
        if accion == "enjuague" and is_final:
            s["quimicos"].add("suavizante")
            self.chem_vars["suavizante"].set(True)

        # Exclusión: blanqueador vs quitamanchas
        if "blanqueador" in s["quimicos"] and "quitamanchas" in s["quimicos"]:
            # política simple: mantener blanqueador
            s["quimicos"].discard("quitamanchas")
            self.chem_vars["quitamanchas"].set(False)

        self._refresh_lb()

    def _chem_clicked(self, idx: int, key: str):
        s = self.steps[idx]
        accion = s["accion"]; is_final = s.get("rinse_final", False)
        allowed = self._allowed_by_action(accion, is_final)
        if not allowed.get(key, False):
            # ignorar clicks sobre items deshabilitados
            self.chem_vars[key].set(False)
            return

        if self.chem_vars[key].get():
            s["quimicos"].add(key)
            # exclusión bleach vs quitamanchas
            if key == "blanqueador" and "quitamanchas" in s["quimicos"]:
                s["quimicos"].discard("quitamanchas")
                self.chem_vars["quitamanchas"].set(False)
            elif key == "quitamanchas" and "blanqueador" in s["quimicos"]:
                s["quimicos"].discard("blanqueador")
                self.chem_vars["blanqueador"].set(False)
        else:
            if key in s["quimicos"]:
                s["quimicos"].discard(key)

        # mantener defaults obligatorios
        if accion in ("prelavado","lavado"):
            s["quimicos"].add("detergente")
            self.chem_vars["detergente"].set(True)
        if accion == "enjuague" and is_final:
            s["quimicos"].add("suavizante")
            self.chem_vars["suavizante"].set(True)

        self._refresh_lb()

    # ------- guardar -------
    def _save(self):
        nombre = self.nombre_var.get().strip() or "Ciclo rápido"
        if not self.steps:
            messagebox.showwarning("Vacío", "Agrega al menos un paso.")
            return

        pasos: List[Step] = []
        for i, s in enumerate(self.steps):
            accion = s["accion"]
            try:
                dur = int(s["min"]) * 60
            except Exception:
                messagebox.showerror("Valor inválido", f"Minutos en paso {i+1} deben ser número.")
                return

            nivel = "" if accion in ("centrifugado","drenaje") else "estandar"
            vel = s.get("velocidad","") if accion == "centrifugado" else ""
            chems = sorted(list(s.get("quimicos", set())))

            pasos.append(Step(
                accion=accion,
                duracion=dur,
                nivel_agua=nivel,   # <-- ajusta si tu modelo cambia
                quimicos=chems,     # <-- ajusta si tu modelo cambia
                velocidad=vel       # <-- ajusta si tu modelo cambia
            ))

        ciclo = Cycle(nombre=nombre, pasos=pasos)
        setattr(ciclo, "agua_temp", self.temp_var.get())
        self.on_save(ciclo)
        self.destroy()
