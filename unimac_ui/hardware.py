# -*- coding: utf-8 -*-
import unicodedata


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace(" ", "").replace("-", "").upper()


class HardwareIO:
    """Stub de hardware — remplázalo por GPIO/Modbus/PLC en producción."""
    def fill(self, temp):
        print(f"[HW] Llenando agua: {temp or 'N/A'}")

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
        print(f"[HW] Químico {pretty} ({hw_ident})")

    def drain_open(self, enable: bool):
        print(f"[HW] Drenaje {'ABIERTO' if enable else 'CERRADO'}")

    def spin(self, level):
        if level:
            print(f"[HW] Spin {level}")

    def stop_all(self):
        print("[HW] Paro seguro")
    
    def is_emergency_pressed(self) -> bool:
        """Indica si el paro de emergencia esté presionado.

        En esta implementación stub devuelve False. Reemplazar por lectura real
        de GPIO/entrada cuando se integre el hardware.
        """
        return False
