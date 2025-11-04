# -*- coding: utf-8 -*-
class HardwareIO:
    """Stub de hardware — remplázalo por GPIO/Modbus/PLC en producción."""
    def fill(self, temp):
        print(f"[HW] Llenando agua: {temp or 'N/A'}")

    def add_chemical(self, ident):
        if ident:
            print(f"[HW] Químico {ident}")

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
