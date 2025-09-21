#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI de Lavadora Industrial - Tkinter
Arquitectura: la lógica/vigilancia vive en Python; los .txt contienen SOLO parámetros.
Autor: pensado para Iván (AXIS 3D) - Proyecto Automatización Lavadora UNIMAC
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import time

# =========================
#   MODELOS DE DOMINIO
# =========================

@dataclass
class Step:
    accion: str
    duracion: int  # segundos
    agua: Optional[str] = None         # 'fria' | 'caliente' | None
    quimico: Optional[str] = None      # 'A' | 'B' | ...
    velocidad: Optional[str] = None    # 'bajo' | 'medio' | 'alto'

    def to_human(self, idx: int) -> str:
        parts = [f"Paso {idx}: {self.accion.capitalize()} - {self.duracion}s"]
        if self.agua:
            parts.append(f"Agua {self.agua}")
        if self.quimico:
            parts.append(f"Químico {self.quimico}")
        if self.velocidad:
            parts.append(self.velocidad.capitalize())
        return " ".join(parts)


@dataclass
class Cycle:
    nombre: str
    pasos: List[Step] = field(default_factory=list)

    @property
    def total_duracion(self) -> int:
        return sum(p.duracion for p in self.pasos)

# =========================
#   PERSISTENCIA .TXT
# =========================

CICLOS_DIR = "ciclos"

def ensure_demo_files():
    """Crea carpeta y dos ciclos demo si no existen."""
    os.makedirs(CICLOS_DIR, exist_ok=True)
    demo1 = os.path.join(CICLOS_DIR, "Ciclo_Rapido.txt")
    demo2 = os.path.join(CICLOS_DIR, "Ciclo_Industrial.txt")
    if not os.path.exists(demo1):
        with open(demo1, "w", encoding="utf-8") as f:
            f.write(
                "# Ciclo rápido de ejemplo\n"
                "nombre=Ciclo Rápido\n"
                "accion=prelavado;duracion=120;agua=fria\n"
                "accion=lavado;duracion=600;quimico=A\n"
                "accion=enjuague;duracion=300;agua=fria\n"
                "accion=centrifugado;duracion=180;velocidad=alto\n"
            )
    if not os.path.exists(demo2):
        with open(demo2, "w", encoding="utf-8") as f:
            f.write(
                "# Ciclo industrial de ejemplo\n"
                "nombre=Ciclo Industrial\n"
                "accion=prelavado;duracion=240;agua=fria\n"
                "accion=lavado;duracion=900;quimico=B\n"
                "accion=enjuague;duracion=300;agua=caliente\n"
                "accion=enjuague;duracion=300;agua=fria\n"
                "accion=centrifugado;duracion=240;velocidad=alto\n"
            )

def parse_kv(segment: str) -> Dict[str, str]:
    out = {}
    for par in segment.split(";"):
        if not par.strip():
            continue
        if "=" in par:
            k, v = par.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out

def load_cycle_from_txt(path: str) -> Cycle:
    nombre = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    pasos: List[Step] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("nombre="):
                nombre = line.split("=", 1)[1].strip()
                continue
            kv = parse_kv(line)
            accion = kv.get("accion")
            dur = kv.get("duracion")
            if not accion or not dur:
                continue
            try:
                dur = int(dur)
            except ValueError:
                continue
            pasos.append(Step(
                accion=accion,
                duracion=dur,
                agua=kv.get("agua"),
                quimico=kv.get("quimico"),
                velocidad=kv.get("velocidad"),
            ))
    return Cycle(nombre=nombre, pasos=pasos)

def save_cycle_to_txt(cycle: Cycle, path: str):
    lines = [f"nombre={cycle.nombre}"]
    for s in cycle.pasos:
        segs = [f"accion={s.accion}", f"duracion={s.duracion}"]
        if s.agua: segs.append(f"agua={s.agua}")
        if s.quimico: segs.append(f"quimico={s.quimico}")
        if s.velocidad: segs.append(f"velocidad={s.velocidad}")
        lines.append(";".join(segs))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def list_cycles() -> List[str]:
    ensure_demo_files()
    files = [f for f in os.listdir(CICLOS_DIR) if f.lower().endswith(".txt")]
    return sorted(files)

# =========================
#   ABSTRACCIÓN DE HARDWARE
# =========================

class HardwareIO:
    """
    Capa para aislar el hardware.
    Sustituye las funciones por GPIO/Modbus/PLC según tu implementación.
    """
    def __init__(self):
        # Callbacks externos opcionales
        self.read_emergency_stop: Optional[Callable[[], bool]] = None
        self.read_suction_sensor: Optional[Callable[[], bool]] = None

    # --- Actuadores ---
    def fill(self, temp: Optional[str]):
        # Implementa válvulas de entrada
        print(f"[HW] Llenando con agua: {temp or 'N/A'}")

    def add_chemical(self, ident: Optional[str]):
        if ident:
            print(f"[HW] Dosificando químico {ident}")

    def drain_open(self, enable: bool):
        print(f"[HW] Drenaje {'ABIERTO' if enable else 'CERRADO'}")

    def spin(self, level: Optional[str]):
        if level:
            print(f"[HW] Centrifugado: {level}")

    def stop_all(self):
        print("[HW] Paro total: todos los actuadores a estado seguro")

    # --- Sensores/monitoreo ---
    def is_emergency_pressed(self) -> bool:
        if self.read_emergency_stop:
            return bool(self.read_emergency_stop())
        return False

    def has_suction(self) -> bool:
        if self.read_suction_sensor:
            return bool(self.read_suction_sensor())
        return True  # por defecto asumimos OK

# =========================
#   EJECUTOR DE CICLOS
# =========================

class Executor:
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"

    def __init__(self, hw: HardwareIO, on_status: Callable[[str], None], on_tick: Callable[[int, int, int], None], on_step_change: Callable[[int], None], on_finish: Callable[[], None]):
        self.hw = hw
        self.on_status = on_status
        self.on_tick = on_tick
        self.on_step_change = on_step_change
        self.on_finish = on_finish

        self.state = Executor.IDLE
        self.cycle: Optional[Cycle] = None
        self.step_index: int = 0
        self.step_remaining: int = 0
        self.total_remaining: int = 0
        self._last_tick = time.time()

    def load_cycle(self, cycle: Cycle):
        self.cycle = cycle
        self.reset_runtime()

    def reset_runtime(self):
        self.state = Executor.IDLE
        self.step_index = 0
        self.step_remaining = self.cycle.pasos[0].duracion if (self.cycle and self.cycle.pasos) else 0
        self.total_remaining = self.cycle.total_duracion if self.cycle else 0
        self._last_tick = time.time()

    def start(self):
        if not self.cycle or not self.cycle.pasos:
            self.on_status("No hay ciclo cargado.")
            return
        self.state = Executor.RUNNING
        self._last_tick = time.time()
        self._apply_step(self.cycle.pasos[self.step_index])
        self.on_status("Ejecutando")

    def pause(self):
        if self.state == Executor.RUNNING:
            self.state = Executor.PAUSED
            self.hw.stop_all()
            self.on_status("Pausado")
        elif self.state == Executor.PAUSED:
            self.state = Executor.RUNNING
            # Reaplicar el paso actual
            self._apply_step(self.cycle.pasos[self.step_index])
            self._last_tick = time.time()
            self.on_status("Reanudado")

    def stop(self):
        self.state = Executor.STOPPED
        self.hw.stop_all()
        # Secuencia de paro seguro (ejemplo): abrir drenaje y detener giro
        self.hw.drain_open(True)
        self.on_status("Detenido (paro seguro)")

    def tick(self):
        """Debe llamarse periódicamente (GUI.after)."""
        # Vigilancias rápidas
        if self.hw.is_emergency_pressed():
            self.stop()
        if self.state != Executor.RUNNING:
            self.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            return

        now = time.time()
        elapsed = now - self._last_tick
        if elapsed >= 1.0:
            secs = int(elapsed)
            self._last_tick = now
            self.step_remaining = max(0, self.step_remaining - secs)
            self.total_remaining = max(0, self.total_remaining - secs)

            if self.step_remaining <= 0:
                self._next_step()

        self.on_tick(self.step_index, self.step_remaining, self.total_remaining)

    # --- Helpers internos ---

    def _apply_step(self, step: Step):
        # Apaga todo de base
        self.hw.stop_all()

        acc = step.accion.lower()
        if acc in ("prelavado", "lavado", "enjuague"):
            # Llenado + (opcional) químico, sin giro fuerte
            self.hw.fill(step.agua)
            self.hw.add_chemical(step.quimico)
        elif acc in ("centrifugado", "spin"):
            self.hw.drain_open(True)
            self.hw.spin(step.velocidad)
        elif acc in ("drenaje", "descarga"):
            self.hw.drain_open(True)
        else:
            # Paso genérico: permitir acciones personalizadas en el futuro
            pass

        # tiempo del paso
        self.step_remaining = step.duracion

    def _next_step(self):
        self.step_index += 1
        if not self.cycle or self.step_index >= len(self.cycle.pasos):
            self.finish()
            return
        self.on_step_change(self.step_index)
        self._apply_step(self.cycle.pasos[self.step_index])

    def finish(self):
        self.state = Executor.IDLE
        self.hw.stop_all()
        self.on_status("Ciclo terminado")
        self.on_finish()

# =========================
#   GUI TKINTER
# =========================

class WasherUI(tk.Tk):
    TICK_MS = 200  # 5 Hz para respuesta rápida sin hilos

    def __init__(self):
        super().__init__()
        self.title("Lavadora Industrial")
        self.geometry("960x590")
        self.minsize(840, 520)

        self.hw = HardwareIO()
        self.executor = Executor(
            hw=self.hw,
            on_status=self._update_status_text,
            on_tick=self._on_tick,
            on_step_change=self._on_step_change,
            on_finish=self._on_finish
        )

        self.selected_cycle: Optional[Cycle] = None
        self._build_ui()
        self._load_cycle_list()
        self.after(self.TICK_MS, self._loop)

    # --- UI building ---

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Top bar
        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=(0, 8))

        self.btn_refresh = ttk.Button(bar, text="⟳  Seleccionar Ciclo", command=self._select_cycle_dialog)
        self.btn_refresh.pack(side="left", padx=(0, 8))

        self.btn_create = ttk.Button(bar, text="+  Crear Ciclo", command=self._create_cycle_dialog)
        self.btn_create.pack(side="left", padx=(0, 8))

        self.btn_delete = ttk.Button(bar, text="🗑  Eliminar", command=self._delete_selected_cycle)
        self.btn_delete.pack(side="left")

        # Body split
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)

        # List panel
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ttk.Label(left, text="Ciclos Disponibles", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 6))
        self.listbox = tk.Listbox(left, exportselection=False, height=15)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_list_select())

        # Details panel
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(right, text="Detalles", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 6))

        self.details = tk.Text(right, height=18, wrap="word")
        self.details.configure(state="disabled")
        self.details.pack(fill="both", expand=True)

        # Controls bottom
        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=8)

        self.btn_run = ttk.Button(controls, text="▶  Ejecutar", command=self._start_execution)
        self.btn_run.pack(side="left", padx=(0, 8))

        self.btn_pause = ttk.Button(controls, text="⏸  Pausar", command=self._pause_resume, state="disabled")
        self.btn_pause.pack(side="left", padx=(0, 8))

        self.btn_stop = ttk.Button(controls, text="■  Detener", command=self._stop_execution, state="disabled")
        self.btn_stop.pack(side="left")

        # Status line
        self.status = ttk.Label(root, text="Estado actual: Inactivo")
        self.status.pack(anchor="w", pady=(8, 0))

    # --- UI helpers ---

    def _load_cycle_list(self):
        self.listbox.delete(0, "end")
        for f in list_cycles():
            lbl = f[:-4].replace("_", " ")
            self.listbox.insert("end", lbl)

    def _on_list_select(self):
        idx = self.listbox.curselection()
        if not idx:
            return
        filename = list_cycles()[idx[0]]
        path = os.path.join(CICLOS_DIR, filename)
        self.selected_cycle = load_cycle_from_txt(path)
        self._render_details(self.selected_cycle)

    def _render_details(self, cycle: Optional[Cycle]):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if not cycle:
            self.details.insert("end", "Selecciona un ciclo para ver sus detalles.")
        else:
            self.details.insert("end", f"{cycle.nombre}\n\n")
            for i, p in enumerate(cycle.pasos, 1):
                self.details.insert("end", p.to_human(i) + "\n")
        self.details.configure(state="disabled")

    def _update_status_text(self, text: str):
        if self.selected_cycle and self.executor.state in (Executor.RUNNING, Executor.PAUSED):
            step_n = self.executor.step_index + 1
            total = len(self.selected_cycle.pasos)
            self.status.config(text=f"Estado actual: {text} - Paso {step_n} de {total}")
        else:
            self.status.config(text=f"Estado actual: {text}")

    def _on_tick(self, step_idx: int, step_remaining: int, total_remaining: int):
        # Refresca el tiempo restante en la barra de estado
        if self.selected_cycle and self.executor.state in (Executor.RUNNING, Executor.PAUSED):
            step_n = step_idx + 1
            total = len(self.selected_cycle.pasos)
            self.status.config(
                text=f"Estado actual: {'Pausado' if self.executor.state==Executor.PAUSED else 'Lavando'} "
                     f"- Paso {step_n} de {total} - Tiempo restante: {self._fmt_secs(total_remaining)}"
            )

    def _on_step_change(self, step_idx: int):
        # Podrías resaltar el paso actual en los detalles si quisieras
        pass

    def _on_finish(self):
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_run.configure(state="normal")

    def _fmt_secs(self, s: int) -> str:
        m, sec = divmod(max(0, s), 60)
        return f"{m}:{sec:02d}"

    # --- Buttons logic ---

    def _start_execution(self):
        if not self.selected_cycle:
            messagebox.showwarning("Sin ciclo", "Selecciona un ciclo primero.")
            return
        self.executor.load_cycle(self.selected_cycle)
        self.executor.start()
        self.btn_run.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="⏸  Pausar")
        self.btn_stop.configure(state="normal")

    def _pause_resume(self):
        self.executor.pause()
        if self.executor.state == Executor.PAUSED:
            self.btn_pause.configure(text="▶  Reanudar")
        else:
            self.btn_pause.configure(text="⏸  Pausar")

    def _stop_execution(self):
        self.executor.stop()
        self.btn_pause.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_run.configure(state="normal")

    def _select_cycle_dialog(self):
        # Esto recarga la lista (útil si agregaste archivos a mano)
        self._load_cycle_list()
        messagebox.showinfo("Ciclos", "Lista de ciclos actualizada. Selecciona uno en la lista de la izquierda.")

    def _create_cycle_dialog(self):
        # Diálogo simple para crear/editar a partir de texto
        dlg = CycleEditor(self, on_save=self._on_cycle_saved)
        dlg.grab_set()

    def _on_cycle_saved(self, cycle: Cycle):
        fname = cycle.nombre.replace(" ", "_") + ".txt"
        save_cycle_to_txt(cycle, os.path.join(CICLOS_DIR, fname))
        self._load_cycle_list()
        messagebox.showinfo("Guardado", f"Ciclo '{cycle.nombre}' guardado.")
        # Autoseleccionar
        for i, f in enumerate(list_cycles()):
            if f == fname:
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.event_generate("<<ListboxSelect>>")
                break

    def _delete_selected_cycle(self):
        idx = self.listbox.curselection()
        if not idx:
            messagebox.showwarning("Eliminar", "Selecciona un ciclo para eliminar.")
            return
        filename = list_cycles()[idx[0]]
        path = os.path.join(CICLOS_DIR, filename)
        if messagebox.askyesno("Confirmar", f"¿Eliminar '{filename}'?"):
            try:
                os.remove(path)
            except Exception as e:
                messagebox.showerror("Error", str(e))
            self._load_cycle_list()
            self.selected_cycle = None
            self._render_details(None)

    # --- Main loop for executor ---
    def _loop(self):
        self.executor.tick()
        self.after(self.TICK_MS, self._loop)

# =========================
#   EDITOR DE CICLOS
# =========================

class CycleEditor(tk.Toplevel):
    TEMPLATE = (
        "nombre=Ciclo Personalizado\n"
        "accion=prelavado;duracion=120;agua=fria\n"
        "accion=lavado;duracion=600;quimico=A\n"
        "accion=enjuague;duracion=300;agua=fria\n"
        "accion=centrifugado;duracion=180;velocidad=alto\n"
    )

    def __init__(self, master, on_save: Callable[[Cycle], None]):
        super().__init__(master)
        self.title("Crear/Editar Ciclo")
        self.geometry("640x520")
        self.on_save = on_save

        ttk.Label(self, text="Pega/edita el contenido del ciclo (.txt):", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        self.text = tk.Text(self, wrap="word")
        self.text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.text.insert("1.0", self.TEMPLATE)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Guardar", command=self._save).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side="right")

    def _save(self):
        # Guarda a un Cycle en memoria (no escribe archivo aquí)
        content = self.text.get("1.0", "end").strip().splitlines()
        nombre = "Ciclo Personalizado"
        pasos: List[Step] = []
        for line in content:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("nombre="):
                nombre = line.split("=", 1)[1].strip()
                continue
            kv = parse_kv(line)
            accion = kv.get("accion")
            dur = kv.get("duracion")
            if not accion or not dur:
                continue
            try:
                dur = int(dur)
            except ValueError:
                messagebox.showerror("Error", f"Duración inválida en línea:\n{line}")
                return
            pasos.append(Step(
                accion=accion,
                duracion=dur,
                agua=kv.get("agua"),
                quimico=kv.get("quimico"),
                velocidad=kv.get("velocidad"),
            ))

        if not pasos:
            messagebox.showwarning("Vacío", "El ciclo no contiene pasos válidos.")
            return

        self.on_save(Cycle(nombre=nombre, pasos=pasos))
        self.destroy()

# =========================
#   MAIN
# =========================

def main():
    ensure_demo_files()
    app = WasherUI()
    # Ejemplo de cómo inyectar lecturas reales si después conectas hardware:
    # app.hw.read_emergency_stop = lambda: GPIO.input(PIN_PARO) == 0   # etc.
    # app.hw.read_suction_sensor = lambda: GPIO.input(PIN_SUCCION) == 1
    app.mainloop()

if __name__ == "__main__":
    main()
