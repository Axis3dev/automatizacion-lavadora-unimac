# -*- coding: utf-8 -*-
"""Motor de ejecución de ciclos.

Gestiona tiempos de pasos, alternancia de motor, llenado, dosificación y
pausas de drenaje utilizando el reloj monotónico para evitar saltos de hora.
"""

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

try:
    from .serialconn import CFG
except ImportError:
    try:
        from unimac_ui.serialconn import CFG
    except Exception:  # pragma: no cover
        CFG = {"globals": {}}


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
    HOLD = "HOLD"  # compatibilidad histórica (no usado)
    STOPPED = "STOPPED"

    _MODE_STEP = "STEP"
    _MODE_DRAIN = "DRAIN_PAUSE"

    WATER_ACTIONS = {"prelavado", "lavado", "enjuague"}
    SPIN_ACTIONS = {"centrifugado", "spin"}
    DRAIN_ACTIONS = {"drenaje", "descarga"}

    def __init__(self,
                 hw,
                 on_status: Callable[[str], None],
                 on_tick: Callable[[int, int, int], None],
                 on_step_change: Callable[[int], None],
                 on_finish: Callable[[], None],
                 controller=None,
                 send_event: Optional[Callable[[Dict], None]] = None,
                 get_fill_seconds: Optional[Callable[[], Dict[str, int]]] = None,
                 get_chem_seconds: Optional[Callable[[], Dict[str, int]]] = None,
                 get_drain_seconds: Optional[Callable[[], Dict[str, int]]] = None,
                 get_motor_alt_seconds: Optional[Callable[[], int]] = None,
                 get_motor_pause_seconds: Optional[Callable[[], int]] = None):
        self.hw = hw
        self.cb = TickCallbacks(on_status, on_tick, on_step_change, on_finish)
        self.controller = controller
        self._send_event = send_event or (lambda payload: None)
        self._get_fill_seconds = get_fill_seconds or (lambda: {"ligero": 5, "estandar": 8, "intenso": 12})
        self._get_chem_seconds = get_chem_seconds or (lambda: {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 2})
        self._get_drain_seconds = get_drain_seconds or (lambda: {"ligero": 20, "estandar": 30, "intenso": 45})
        self._get_motor_alt_seconds = get_motor_alt_seconds or (lambda: 0)

        def _default_pause():
            try:
                return CFG.get("globals", {}).get("motor_pause_seconds", 2)
            except Exception:
                return 2

        self._get_motor_pause_seconds = get_motor_pause_seconds or _default_pause

        self.state = Executor.IDLE
        self.cycle = None
        self.step_index = 0
        self.step_remaining = 0
        self.total_remaining = 0
        self._last_tick = time.monotonic()
        self._tick_fraction = 0.0

        self._mode = Executor._MODE_STEP
        self._drain_remaining = 0
        self._current_step = None
        self._current_action = ""
        self._current_level = "estandar"
        self._agua_temp = None

        self._motor_speed = "medio"
        self._motor_dir = "FWD"
        self._motor_running = False
        self._motor_interval = 0
        self._motor_timer = 0
        self._motor_pause_duration = 0
        self._motor_pause_timer = 0
        self._motor_pause_active = False
        self._motor_next_dir = "FWD"
        self._motor_is_agitation = False
        self.in_drain_pause = False
        self._drain_profile = None
        self._drain_label = None
        self.ui_send_event = getattr(self, "ui_send_event", None)
        self.current_speed: Optional[str] = None
        self.serial = None
        self.cfg_fill: Dict[str, int] = {}
        self.cfg_chems: Dict[str, int] = {}
        self.cfg_motor: Dict[str, int] = {}

    # ---------- utilidades de configuración ----------
    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _fill_seconds(self, level: Optional[str]) -> int:
        table = getattr(self, "cfg_fill", None) or {}
        if not table:
            table = self._get_fill_seconds() or {}
        key = (level or "estandar").strip().lower()
        return self._safe_int(table.get(key, table.get("estandar", 8)), 8)

    def _chem_seconds(self, ident: str) -> int:
        table = getattr(self, "cfg_chems", None) or {}
        if not table:
            table = self._get_chem_seconds() or {}
        value = table.get(ident)
        if value is None and ident in ("Q1", "Q2", "Q3", "Q4"):
            mapping = {
                "Q1": table.get("detergente"),
                "Q2": table.get("quitamanchas"),
                "Q3": table.get("suavizante"),
                "Q4": table.get("blanqueador"),
            }
            value = mapping.get(ident)
        return self._safe_int(0 if value is None else value, 0)

    def _drain_seconds(self, level: Optional[str]) -> int:
        table = self._get_drain_seconds() or {}
        key = (level or "estandar").strip().lower()
        return self._safe_int(table.get(key, table.get("estandar", 30)), 30)

    def _motor_alt_seconds(self) -> int:
        cfg_motor = getattr(self, "cfg_motor", None) or {}
        if cfg_motor and "alt_every_s" in cfg_motor:
            return max(0, self._safe_int(cfg_motor.get("alt_every_s", 0), 0))
        return max(0, self._safe_int(self._get_motor_alt_seconds() or 0, 0))

    def _motor_pause_seconds(self) -> int:
        cfg_motor = getattr(self, "cfg_motor", None) or {}
        if cfg_motor and "alt_pause_s" in cfg_motor:
            return max(0, self._safe_int(cfg_motor.get("alt_pause_s", 0), 0))
        getter = getattr(self, "_get_motor_pause_seconds", None)
        try:
            value = getter() if getter else 0
        except Exception:
            value = 0
        return max(0, self._safe_int(value, 0))

    @staticmethod
    def _normalize_level(level: Optional[str]) -> str:
        key = (level or "estandar").strip().lower()
        if key not in ("ligero", "estandar", "intenso"):
            key = "estandar"
        return key

    @staticmethod
    def _normalize_speed(speed: Optional[str]) -> str:
        spd = (speed or "medio").strip().lower()
        if spd not in ("bajo", "medio", "alto"):
            spd = "medio"
        return spd

    @staticmethod
    def _drain_profile_info(level: Optional[str]):
        key = Executor._normalize_level(level)
        if key == "ligero":
            return "ligero", "DRENAJE LIGERO"
        if key == "intenso":
            return "intenso", "DRENAJE INTENSO"
        return "estandar", "DRENAJE ESTANDAR"

    @staticmethod
    def _chem_ident(name: str) -> Optional[str]:
        if not name:
            return None
        key = name.strip().lower()
        mapping = {
            "detergente": "detergente",
            "quitamanchas": "quitamanchas",
            "quitamancha": "quitamanchas",
            "suavizante": "suavizante",
            "blanqueador": "blanqueador",
            "cloro": "blanqueador",
            "q1": "detergente",
            "q2": "quitamanchas",
            "q3": "suavizante",
            "q4": "blanqueador",
        }
        return mapping.get(key)

    def _chem_hw_ident(self, ident: str) -> str:
        return {
            "detergente": "Q1",
            "quitamanchas": "Q2",
            "suavizante": "Q3",
            "blanqueador": "Q4",
        }.get(ident, ident)

    # ---------- ciclo ----------
    def load_cycle(self, cycle):
        self.cycle = cycle
        self.reset_runtime()

    def reset_runtime(self):
        self.state = Executor.IDLE
        self.step_index = 0
        self.step_remaining = self.cycle.pasos[0].duracion if (self.cycle and self.cycle.pasos) else 0
        self.total_remaining = self.cycle.total_duracion if self.cycle else 0
        self._last_tick = time.monotonic()
        self._tick_fraction = 0.0
        self._mode = Executor._MODE_STEP
        self._drain_remaining = 0
        self._current_step = None
        self._motor_running = False
        self._drain_profile = None
        self._drain_label = None
        self.current_speed = None

    def start(self):
        if not self.cycle or not self.cycle.pasos:
            self.cb.on_status("No hay ciclo cargado.")
            return

        self.state = Executor.RUNNING
        self.step_index = 0
        self.step_remaining = max(1, self._safe_int(self.cycle.pasos[0].duracion, 1))
        self.total_remaining = self._safe_int(self.cycle.total_duracion, self.step_remaining)
        self._last_tick = time.monotonic()
        self._tick_fraction = 0.0

        self._emit_start_event()
        self._apply_step(self.cycle.pasos[self.step_index])
        self.cb.on_status("Ejecutando")

    def pause(self):
        if self.state == Executor.RUNNING:
            self.state = Executor.PAUSED
            self._set_motor(False)
            self.hw.stop_all()
            if self.controller and hasattr(self.controller, "cancel_all"):
                self.controller.cancel_all()
            self._send_event({"event": "pause", "reason": "user"})
            self.cb.on_status("Pausado")
        elif self.state == Executor.PAUSED:
            self.state = Executor.RUNNING
            self._last_tick = time.monotonic()
            self.cb.on_status("Reanudado")
            if self._current_step:
                self._resume_current_step()
            self._send_event({"event": "resume"})

    def stop(self):
        if self.state == Executor.IDLE:
            return
        self.state = Executor.STOPPED
        self._set_motor(False)
        self.hw.stop_all()
        self.hw.drain_open(True)
        self._send({"cmd": "drain", "open": True})
        if self.controller and hasattr(self.controller, "cancel_all"):
            self.controller.cancel_all()
        self._send_event({"event": "stop"})
        self.cb.on_status("Detenido (paro seguro)")
        self.current_speed = None

    def finish(self):
        self.state = Executor.IDLE
        self._set_motor(False)
        self.hw.stop_all()
        self.hw.drain_open(True)
        self._send({"cmd": "drain", "open": True})
        if self.controller and hasattr(self.controller, "finish_cycle"):
            self.controller.finish_cycle()
        self._send_event({"event": "finish"})
        self.cb.on_status("Ciclo terminado")
        self.cb.on_finish()
        self.current_speed = None

    # ---------- tick principal ----------
    def tick(self):
        if self.hw.is_emergency_pressed():
            self._handle_emergency()
            return

        if self.state in (Executor.IDLE, Executor.PAUSED, Executor.STOPPED):
            self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            return

        now = time.monotonic()
        elapsed = now - self._last_tick
        if elapsed <= 0:
            self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            return

        secs = int(elapsed)
        self._tick_fraction += elapsed - secs
        if self._tick_fraction >= 1.0:
            secs += int(self._tick_fraction)
            self._tick_fraction %= 1.0

        if secs <= 0:
            self._last_tick = now
            self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)
            return

        self._last_tick = now

        for _ in range(secs):
            if self._mode == Executor._MODE_STEP:
                self._tick_step()
            elif self._mode == Executor._MODE_DRAIN:
                self._tick_drain()

            if self.state != Executor.RUNNING:
                break

        self.cb.on_tick(self.step_index, self.step_remaining, self.total_remaining)

    # ---------- lógica de tick ----------
    def _tick_step(self):
        if self.step_remaining > 0:
            self.step_remaining = max(0, self.step_remaining - 1)
        if self.total_remaining > 0:
            self.total_remaining = max(0, self.total_remaining - 1)

        self._update_motor_alt()

        if self.step_remaining <= 0:
            self._complete_step()

    def _tick_drain(self):
        if self._drain_remaining > 0:
            self._drain_remaining = max(0, self._drain_remaining - 1)
        if self.total_remaining > 0:
            self.total_remaining = max(0, self.total_remaining - 1)

        if self._drain_remaining <= 0:
            self.hw.drain_open(False)
            self._send({"cmd": "drain", "open": False})
            payload = {"event": "drain", "open": False}
            if self._drain_profile:
                payload["profile"] = self._drain_profile
            if self._drain_label:
                payload["label"] = self._drain_label
            self._send_event(payload)
            if self.controller and hasattr(self.controller, "close_drain"):
                self.controller.close_drain()
            self.in_drain_pause = False
            self._drain_profile = None
            self._drain_label = None
            self._advance_step()

    # ---------- helpers ----------
    def _handle_emergency(self):
        self.state = Executor.STOPPED
        self._set_motor(False)
        self.hw.stop_all()
        if self.controller and hasattr(self.controller, "cancel_all"):
            self.controller.cancel_all()
        self.hw.drain_open(True)
        self._send_event({"event": "emergency"})
        self.cb.on_status("Paro de emergencia")
        self.current_speed = None

    def _send(self, payload: Dict) -> None:
        serial = getattr(self, "serial", None)
        if serial and hasattr(serial, "send_json"):
            try:
                serial.send_json(payload)
            except Exception:
                pass

    def _emit_start_event(self):
        total = self._safe_int(getattr(self.cycle, "total_duracion", 0), 0)
        steps = len(getattr(self.cycle, "pasos", []))
        name = getattr(self.cycle, "nombre", "")
        self._send_event({"event": "start", "cycle": name, "steps": steps, "total": total})
        if self.controller and hasattr(self.controller, "start_cycle"):
            self.controller.start_cycle()

    def _apply_step(self, step):
        self._current_step = step
        self._current_action = (getattr(step, "accion", "") or "").strip().lower()
        self._current_level = self._normalize_level(getattr(step, "nivel_agua", None))
        self._agua_temp = getattr(self.cycle, "agua_temp", None)
        default_speed = "alto" if self._current_action in Executor.SPIN_ACTIONS else "medio"
        raw_speed = getattr(step, "velocidad", None) or default_speed
        self._motor_speed = self._normalize_speed(raw_speed)
        self._motor_interval = self._motor_alt_seconds()
        self._motor_pause_duration = self._motor_pause_seconds()
        self._motor_timer = self._motor_interval
        self._motor_pause_timer = 0
        self._motor_pause_active = False
        self._motor_running = False
        self._motor_dir = "FWD"
        self._motor_next_dir = "REV"
        self._motor_is_agitation = self._current_action in Executor.WATER_ACTIONS

        self.step_remaining = max(1, self._safe_int(getattr(step, "duracion", 0), 1))
        self._mode = Executor._MODE_STEP
        self.in_drain_pause = False

        self.cb.on_step_change(self.step_index)

        payload = {
            "event": "step",
            "index": self.step_index,
            "accion": getattr(step, "accion", ""),
            "duracion": self.step_remaining,
            "nivel": getattr(step, "nivel_agua", None),
            "quimicos": list(getattr(step, "quimicos", []) or []),
            "velocidad": getattr(step, "velocidad", None),
        }
        self._send_event(payload)

        self.hw.stop_all()

        if self._current_action in Executor.WATER_ACTIONS:
            self._apply_speed_for_step(step)
            self._start_water_step(step)
        elif self._current_action in Executor.SPIN_ACTIONS:
            self._start_spin_step(step)
        elif self._current_action in Executor.DRAIN_ACTIONS:
            self._start_drain_step(step)
        else:
            print(f"[EXEC] Paso desconocido: {self._current_action}")

    def _start_water_step(self, step):
        print(f"[EXEC] Iniciando paso de agua: {self._current_action}")
        self.hw.drain_open(False)
        self._send({"cmd": "drain", "open": False})
        payload = {"event": "drain", "open": False, "seconds": 0}
        if self._drain_profile:
            payload["profile"] = self._drain_profile
        if self._drain_label:
            payload["label"] = self._drain_label
        self._send_event(payload)
        fill_seconds = self._fill_seconds(self._current_level)
        temp_event = (self._agua_temp or "fria").strip().lower()
        self.hw.fill(temp_event, self._current_level)
        self._send({
            "cmd": "fill",
            "temp": temp_event,
            "nivel": self._current_level,
            "t_s": fill_seconds,
        })
        self._send_event({"event": "fill", "temp": temp_event, "seconds": fill_seconds})
        if self.controller and hasattr(self.controller, "begin_fill"):
            self.controller.begin_fill(self._current_level, self._agua_temp)

        chemicals = getattr(step, "quimicos", []) or []
        for chem in chemicals:
            ident = self._chem_ident(chem)
            if not ident:
                continue
            hw_ident = self._chem_hw_ident(ident)
            secs = self._chem_seconds(hw_ident)
            if secs <= 0:
                continue
            self.hw.add_chemical(chem)
            self._send({"cmd": "chem", "id": ident, "t_s": secs})
            self._send_event({"event": "chem", "id": ident, "seconds": secs})
            if self.controller and hasattr(self.controller, "dose"):
                self.controller.dose(hw_ident, secs)

        self._start_motor()

    def _start_spin_step(self, step):
        print(f"[EXEC] Iniciando centrifugado")
        self.hw.drain_open(True)
        self._send({"cmd": "drain", "open": True})
        self._send_event({"event": "drain", "open": True, "seconds": self.step_remaining})
        speed = self._apply_speed_for_step(step)
        self.hw.spin(speed)
        self._set_motor(True, direction="FWD")
        if self.controller and hasattr(self.controller, "run_drain"):
            self.controller.run_drain(self.step_remaining)

    def _start_drain_step(self, step):
        print(f"[EXEC] Iniciando drenaje explícito")
        self._set_motor(False)
        self.hw.drain_open(True)
        self._send({"cmd": "drain", "open": True})
        self._send_event({"event": "drain", "open": True, "seconds": self.step_remaining})
        if self.controller and hasattr(self.controller, "run_drain"):
            self.controller.run_drain(self.step_remaining)

    def _apply_speed_for_step(self, step) -> str:
        default_speed = "alto" if self._current_action in Executor.SPIN_ACTIONS else "medio"
        raw_speed = getattr(step, "velocidad", None) or default_speed
        normalized = self._normalize_speed(raw_speed)
        self._motor_speed = normalized
        if normalized != self.current_speed:
            self.current_speed = normalized
            self._send({"cmd": "vfd_speed", "level": normalized})
            dispatcher = getattr(self, "ui_send_event", None)
            if callable(dispatcher):
                dispatcher("speed", valor=normalized)
            else:
                self._send_event({"event": "speed", "nivel": normalized})
        return normalized

    def _resume_current_step(self):
        if not self._current_step:
            return
        if self._current_action in Executor.WATER_ACTIONS:
            self._start_motor()
        elif self._current_action in Executor.SPIN_ACTIONS:
            self._set_motor(True, direction=self._motor_dir)

    def _complete_step(self):
        print("[EXEC] Paso completado")
        self._set_motor(False)
        self._motor_pause_active = False
        self._motor_pause_timer = 0
        if self._current_action in Executor.WATER_ACTIONS:
            drain = self._drain_seconds(self._current_level)
            if drain > 0:
                self._mode = Executor._MODE_DRAIN
                self._drain_remaining = drain
                self.in_drain_pause = True
                self.cb.on_status("Drenando…")
                self.hw.drain_open(True)
                self._send({"cmd": "drain", "open": True})
                profile, label = self._drain_profile_info(self._current_level)
                self._drain_profile = profile
                self._drain_label = label
                self._send_event({
                    "event": "drain",
                    "open": True,
                    "seconds": drain,
                    "profile": profile,
                    "label": label,
                })
                self._send_event({"event": "pause", "reason": "drain_pause", "seconds": drain})
                if self.controller and hasattr(self.controller, "run_drain"):
                    self.controller.run_drain(drain)
                return
        self.in_drain_pause = False
        self._drain_profile = None
        self._drain_label = None
        self._advance_step()

    def _advance_step(self):
        self.step_index += 1
        if not self.cycle or self.step_index >= len(self.cycle.pasos):
            self.finish()
            return
        self._apply_step(self.cycle.pasos[self.step_index])

    def _start_motor(self):
        self._motor_dir = "FWD"
        self._motor_interval = self._motor_alt_seconds()
        self._motor_pause_duration = self._motor_pause_seconds()
        self._motor_timer = self._motor_interval
        self._motor_pause_timer = 0
        self._motor_pause_active = False
        self._motor_next_dir = "REV"
        self._set_motor(True, direction=self._motor_dir)

    def _set_motor(self, run: bool, direction: Optional[str] = None):
        if direction:
            self._motor_dir = direction
        self._motor_running = run
        if run:
            event = "motor_fwd" if self._motor_dir == "FWD" else "motor_rev"
            cmd_dir = "FWD" if self._motor_dir == "FWD" else "REV"
        else:
            event = "motor_off"
            cmd_dir = "STOP"
        self._send({"cmd": "motor", "dir": cmd_dir})
        self._send_event({"event": event})
        if self.controller and hasattr(self.controller, "motor"):
            self.controller.motor(run=run, direction=self._motor_dir, speed=self._motor_speed)

    def _update_motor_alt(self):
        if not self._motor_is_agitation:
            return
        if self._motor_interval <= 0:
            return

        if self._motor_pause_active:
            if self._motor_pause_timer > 0:
                self._motor_pause_timer = max(0, self._motor_pause_timer - 1)
            if self._motor_pause_timer > 0:
                return
            self._motor_pause_active = False
            next_dir = self._motor_next_dir or ("REV" if self._motor_dir == "FWD" else "FWD")
            print(f"[EXEC] Alternando motor a {next_dir}")
            self._set_motor(True, direction=next_dir)
            self._motor_timer = self._motor_interval
            self._motor_next_dir = "REV" if next_dir == "FWD" else "FWD"
            return

        if not self._motor_running:
            return

        if self._motor_timer > 0:
            self._motor_timer -= 1
        if self._motor_timer > 0:
            return

        next_dir = "REV" if self._motor_dir == "FWD" else "FWD"
        pause = self._motor_pause_duration
        if pause > 0:
            print(f"[EXEC] Pausa de alternancia ({pause}s)")
            self._motor_pause_active = True
            self._motor_pause_timer = pause
            self._motor_next_dir = next_dir
            if self._motor_running:
                self._set_motor(False)
            return

        print(f"[EXEC] Alternando motor a {next_dir}")
        self._set_motor(True, direction=next_dir)
        self._motor_timer = self._motor_interval
        self._motor_next_dir = "REV" if next_dir == "FWD" else "FWD"

    def on_serial_reconnected(self):
        if not self.current_speed:
            return
        self._send({"cmd": "vfd_speed", "level": self.current_speed})
        dispatcher = getattr(self, "ui_send_event", None)
        if callable(dispatcher):
            dispatcher("speed", valor=self.current_speed)
        else:
            self._send_event({"event": "speed", "nivel": self.current_speed})

