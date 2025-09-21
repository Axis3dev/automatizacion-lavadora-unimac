# core/executor.py
import time
from typing import Dict
from .params_model import CicloParams
try:
    from nSerial.serial_manager import SerialManager
except Exception:
    SerialManager = None  # permite dry-run sin serial

class Executor:
    def __init__(self, serial_port: str | None = None, dry_run: bool = False):
        """
        dry_run=True => imprime comandos en consola, no usa serial.
        serial_port=None => auto-detecta (si SerialManager lo implementa así).
        """
        self.dry_run = dry_run
        self.sm = None
        if not dry_run and SerialManager is not None:
            self.sm = SerialManager(port=serial_port)

    # ---------- utilidades ----------
    def _log(self, msg: str):
        print(msg)

    def _cmd(self, comando: str, wait_reply: bool = True):
        if self.dry_run or self.sm is None:
            self._log(f"[CMD] {comando}")
            return "OK (dry-run)"
        return self.sm.enviar_comando(comando, wait_reply=wait_reply)

    def _esperar(self, s: int):
        self._log(f"[WAIT] {s}s")
        t0 = time.time()
        while time.time() - t0 < s:
            time.sleep(0.05)

    def _dosificar(self, d: Dict[str, int]):
        # d = {"A":seg, "B":seg, "C":seg, "D":seg}
        for key, seg in d.items():
            if seg > 0:
                self._cmd(f"DOSIF_{key}_ON")
                self._esperar(seg)
                self._cmd(f"DOSIF_{key}_OFF")

    # ---------- etapas ----------
    def _etapa_lavado(self, p):
        # llenado
        if p.llenado_s > 0:
            self._log("== LAVADO: Llenado de agua ==")
            self._cmd("VALVULA_AGUA_ON")
            self._esperar(p.llenado_s)
            self._cmd("VALVULA_AGUA_OFF")

        # dosificar
        if any(v > 0 for v in p.dosificar.values()):
            self._log("== LAVADO: Dosificación ==")
            self._dosificar(p.dosificar)

        # agitar
        if p.agitar_s > 0:
            self._log(f"== LAVADO: Agitar ({p.vel}) ==")
            self._cmd(f"MOTOR_{p.vel}_AUTO_ON")
            self._esperar(p.agitar_s)
            self._cmd("MOTOR_OFF")

    def _etapa_enjuague(self, p):
        for rep in range(max(0, p.repeticiones)):
            self._log(f"== ENJUAGUE ({rep+1}/{p.repeticiones}) ==")
            if p.llenado_s > 0:
                self._cmd("VALVULA_AGUA_ON")
                self._esperar(p.llenado_s)
                self._cmd("VALVULA_AGUA_OFF")
            if p.agitar_s > 0:
                self._cmd(f"MOTOR_{p.vel}_AUTO_ON")
                self._esperar(p.agitar_s)
                self._cmd("MOTOR_OFF")
            # drenado fijo 20s entre enjuagues
            self._cmd("BOMBA_ON")
            self._esperar(20)
            self._cmd("BOMBA_OFF")

    def _etapa_centrifugado(self, p):
        if p.balanceo_s > 0:
            self._log("== CENTRIFUGADO: Balanceo ==")
            self._cmd("MOTOR_BAJA_AUTO_ON")
            self._esperar(p.balanceo_s)
            self._cmd("MOTOR_OFF")
        if p.centrifugado_s > 0:
            # drenado breve de seguridad
            self._log("== CENTRIFUGADO: Drenado breve ==")
            self._cmd("BOMBA_ON")
            self._esperar(10)
            self._cmd("BOMBA_OFF")
            # centrifugar
            self._log(f"== CENTRIFUGADO: Giro ({p.vel}) ==")
            self._cmd(f"MOTOR_{p.vel}_FIJA_ON")
            self._esperar(p.centrifugado_s)
            self._cmd("MOTOR_OFF")

    # ---------- orquestación ----------
    def ejecutar(self, params: CicloParams):
        self._log("=== INICIO DE CICLO ===")
        self._etapa_lavado(params.lavado)
        self._etapa_enjuague(params.enjuague)
        self._etapa_centrifugado(params.centrifugado)
        self._log("=== FIN DE CICLO ===")

    def cerrar(self):
        if self.sm:
            self.sm.cerrar()
