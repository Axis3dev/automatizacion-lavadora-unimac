# -*- coding: utf-8 -*-
import os
import json
import time
import threading
from typing import Optional, List, Dict

try:
    import serial
    from serial.tools import list_ports
except Exception:
    serial = None
    list_ports = None

# ========= Config persistente =========
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config() -> Dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg: Dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

CFG: Dict = load_config()
CFG.setdefault("globals", {})
CFG["globals"].setdefault("water_fill_seconds", {"ligero": 5, "estandar": 8, "intenso": 12})

# ========= Defaults de serial =========
BAUDRATE: int = int(CFG.get("baudrate", 115200))
PREFERRED_PORT: Optional[str] = CFG.get("serial_port")

# ========= Puertos bloqueados (Raspberry UART del sistema) =========
BLOCKED_PORTS = ("/dev/ttyAMA0", "ttyAMA0")

def _is_blocked_port(name: Optional[str]) -> bool:
    if not name:
        return False
    return name.endswith(BLOCKED_PORTS[1]) or name == BLOCKED_PORTS[0]


class SerialConn:
    """
    Envoltura simple para pyserial con:
    - open/cerrar
    - autoconexión
    - envío JSON por línea
    - lista de puertos (filtrada)
    """
    def __init__(self, baudrate: int = BAUDRATE, preferred_port: Optional[str] = PREFERRED_PORT):
        self.baudrate = baudrate
        self.preferred_port = preferred_port
        self.port_name: Optional[str] = None
        self._lock = threading.Lock()
        self._ser = None  # type: ignore # type: Optional[serial.Serial]

    # ---- utilidades ----
    def list_ports(self) -> List[str]:
        ports = []
        try:
            if list_ports:
                ports = [p.device for p in list_ports.comports()]
        except Exception:
            ports = []
        # filtra bloqueados
        ports = [p for p in ports if not _is_blocked_port(p)]
        return ports

    def is_connected(self) -> bool:
        try:
            return bool(self._ser and self._ser.is_open)
        except Exception:
            return False

    # ---- conexión ----
    def connect(self, port_name: str) -> bool:
        """Conecta a un puerto específico. Devuelve True/False."""
        if _is_blocked_port(port_name):
            self.port_name = None
            return False
        if serial is None:
            return False

        with self._lock:
            try:
                # Cierra si estaba abierto
                if self._ser and self._ser.is_open:
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None

                self._ser = serial.Serial(
                    port=port_name,
                    baudrate=int(self.baudrate or 115200),
                    timeout=0.1,
                    write_timeout=0.2
                )
                self.port_name = port_name

                # persiste preferencia
                self.preferred_port = port_name
                CFG["serial_port"] = port_name
                CFG["baudrate"] = int(self.baudrate or 115200)
                save_config(CFG)

                return True
            except Exception:
                self._ser = None
                self.port_name = None
                return False

    def connect_auto(self) -> bool:
        """Intenta conectar usando preferred_port y luego el resto."""
        # 1) preferred_port primero (si no está bloqueado)
        if self.preferred_port and not _is_blocked_port(self.preferred_port):
            if self.connect(self.preferred_port):
                return True

        # 2) otros puertos
        for p in self.list_ports():
            if self.connect(p):
                return True

        return False

    def close(self):
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                self.port_name = None

    # ---- IO ----
    def send_line(self, line: str) -> bool:
        if not self.is_connected():
            return False
        try:
            data = (line.rstrip("\n") + "\n").encode("utf-8")
            with self._lock:
                self._ser.write(data)
            return True
        except Exception:
            return False

    def send_json(self, obj: Dict) -> bool:
        import json as _json
        try:
            line = _json.dumps(obj, ensure_ascii=False)
        except Exception:
            return False
        return self.send_line(line)

    def read_line(self, timeout: float = 0.0) -> Optional[str]:
        """Lee una línea si hay datos; si timeout>0, espera un poco."""
        if not self.is_connected():
            return None
        end_t = time.time() + max(0.0, timeout)
        try:
            while True:
                with self._lock:
                    if self._ser.in_waiting:
                        raw = self._ser.readline()
                    else:
                        raw = b""
                if raw:
                    try:
                        return raw.decode("utf-8", errors="ignore").rstrip("\r\n")
                    except Exception:
                        return None
                if timeout <= 0.0 or time.time() >= end_t:
                    return None
                time.sleep(0.01)
        except Exception:
            return None


class CommWatcher(threading.Thread):
    """
    Hilo que vigila la conexión y reintenta automáticamente.
    """
    def __init__(self, serial_conn: SerialConn, poll_sec: float = 1.0):
        super().__init__(daemon=True)
        self.serial = serial_conn
        self.poll_sec = poll_sec
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                if not self.serial.is_connected():
                    # Evitar puertos bloqueados en auto
                    self.serial.connect_auto()
            except Exception:
                pass
            # pausa
            for _ in range(int(self.poll_sec * 10)):
                if self._stop.is_set():
                    break
                time.sleep(0.1)

    def stop(self):
        self._stop.set()
