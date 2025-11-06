# -*- coding: utf-8 -*-
"""Gestión de conexión serie y vigilancia de puertos para ESP32."""

import json
import os
import re
import sys
import threading
import time
from typing import Callable, Iterable, List, Optional

try:  # pragma: no cover - importación opcional
    import serial  # type: ignore
    from serial import Serial, SerialException  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:  # pragma: no cover - entorno sin pyserial
    serial = None  # type: ignore
    Serial = None  # type: ignore
    SerialException = Exception  # type: ignore
    list_ports = None  # type: ignore

BLOCKED_PORTS = ("/dev/ttyAMA0", "ttyAMA0")


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    except Exception:
        pass


CFG = load_config()
BAUDRATE = int(CFG.get("baudrate", 115200) or 115200)
PREFERRED_PORT = CFG.get("serial_port")


def _is_blocked_port(port: Optional[str]) -> bool:
    if not port:
        return False
    return port == BLOCKED_PORTS[0] or port.endswith(BLOCKED_PORTS[1])


def _discover_ports() -> List[str]:
    ports: List[str] = []

    # 1) Enumeración estándar de pyserial
    try:
        if list_ports:
            ports = [p.device for p in list_ports.comports()]
            if not ports:
                try:
                    ports = [p.device for p in list_ports.comports(include_links=True)]
                except TypeError:
                    ports = [p.device for p in list_ports.comports()]
    except Exception:
        ports = []

    plat = sys.platform.lower()

    # Linux: excluir únicamente /dev/ttyAMA0
    if "linux" in plat:
        ports = [p for p in ports if p and not p.endswith("ttyAMA0")]

    # Windows: fallback si pyserial no devolvió nada
    if plat.startswith("win") and not ports:
        com_pattern = re.compile(r"^COM\d+$", re.IGNORECASE)
        candidates = [f"COM{i}" for i in range(1, 257)]
        validated: List[str] = []
        try:
            if list_ports:
                existing = {p.device.upper() for p in list_ports.comports()}
                validated = [c for c in candidates if c.upper() in existing and com_pattern.match(c)]
        except Exception:
            validated = []

        if not validated:
            try:  # Último recurso: QueryDosDeviceW para detectar puertos reales
                import ctypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                buffer_len = 1024
                for cand in candidates:
                    buf = ctypes.create_unicode_buffer(buffer_len)  # type: ignore[attr-defined]
                    res = kernel32.QueryDosDeviceW(cand, buf, buffer_len)
                    if res != 0 and com_pattern.match(cand):
                        validated.append(cand)
                    else:
                        err = ctypes.GetLastError()
                        if err == 122 and com_pattern.match(cand):  # ERROR_INSUFFICIENT_BUFFER
                            validated.append(cand)
                        kernel32.SetLastError(0)
            except Exception:
                validated = []

        if not validated:
            validated = [c for c in candidates if com_pattern.match(c)]

        ports = validated

    # macOS: priorizar /dev/cu.*
    if plat == "darwin":
        ports = [p for p in ports if p and "/dev/cu." in p]

    # Deduplicar y ordenar
    uniq: List[str] = []
    seen = set()
    for port in ports:
        if not port:
            continue
        if port in seen:
            continue
        uniq.append(port)
        seen.add(port)

    uniq.sort()

    try:
        import serial  # type: ignore

        print(
            f"[SERIAL] pyserial={getattr(serial, '__version__', 'unknown')} platform={sys.platform} ports={uniq}"
        )
    except Exception:
        print(f"[SERIAL] platform={sys.platform} ports={uniq}")

    return uniq


class SerialConn:
    """Wrapper mínima sobre pyserial con autoconexión y envío JSON."""

    def __init__(self, baudrate: int = BAUDRATE, preferred_port: Optional[str] = PREFERRED_PORT):
        self.baudrate = int(baudrate or 115200)
        self.preferred_port = preferred_port
        self._lock = threading.Lock()
        self.ser: Optional[Serial] = None
        self.port_name: Optional[str] = None

    # ------------------------------- utilidades -------------------------------
    @staticmethod
    def list_available_ports() -> List[str]:
        return _discover_ports()

    def is_connected(self) -> bool:
        try:
            with self._lock:
                ser = self.ser
            return bool(ser and getattr(ser, "is_open", False))
        except Exception:
            return False

    # ------------------------------- conexión --------------------------------
    def close(self) -> None:
        with self._lock:
            ser = self.ser
            self.ser = None
            self.port_name = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass

    def connect(self, port: str) -> bool:
        if not port or _is_blocked_port(port) or serial is None or Serial is None:
            return False

        try:
            self.close()

            kwargs = dict(
                port=port,
                baudrate=int(self.baudrate or 115200),
                timeout=0.1,
                write_timeout=0.5,
                rtscts=False,
                dsrdtr=False,
            )
            if sys.platform.startswith("linux") or sys.platform == "darwin":
                kwargs["exclusive"] = False

            ser = Serial(**kwargs)

            try:
                ser.setDTR(False)
                ser.setRTS(False)
                time.sleep(0.05)
                ser.setDTR(True)
                time.sleep(0.05)
            except Exception:
                pass

            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass

            try:
                ser.write(b'{"cmd":"ping"}\n')
                ser.flush()
                deadline = time.time() + 0.2
                while time.time() < deadline and ser.in_waiting:
                    _ = ser.read(ser.in_waiting)
            except Exception:
                pass

            if not getattr(ser, "is_open", False):
                try:
                    ser.close()
                except Exception:
                    pass
                return False

            with self._lock:
                self.ser = ser
                self.port_name = port
                self.preferred_port = port

            CFG["serial_port"] = port
            CFG["baudrate"] = self.baudrate
            save_config(CFG)
            return True
        except Exception as exc:
            print(f"[SERIAL][connect] Error abriendo {port}: {exc}")
            self.close()
            return False

    def connect_auto(self) -> bool:
        preferred = self.preferred_port
        if preferred and not _is_blocked_port(preferred):
            if self.connect(preferred):
                return True

        for port in self.list_available_ports():
            if _is_blocked_port(port):
                continue
            if preferred and port == preferred:
                continue
            if self.connect(port):
                return True
        return False

    # -------------------------------- envío ----------------------------------
    def send_json(self, payload: dict) -> bool:
        if not self.is_connected():
            print("[SER] drop send_json: not connected")
            return False
        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        data = (line + "\n").encode("utf-8")
        with self._lock:
            ser = self.ser
        if not ser or not getattr(ser, "is_open", False):
            print("[SER] drop send_json: port closed")
            return False
        try:
            with self._lock:
                ser.write(data)
                ser.flush()
        except (SerialException, OSError) as exc:
            print(f"[SERIAL][send_json] Error: {exc}")
            self.close()
            return False
        print(f"[SER→ESP] {line}")
        return True

    # ------------------------------- vigilancia -------------------------------
    def _alive_touch(self) -> bool:
        with self._lock:
            ser = self.ser
        if not ser or not ser.is_open:
            return False
        try:
            _ = ser.in_waiting
            return True
        except (SerialException, OSError):
            self.close()
            return False


class CommWatcher(threading.Thread):
    """Hilo que vigila el estado de la conexión y reconecta automáticamente."""

    def __init__(
        self,
        serial_conn: SerialConn,
        poll_sec: float = 0.5,
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        tk_after: Optional[Callable[[int, Callable[[], None]], None]] = None,
    ) -> None:
        super().__init__(daemon=True)
        self.serial = serial_conn
        self.poll_sec = max(0.1, float(poll_sec) if poll_sec else 0.5)
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._tk_after = tk_after
        self._stop = threading.Event()
        self._last_connected = self.serial.is_connected()
        self._last_port = self.serial.port_name

    # ------------------------------ utilidades --------------------------------
    def _emit(self, callback: Optional[Callable], *args) -> None:
        if not callback:
            return
        if self._tk_after:
            try:
                self._tk_after(0, lambda: callback(*args))
            except Exception:
                pass
            return
        try:
            callback(*args)
        except Exception:
            pass

    def _sleep(self) -> None:
        end = time.time() + self.poll_sec
        while not self._stop.is_set() and time.time() < end:
            time.sleep(0.1)

    def _attempt_reconnect(self, available_ports: Iterable[str]) -> bool:
        ports = [p for p in available_ports if not _is_blocked_port(p)]
        target = self.serial.preferred_port
        if target and not _is_blocked_port(target):
            if target not in ports:
                ports.insert(0, target)
            else:
                ports.remove(target)
                ports.insert(0, target)
        else:
            target = None
        for port in ports:
            if self.serial.connect(port):
                return True
        if not target:
            for port in self.serial.list_available_ports():
                if _is_blocked_port(port):
                    continue
                if self.serial.connect(port):
                    return True
        return False

    # --------------------------------- hilo -----------------------------------
    def run(self) -> None:
        if self._last_connected and self._last_port:
            self._emit(self._on_connect, self._last_port)

        while not self._stop.is_set():
            try:
                connected = self.serial.is_connected()
                current_port = self.serial.port_name
                available_ports = list(self.serial.list_available_ports())
                port_present = current_port in available_ports if current_port else False
                alive = self.serial._alive_touch() if connected else False

                if connected and (not port_present or not alive):
                    self.serial.close()
                    connected = False
                    current_port = None

                if connected:
                    if not self._last_connected:
                        self._last_connected = True
                        self._last_port = current_port
                        if current_port:
                            self._emit(self._on_connect, current_port)
                else:
                    if self._last_connected:
                        self._last_connected = False
                        self._last_port = None
                        self._emit(self._on_disconnect)

                    if self._attempt_reconnect(available_ports):
                        self._last_connected = True
                        self._last_port = self.serial.port_name
                        if self._last_port:
                            self._emit(self._on_connect, self._last_port)
            except Exception:
                if self.serial.is_connected():
                    self.serial.close()
                if self._last_connected:
                    self._last_connected = False
                    self._last_port = None
                    self._emit(self._on_disconnect)
            self._sleep()

    def stop(self) -> None:
        self._stop.set()
