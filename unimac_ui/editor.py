# -*- coding: utf-8 -*-
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Optional, List

EDITOR_VERSION = "v2"

# -------- imports robustos ----------
try:
    from unimac_ui.models import Cycle
    from unimac_ui.models import Step as StepModel
except Exception:
    from .models import Cycle
    try:
        from .models import Step as StepModel
    except Exception:
        StepModel = None

# Intentar usar el teclado embebido del proyecto; si no existe, definimos un fallback aquí:
try:
    from unimac_ui.keyboard import KeyboardFrame as ExtKeyboardFrame
except Exception:
    try:
        from .keyboard import KeyboardFrame as ExtKeyboardFrame
    except Exception:
        ExtKeyboardFrame = None


# ---------- Fallback de teclado (con objetivo persistente) ----------
class _FallbackKeyboardFrame(ttk.Frame):
    """
    Teclado embebido fiable (fallback interno):
      - Mantiene Entry objetivo persistente (no depende del foco)
      - Tras cada tecla, devuelve el foco al Entry
      - Modos: "text" (QWERTY) y "numeric"
    """
    def __init__(self, master, mode="text", title="Teclado",
                 key_font: Optional[tkfont.Font]=None, btn_pad=(4, 6)):
        super().__init__(master, padding=6)
        ttk.Label(self, text=title).pack(anchor="w", pady=(0, 4))

        self.mode = mode
        self.shift = False
        self._target_entry: Optional[tk.Entry] = None

        self.key_font = key_font or tkfont.Font(size=15, weight="bold")
        self.btn_pad = btn_pad

        if mode == "numeric":
            layout = [
                ["7", "8", "9", "⌫"],
                ["4", "5", "6", "Limpiar"],
                ["1", "2", "3"],
                ["0"],
            ]
        else:
            layout = [
                list("1234567890"),
                list("qwertyuiop"),
                list("asdfghjkl"),
                ["⇧"] + list("zxcvbnm") + ["⌫"],
                ["ESPACIO", "Limpiar"],
            ]

        style = ttk.Style(self)
        style.configure("Kb.TButton", font=self.key_font)

        for row in layout:
            rowf = ttk.Frame(self)
            rowf.pack(fill="x")
            for key in row:
                b = ttk.Button(rowf, text=key, style="Kb.TButton",
                               command=lambda k=key: self._press(k))
                b["padding"] = self.btn_pad
                try:
                    b.configure(takefocus=False)
                except Exception:
                    pass
                b.pack(side="left", padx=4, pady=4, expand=True)

    def set_target(self, entry: Optional[tk.Entry]):
        self._target_entry = entry

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
        e = self._target_entry
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
        char = key.upper() if (self.mode != "numeric" and self.shift) else key
        e.insert("insert", char)
        e.focus_set()


# Usa el teclado externo si existe, si no el fallback interno
KeyboardFrame = ExtKeyboardFrame or _FallbackKeyboardFrame


class TouchCycleEditor(tk.Toplevel):
    """
    Editor táctil de ciclo (V2)
    - Sin barra superior
    - Botonera inferior (Agregar / Cancelar / Guardar)
    - Flechas de scroll ocupan toda el área de pasos (no pisan botonera/teclado)
    - Teclados on-demand con Entry objetivo persistente
    """
    def __init__(self, master, on_save, preload: Optional[Cycle] = None):
        super().__init__(master)
        self.title(f"Crear/Editar Ciclo ({EDITOR_VERSION})")
        self.attributes("-fullscreen", True)
        self.transient(master)

        # Referencias/estilos del master
        self.is_720p = getattr(master, "is_720p", True)
        self.header_font = getattr(
            master, "header_font",
            tkfont.Font(size=(18 if self.is_720p else 20), weight="bold")
        )

        # Fuentes base
        self.f_label_big = tkfont.Font(size=(18 if self.is_720p else 20), weight="bold")  # “Nombre del ciclo”
        self.f_entry_big = tkfont.Font(size=(16 if self.is_720p else 18))                 # Entry nombre
        self.f_field     = tkfont.Font(size=(15 if self.is_720p else 16))                 # Labels (+1 pt)
        self.f_list      = tkfont.Font(size=(16 if self.is_720p else 18))                 # Lista pasos
        self.f_btn_chip  = tkfont.Font(size=(16 if self.is_720p else 18), weight="bold")  # Chips

        # Fuente DOBLE para radios/checks
        base_sz = int(self.f_field.cget("size"))
        self.f_choice = tkfont.Font(size=base_sz * 1)

        # Estilos
        self.style = ttk.Style(self)
        # Define estilos base si no existen
        try:
            self.style.lookup("Control.TButton", "font")
        except Exception:
            self.style.configure("Control.TButton", font=("TkDefaultFont", 14, "bold"), padding=(12, 10))
        try:
            self.style.lookup("Arrow.TButton", "font")
        except Exception:
            self.style.configure("Arrow.TButton", font=("TkDefaultFont", 18, "bold"), padding=(8, 10), width=3)

        # Estilos grandes para radios/checks
        self.style.configure("Choice.TRadiobutton", font=self.f_choice)
        self.style.configure("Choice.TCheckbutton", font=self.f_choice)

        self.on_save = on_save
        self.step_rows: List[dict] = []

        # ---------- Layout raíz ----------
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Encabezado (sin app bar): nombre + temperatura global
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 6))

        ttk.Label(top, text="Nombre del ciclo:", font=self.f_label_big).grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=(preload.nombre if preload else "Ciclo Personalizado"))
        self.name_entry = ttk.Entry(top, textvariable=self.name_var, font=self.f_entry_big, width=38)
        self.name_entry.grid(row=0, column=1, sticky="w", padx=(6, 18))
        # Al enfocar, mostrar teclado alfabético y fijar objetivo
        self.name_entry.bind("<FocusIn>", lambda e, en=self.name_entry: self._attach_alpha(en))

        ttk.Label(top, text="Temperatura del agua (global):", font=self.f_field)\
            .grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.temp_var = tk.StringVar(value=getattr(preload, "agua_temp", "fria") or "fria")
        rb = ttk.Frame(top); rb.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Radiobutton(rb, text="Agua fría", value="fria", variable=self.temp_var,
                        style="Choice.TRadiobutton").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(rb, text="Agua caliente", value="caliente", variable=self.temp_var,
                        style="Choice.TRadiobutton").pack(side="left", padx=(0, 12))

        # Centro: pasos + flechas
        center = ttk.Frame(root)
        center.pack(fill="both", expand=True, pady=(8, 6))

        # fila0: pasos + flechas   fila1: botonera   fila2: teclados
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)  # canvas
        center.columnconfigure(1, weight=0)  # flechas

        # Canvas con frame interior para pasos
        self.steps_canvas = tk.Canvas(center, highlightthickness=0, bd=0)
        self.steps_canvas.grid(row=0, column=0, sticky="nsew")

        self.steps_inner = ttk.Frame(self.steps_canvas)
        self.steps_window = self.steps_canvas.create_window((0, 0), window=self.steps_inner, anchor="nw")
        self.steps_inner.bind("<Configure>", self._on_steps_configure)
        self.steps_canvas.bind("<Configure>", self._on_canvas_configure)

        # Flechas a TODO el alto (no tapan botonera/teclado)
        arrows = ttk.Frame(center)
        arrows.grid(row=0, column=1, sticky="nsw", padx=(6, 0))
        self.btn_up = ttk.Button(arrows, text="▲", style="Arrow.TButton",
                                 command=lambda: self._scroll_steps("up"))
        self.btn_dn = ttk.Button(arrows, text="▼", style="Arrow.TButton",
                                 command=lambda: self._scroll_steps("down"))
        self.btn_up.pack(fill="both", expand=True, pady=(0, 3))
        self.btn_dn.pack(fill="both", expand=True, pady=(3, 0))
        self.btn_up.bind("<ButtonPress-1>", lambda e: self._scroll_hold("up"))
        self.btn_dn.bind("<ButtonPress-1>", lambda e: self._scroll_hold("down"))
        self.btn_up.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        self.btn_dn.bind("<ButtonRelease-1>", lambda e: self._scroll_release())
        self._scroll_job = None

        # Botonera inferior (debajo de pasos, arriba del teclado)
        actions = ttk.Frame(center)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=0)
        actions.columnconfigure(2, weight=0)

        ttk.Button(actions, text="+ Agregar paso", style="Control.TButton",
                   command=self._add_step).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="Cancelar", style="Control.TButton",
                   command=self._close).grid(row=0, column=1, sticky="e", padx=(6, 0))
        ttk.Button(actions, text="Guardar ciclo", style="Control.TButton",
                   command=self._save).grid(row=0, column=2, sticky="e", padx=(6, 0))

        # Teclados on-demand (persistentes)
        self.kb_alpha = KeyboardFrame(center, mode="text", title="Teclado")
        self.kb_num   = KeyboardFrame(center, mode="numeric", title="Teclado numérico")
        self.kb_alpha.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0)); self.kb_alpha.grid_remove()
        self.kb_num.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0)); self.kb_num.grid_remove()

        # Precarga o 1 paso por defecto
        if preload and getattr(preload, "pasos", None):
            for s in preload.pasos:
                self._add_step(pre=s)
        else:
            self._add_step()

        # foco inicial
        self.after(50, lambda: self.name_entry.focus_set())

    # ---------- Scroll ----------
    def _on_steps_configure(self, event=None):
        self.steps_canvas.configure(scrollregion=self.steps_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.steps_canvas.itemconfigure(self.steps_window, width=event.width)

    def _scroll_steps(self, direction: str):
        self.steps_canvas.yview_scroll(-3 if direction == "up" else 3, "units")

    def _scroll_hold(self, direction: str):
        self._scroll_steps(direction)
        self._scroll_job = self.after(120, lambda: self._scroll_hold(direction))

    def _scroll_release(self):
        if self._scroll_job:
            self.after_cancel(self._scroll_job)
            self._scroll_job = None

    # ---------- Teclados (objetivo persistente) ----------
    def _attach_alpha(self, entry: tk.Entry):
        self.kb_num.grid_remove()
        self.kb_alpha.grid()
        self.kb_alpha.set_target(entry)

    def _attach_numeric(self, entry: tk.Entry):
        self.kb_alpha.grid_remove()
        self.kb_num.grid()
        self.kb_num.set_target(entry)

    # ---------- Pasos ----------
    def _add_step(self, pre=None):
        idx = len(self.step_rows) + 1
        lf = ttk.LabelFrame(self.steps_inner, text=f"Paso {idx}")
        lf.pack(fill="x", pady=6)

        # fila 0: acción + duración + eliminar
        row0 = ttk.Frame(lf); row0.pack(fill="x", pady=(4, 6))
        ttk.Label(row0, text="Acción:", font=self.f_field).pack(side="left")
        action_var = tk.StringVar(value=getattr(pre, "accion", "prelavado"))
        action_cb = ttk.Combobox(row0, textvariable=action_var, state="readonly",
                                 values=["prelavado", "lavado", "enjuague", "centrifugado", "drenaje"], width=16)
        action_cb["font"] = self.f_field
        action_cb.pack(side="left", padx=(6, 16))

        ttk.Label(row0, text="Duración (min):", font=self.f_field).pack(side="left")
        mins_var = tk.StringVar(value=str(int(getattr(pre, "duracion", 120)//60)))
        mins_entry = ttk.Entry(row0, textvariable=mins_var, width=6, font=self.f_field)
        mins_entry.pack(side="left", padx=(6, 6))
        mins_entry.bind("<FocusIn>", lambda e, en=mins_entry: self._attach_numeric(en))

        ttk.Button(row0, text="Eliminar paso", style="Control.TButton",
                   command=lambda f=lf: self._delete_step(f)).pack(side="right")

        # fila 1: nivel de agua (radios GRANDES)
        row1 = ttk.Frame(lf); row1.pack(fill="x", pady=(2, 2))
        ttk.Label(row1, text="Nivel de agua:", font=self.f_field).pack(side="left")
        nivel_var = tk.StringVar(value=getattr(pre, "nivel_agua", "estandar"))
        for txt, val in (("Ligero", "ligero"), ("Estándar", "estandar"), ("Intenso", "intenso")):
            ttk.Radiobutton(row1, text=txt, variable=nivel_var, value=val,
                            style="Choice.TRadiobutton").pack(side="left", padx=(12, 0))

        # fila 2: químicos (checks GRANDES, dos columnas con separación corta)
        row2 = ttk.Frame(lf); row2.pack(fill="x", pady=(2, 2))
        ttk.Label(row2, text="Químicos:", font=self.f_field).pack(side="left")
        colA = ttk.Frame(row2); colA.pack(side="left", padx=(8, 6))
        colB = ttk.Frame(row2); colB.pack(side="left", padx=(6, 0))
        q_det = tk.BooleanVar(value=("Detergente" in getattr(pre, "quimicos", [])))
        q_quit = tk.BooleanVar(value=("Quitamanchas" in getattr(pre, "quimicos", [])))
        q_suav = tk.BooleanVar(value=("Suavizante" in getattr(pre, "quimicos", [])))
        q_blan = tk.BooleanVar(value=("Blanqueador" in getattr(pre, "quimicos", [])))
        ttk.Checkbutton(colA, text="Detergente",  variable=q_det,  style="Choice.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(colA, text="Suavizante",  variable=q_suav, style="Choice.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(colB, text="Quitamanchas", variable=q_quit, style="Choice.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(colB, text="Blanqueador",  variable=q_blan, style="Choice.TCheckbutton").pack(anchor="w")

        # fila 3: velocidad (radios GRANDES)
        row3 = ttk.Frame(lf); row3.pack(fill="x", pady=(2, 6))
        ttk.Label(row3, text="Velocidad:", font=self.f_field).pack(side="left")
        vel_var = tk.StringVar(value=getattr(pre, "velocidad", "medio"))
        for txt, val in (("Bajo", "bajo"), ("Medio", "medio"), ("Alto", "alto")):
            ttk.Radiobutton(row3, text=txt, variable=vel_var, value=val,
                            style="Choice.TRadiobutton").pack(side="left", padx=(12, 0))

        self.step_rows.append({
            "frame": lf,
            "action": action_var,
            "mins": mins_var,
            "nivel": nivel_var,
            "q_det": q_det, "q_quit": q_quit, "q_suav": q_suav, "q_blan": q_blan,
            "vel": vel_var,
        })

        # autoscroll al final
        self.after(40, lambda: self.steps_canvas.yview_moveto(1.0))

    def _delete_step(self, frame):
        for i, row in enumerate(self.step_rows):
            if row["frame"] is frame:
                row["frame"].destroy()
                self.step_rows.pop(i)
                break
        for i, row in enumerate(self.step_rows, start=1):
            try:
                row["frame"].config(text=f"Paso {i}")
            except Exception:
                pass
        self._on_steps_configure()

    # ---------- Guardar / Cerrar ----------
    def _save(self):
        nombre = (self.name_var.get() or "").strip() or "Ciclo Personalizado"
        pasos = []
        for row in self.step_rows:
            try:
                mins = int(row["mins"].get())
            except Exception:
                mins = 1
            secs = max(1, mins) * 60
            quims = []
            if row["q_det"].get():  quims.append("Detergente")
            if row["q_quit"].get(): quims.append("Quitamanchas")
            if row["q_suav"].get(): quims.append("Suavizante")
            if row["q_blan"].get(): quims.append("Blanqueador")

            # Crear Step compatible (dos firmas posibles)
            step_obj = None
            if StepModel:
                try:
                    step_obj = StepModel(
                        accion=row["action"].get(),
                        duracion=secs,
                        nivel_agua=row["nivel"].get(),
                        quimicos=quims,
                        velocidad=row["vel"].get(),
                    )
                except TypeError:
                    chem = None
                    if "Detergente" in quims: chem = "A"
                    step_obj = StepModel(
                        accion=row["action"].get(),
                        duracion=secs,
                        agua=None,
                        quimico=chem,
                        velocidad=row["vel"].get(),
                    )
            else:
                step_obj = {
                    "accion": row["action"].get(),
                    "duracion": secs,
                    "nivel_agua": row["nivel"].get(),
                    "quimicos": quims,
                    "velocidad": row["vel"].get(),
                }
            pasos.append(step_obj)

        cycle = Cycle(nombre=nombre, pasos=pasos)
        try:
            cycle.agua_temp = self.temp_var.get()
        except Exception:
            pass

        if callable(self.on_save):
            self.on_save(cycle)
        self._close()

    def _close(self):
        try:
            self.destroy()
        except Exception:
            pass
