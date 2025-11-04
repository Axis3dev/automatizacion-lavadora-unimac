# -*- coding: utf-8 -*-
import threading
import unicodedata
from typing import Callable, Dict, Optional


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace(" ", "").replace("-", "").upper()


def _safe_int(value, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return default


class HardwareIO:
    """Stub de hardware — remplázalo por GPIO/Modbus/PLC en producción."""

    def __init__(self,
                 get_fill_seconds: Optional[Callable[[], Dict[str, int]]] = None,
                 get_dose_seconds: Optional[Callable[[], Dict[str, int]]] = None):
        self.get_fill_seconds = get_fill_seconds or (lambda: {"ligero": 5, "estandar": 8, "intenso": 12})
        self.get_dose_seconds = get_dose_seconds or (lambda: {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 2})
        self._fill_timer: Optional[threading.Timer] = None
        self._chem_timers: Dict[str, threading.Timer] = {}

    def _cancel_timer(self, timer: Optional[threading.Timer]):
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

    def _fill_seconds_for(self, level: Optional[str]) -> int:
        table = self.get_fill_seconds() or {}
        key = (level or "estandar").strip().lower()
        return _safe_int(table.get(key, table.get("estandar", 8)), 8)

    def _dose_seconds_for(self, ident: str) -> int:
        table = self.get_dose_seconds() or {}
        return _safe_int(table.get(ident, 0), 0)

    def fill(self, temp: Optional[str], nivel: Optional[str] = None):
        """Activa la válvula de agua respetando el nivel configurado.

        Mantiene compatibilidad con llamadas heredadas donde el primer
        parámetro correspondía al nivel en lugar de la temperatura.
        """
        water = (temp or "").strip().lower() if temp else None
        level = nivel
        if level is None and water not in {None, "fria", "fría", "caliente", "tibia"}:
            # Compatibilidad con firmas antiguas: fill(nivel)
            level = water
            water = None

        secs = self._fill_seconds_for(level)
        self._cancel_timer(self._fill_timer)
        if secs > 0:
            descr = level or "estandar"
            if water:
                descr = f"{descr} / agua {water}"
            print(f"[HW] Llenando agua ({descr}) durante {secs}s")

            def _on_finish():
                print("[HW] Llenado completado")

            self._fill_timer = threading.Timer(secs, _on_finish)
            self._fill_timer.daemon = True
            self._fill_timer.start()
        else:
            descr = level or "estandar"
            if water:
                descr = f"{descr} / agua {water}"
            print(f"[HW] Llenando agua ({descr})")

    CHEM_LABELS = {
        "Q1": "Detergente",
        "Q2": "Quitamanchas",
        "Q3": "Suavizante",
        "Q4": "Blanqueador",
    }
    CHEM_ALIASES = {
        "DETERGENTE": "Q1",
        "QUITAMANCHAS": "Q2",
        "QUITAMANCHA": "Q2",
        "SUAVIZANTE": "Q3",
        "BLANQUEADOR": "Q4",
        "CLORO": "Q4",
    }

    def add_chemical(self, ident):
        if not ident:
            return
        key = str(ident).strip()
        norm = _normalize(key)
        hw_ident = self.CHEM_ALIASES.get(norm, key.upper())
        pretty = self.CHEM_LABELS.get(hw_ident, key)
        secs = self._dose_seconds_for(hw_ident)
        timer = self._chem_timers.pop(hw_ident, None)
        self._cancel_timer(timer)
        if secs > 0:
            print(f"[HW] Dosificando {pretty} ({hw_ident}) durante {secs}s")

            def _done():
                print(f"[HW] {pretty} completado")

            timer = threading.Timer(secs, _done)
            timer.daemon = True
            self._chem_timers[hw_ident] = timer
            timer.start()
        else:
            print(f"[HW] Dosificando {pretty} ({hw_ident})")

    def drain_open(self, enable: bool):
        print(f"[HW] Drenaje {'ABIERTO' if enable else 'CERRADO'}")

    def spin(self, level):
        if level:
            print(f"[HW] Spin {level}")

    def stop_all(self):
        self._cancel_timer(self._fill_timer)
        self._fill_timer = None
        for timer in list(self._chem_timers.values()):
            self._cancel_timer(timer)
        self._chem_timers.clear()
        print("[HW] Paro seguro")

    def is_emergency_pressed(self) -> bool:
        """Indica si el paro de emergencia esté presionado.

        En esta implementación stub devuelve False. Reemplazar por lectura real
        de GPIO/entrada cuando se integre el hardware.
        """
        return False
