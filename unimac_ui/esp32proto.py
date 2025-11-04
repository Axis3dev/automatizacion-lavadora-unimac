# -*- coding: utf-8 -*-
"""
Control de ESP32 (orquestador de comandos).
- Alternancia de giro durante agitación (configurable).
- Dosificación Q1..Q4 usando segundos definidos por GUI.
- Drenaje entre pasos lo controla main; aquí NO se abre al final de pasos con agua.
"""

from typing import Callable, Optional, List, Dict

class Esp32Controller:
    def __init__(self,
                 after: Callable[[int, Callable], None],
                 send: Callable[[Dict], None],
                 on_info: Optional[Callable[[str], None]] = None,
                 get_dose_seconds: Optional[Callable[[], Dict[str,int]]] = None,
                 get_alt_seconds: Optional[Callable[[], int]] = None):
        self.after = after
        self.send = send
        self.on_info = on_info or (lambda s: None)
        self.get_dose_seconds = get_dose_seconds or (lambda: {"Q1":4,"Q2":3,"Q3":2,"Q4":2})
        self.get_alt_seconds = get_alt_seconds or (lambda: 0)

        self._agitate_toggle_job = None
        self._agitate_stop_job = None
        self._current_dir = "cw"

    # ---------- util ----------
    def _after(self, ms: int, cb: Callable):
        return self.after(max(0, int(ms)), cb)

    def _out(self, target: str, on: int):
        self.send({"cmd": "out", "target": target, "on": 1 if on else 0})

    def _dose(self, which: str, seconds: int):
        self.send({"cmd": "dose", "which": which, "seconds": max(0, int(seconds))})

    def _vfd(self, run: str = "off", dir: str = "cw", speed: str = "low"):
        self.send({"cmd": "vfd", "run": run, "dir": dir, "speed": speed})

    def _beep(self, ms: int = 120):
        self.send({"cmd": "beep", "ms": int(max(30, ms))})

    # ---------- ciclo ----------
    def start_cycle(self):
        # Drenaje (NA) cerrar = energizado
        self._out("DRAIN", 1)
        # Cerrar puerta
        self._out("DOOR_LOCK", 1)
        self._beep(80)
        self.on_info("Ciclo iniciado.")

    def finish_cycle(self):
        # Paro seguro
        self._vfd(run="off")
        self._out("WATER_COLD", 0)
        self._out("WATER_HOT", 0)
        self._out("Q1", 0); self._out("Q2", 0); self._out("Q3", 0); self._out("Q4", 0)
        # Drenaje NA: abrir
        self._out("DRAIN", 0)
        # Abrir puerta
        self._out("DOOR_LOCK", 0)
        self._beep(160)
        self.on_info("Ciclo terminado.")

    def cancel_all(self):
        # Paro inmediato
        self._vfd(run="off")
        self._out("WATER_COLD", 0)
        self._out("WATER_HOT", 0)
        self._out("Q1", 0); self._out("Q2", 0); self._out("Q3", 0); self._out("Q4", 0)
        # Drenaje NA: abrir
        self._out("DRAIN", 0)
        # Cancelar alternancia
        self._cancel_agitate_jobs()

    # ---------- pasos ----------
    def run_step(self, accion: str, duracion: int,
                 nivel_agua: Optional[str] = None,
                 agua: Optional[str] = None,
                 quimicos: Optional[List[str]] = None,
                 velocidad: Optional[str] = None):
        a = (accion or "").strip().lower()
        quimicos = quimicos or []

        if a in ("prelavado", "lavado", "enjuague"):
            self._run_fill_agitate(agua=agua, quimicos=quimicos, duracion=duracion, velocidad=velocidad)
            return
        if a in ("centrifugado", "spin"):
            self._run_spin(duracion=duracion, velocidad=velocidad or "alto")
            return
        if a in ("drenaje", "descarga"):
            self._run_drain(duracion=max(0, int(duracion or 0)))
            return

        self._beep(60)  # paso desconocido

    def _run_fill_agitate(self, agua: Optional[str], quimicos: List[str], duracion: int, velocidad: Optional[str]):
        # Agua
        if agua:
            if agua.lower() == "fria":
                self._out("WATER_COLD", 1); self._out("WATER_HOT", 0)
            elif agua.lower() == "caliente":
                self._out("WATER_HOT", 1); self._out("WATER_COLD", 0)
        else:
            self._out("WATER_COLD", 0); self._out("WATER_HOT", 0)

        # Dosificación con segundos reales
        doses = self.get_dose_seconds()
        for q in quimicos:
            ident = str(q).upper()
            if ident in ("Q1", "Q2", "Q3", "Q4"):
                self._dose(ident, int(doses.get(ident, 0)))

        # Agitación con alternancia
        spd = "low"
        v = (velocidad or "").lower()
        if v == "medio": spd = "med"
        elif v == "alto": spd = "high"

        self._current_dir = "cw"
        self._vfd(run="on", dir=self._current_dir, speed=spd)
        self._beep(70)

        alt = max(0, int(self.get_alt_seconds() or 0))
        if alt > 0:
            self._schedule_toggle(alt, spd)

        # Final del periodo
        self._agitate_stop_job = self._after(int(max(0, duracion)) * 1000, self._end_step_no_drain)

    def _schedule_toggle(self, alt_sec: int, spd: str):
        def toggle():
            self._current_dir = "ccw" if self._current_dir == "cw" else "cw"
            self._vfd(run="on", dir=self._current_dir, speed=spd)
            self._agitate_toggle_job = self._after(alt_sec * 1000, toggle)
        self._agitate_toggle_job = self._after(alt_sec * 1000, toggle)

    def _cancel_agitate_jobs(self):
        # No hay cancelación directa de after; se re-sincroniza en fin de paso
        self._agitate_toggle_job = None
        self._agitate_stop_job = None

    def _end_step_no_drain(self):
        # Parar agitación y agua/químicos
        self._vfd(run="off")
        self._out("WATER_COLD", 0)
        self._out("WATER_HOT", 0)
        self._out("Q1", 0); self._out("Q2", 0); self._out("Q3", 0); self._out("Q4", 0)
        self._beep(100)
        self._cancel_agitate_jobs()

    def _run_spin(self, duracion: int, velocidad: str):
        # Spin: abrir drenaje (NA) y centrifugar
        self._out("WATER_COLD", 0)
        self._out("WATER_HOT", 0)
        self._out("Q1", 0); self._out("Q2", 0); self._out("Q3", 0); self._out("Q4", 0)
        self._out("DRAIN", 0)

        spd = "high"
        v = (velocidad or "").lower()
        if v == "medio": spd = "med"
        elif v == "bajo": spd = "low"

        self._vfd(run="on", dir="cw", speed=spd)
        self._beep(80)

        self._after(int(max(0, duracion)) * 1000, self._end_spin)

    def _end_spin(self):
        self._vfd(run="off")
        self._beep(120)

    # ---- Drenaje público para main ----
    def run_drain(self, duracion: int):
        self._run_drain(duracion=max(0, int(duracion or 0)))

    def _run_drain(self, duracion: int):
        self._out("WATER_COLD", 0)
        self._out("WATER_HOT", 0)
        self._out("Q1", 0); self._out("Q2", 0); self._out("Q3", 0); self._out("Q4", 0)
        self._out("DRAIN", 0)
        self._after(int(max(0, duracion)) * 1000, self._end_drain)

    def _end_drain(self):
        # Cerrar drenaje (NA) para próximo llenado
        self._out("DRAIN", 1)
        self._beep(80)
