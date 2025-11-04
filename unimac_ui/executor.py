# -*- coding: utf-8 -*-
import time
from typing import Callable, Optional
from dataclasses import dataclass

@dataclass
class TickCallbacks:
    on_status: Callable[[str], None]
    on_tick: Callable[[int, int, int], None]
    on_step_change: Callable[[int], None]
    on_finish: Callable[[], None]

class Executor:
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HOLD = "HOLD"          # Nuevo: pausa dura (no descuenta tiempo) para drenaje/esperas entre pasos
    STOPPED = "STOPPED"

    def __init__(self, hw, on_status, on_tick, on_step_change, on_finish):
        self.hw = hw
        self.cb = TickCallbacks(on_status, on_tick, on_step_change, on_finish)

        self.state = Executor.IDLE
        self.cycle = None
        self.step_index = 0
        self.step_remaining = 0
        self.total_remaining = 0
        self._last_tick = time.time()

        # HOLD
        self._hold_until: Optional[float] = None
        self._hold_label: str = ""

    # -------- ciclo ----------
    def load_cycle(self, cycle):
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
            self.cb.on_status("No hay ciclo cargado.")
            return
        self.state = Executor.RUNNING
        self._last_tick = time.time()
        self._apply_step(self.cycle.pasos[self.step_index])
        self.cb.on_status("Ejecutando")

    def pause(self):
        if self.state == Executor.RUNNING:
            self.state = Executor.PAUSED
            self.hw.stop_all()
            self.cb.on_status("Pausado")
        elif self.state == Executor.PAUSED:
            self.state = Executor.RUNNING
            # Reaplica el paso actual
            self._apply_step(self.cycle.pasos[self.step_index])
            self._last_tick = time.time()
            self.cb.on_status("Reanudado")

    def stop(self):
        self.state = Executor.STOPPED
        self.hw.stop_all()
        self.hw.drain_open(True)  # paro seguro
        self.cb.on_status("Detenido (paro seguro)")

    # -------- HOLD duro (no descuenta tiempo del total) ----------
    def hold_for(self, seconds: int, label: str = ""):
        """Congela contadores durante 'seconds' y muestra 'label'."""
        self.state = Executor.HOLD
        self._hold_until = time.time() + max(0, int(seconds))
        self._hold_label = label or "Esperando…"
        self.cb.on_status(self._hold_label)

    def _clear_hold(self):
        self._hold_until = None
        self._hold_label = ""
        if self.state == Executor.HOLD:
            self.state = Executor.RUNNING
            self._last_tick = time.time()
            self.cb.on_status("Ejecutando")

    # -------- tick ----------
    def tick(self):
        # EMERGENCIA hw
        if self.hw.is_emergency_pressed():
            self.stop()
        # Estados no-running
        if self.state in (Executor.PAUSED, Executor.STOPPED, Executor.IDLE):
            self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            return

        # HOLD: no descontar tiempos
        if self.state == Executor.HOLD:
            # solo refrescar tick, sin restar contadores
            self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            # si termina el hold, quedará a cargo del caller (main) continuar el paso
            return

        # RUNNING
        now = time.time()
        elapsed = now - self._last_tick
        if elapsed >= 1.0:
            secs = int(elapsed)
            self._last_tick = now
            self.step_remaining = max(0, self.step_remaining - secs)
            self.total_remaining = max(0, self.total_remaining - secs)
            if self.step_remaining <= 0:
                self._next_step()

        self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)

    # -------- helpers internos ----------
    def _apply_step(self, step):
        # Apaga todo base
        self.hw.stop_all()
        acc = step.accion.lower()
        if acc in ("prelavado", "lavado", "enjuague"):
            # Llenado + (opcional) químico, sin giro fuerte (la GUI/ESP32 hacen lo suyo)
            # El modelo de datos usa 'nivel_agua' para describir el nivel; usar eso.
            self.hw.fill(getattr(step, 'nivel_agua', None))
        elif acc in ("centrifugado", "spin"):
            self.hw.drain_open(True)
            self.hw.spin(step.velocidad)
        elif acc in ("drenaje", "descarga"):
            self.hw.drain_open(True)
        # tiempo del paso
        self.step_remaining = step.duracion

    def _next_step(self):
        self.step_index += 1
        if not self.cycle or self.step_index >= len(self.cycle.pasos):
            self.finish()
            return
        self.cb.on_step_change(self.step_index)
        self._apply_step(self.cycle.pasos[self.step_index])

    def finish(self):
        self.state = Executor.IDLE
        self.hw.stop_all()
        self.cb.on_status("Ciclo terminado")
        self.cb.on_finish()
