# -*- coding: utf-8 -*-
"""Gestor dedicado de conexión serie con reconexión automática.

Arranca en un hilo daemon, prioriza /dev/serial/by-id/CP2102 y
reintenta con backoff suave mientras envía/recibe líneas JSON.
"""
import json
import os
import threading
import time
from typing import Callable, Optional, Iterable, Union

try:
    from serial import Serial, SerialException  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:  # pragma: no cover - entorno sin pyserial
    Serial = None  # type: ignore
    SerialException = Exception  # type: ignore
    list_ports = None  # type: ignore

CONFIG_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "unimac_ui", "config.json"))


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


# --------------------------- utilidades de logging ---------------------------
_last_scan_log = 0.0


def _log(msg: str) -> None:
    print(f"[SERIAL] {msg}")


# ---------------------------- selección de puerto ----------------------------

def short_port_label(path: str) -> str:
    base = os.path.basename(path or "")
    lower = base.lower()
    label = base
    if "cp210" in lower:
        suffix = ""
        if "port" in lower:
            idx = lower.rfind("port")
            if idx >= 0:
                suffix = base[idx:]
        if not suffix:
            # Busca un identificador numérico estable, p.ej. "0001"
            for token in base.replace("-", "_").split("_"):
                if token.isdigit() and len(token) >= 3:
                    suffix = token
                    break
        label = f"CP2102-{suffix or 'dev'}"
    elif "ttyusb0" in lower:
        label = "ttyUSB0"
    elif base:
        label = base
    return label[:15]


def _candidate_ports(preferred: Optional[str]) -> Iterable[str]:
    ports = []
    if preferred:
        ports.append(preferred)

    by_id = "/dev/serial/by-id"
    if os.name != "nt" and os.path.isdir(by_id):
        try:
            for name in sorted(os.listdir(by_id)):
                if "cp2102" not in name.lower() and "cp210" not in name.lower():
                    continue
                path = os.path.join(by_id, name)
                if path not in ports:
                    ports.append(path)
        except Exception:
            pass

    if os.name != "nt":
        fallback = "/dev/ttyUSB0"
        if os.path.exists(fallback) and fallback not in ports:
            ports.append(fallback)

    if list_ports:
        try:
            for info in list_ports.comports():
                dev = getattr(info, "device", None)
                if not dev:
                    continue
                if dev in ports:
                    continue
                ports.append(dev)
        except Exception:
            pass

    return ports


# ----------------------------- SerialManager --------------------------------


class SerialManager:
    def __init__(
        self,
        baudrate: int = BAUDRATE,
        preferred_port: Optional[str] = PREFERRED_PORT,
        on_json: Optional[Callable[[dict], None]] = None,
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        tk_after: Optional[Callable[[int, Callable[[], None]], None]] = None,
    ) -> None:
        self.baudrate = int(baudrate or 115200)
        self.preferred_port = preferred_port
        self._on_json = on_json
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._tk_after = tk_after

        self._serial: Optional[Serial] = None
        self._serial_lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._next_attempt = 0.0
        self._retry_delay = 1.0
        self._last_ports_repr: Optional[str] = None

        self.port_path: Optional[str] = None
        self.port_label: str = ""
        self._connecting = False

    # ------------------------------- API pública ------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_port()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass

    def set_on_json(self, cb: Optional[Callable[[dict], None]]) -> None:
        self._on_json = cb

    def is_connected(self) -> bool:
        with self._serial_lock:
            ser = self._serial
        return bool(ser and ser.is_open)

    # Métodos auxiliares para UI/otros módulos
    def send_line(self, line: Union[str, bytes]) -> bool:
        data = line if isinstance(line, bytes) else line.encode("utf-8")
        if isinstance(line, str) and not line.endswith("\n"):
            data = (line + "\n").encode("utf-8")
        with self._serial_lock:
            ser = self._serial
        if not ser or not ser.is_open:
            _log("drop send_line: not connected")
            return False
        try:
            with self._serial_lock:
                ser.write(data)
                ser.flush()
            return True
        except (SerialException, OSError) as exc:
            _log(f"write error: {exc}")
            self._handle_disconnect(exc)
            return False

    def send_json(self, payload: dict) -> bool:
        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        return self.send_line(line + "\n")

    def connect_once(self, port: Optional[str]) -> bool:
        """Intento síncrono de conexión con handshake, usado desde Configuración."""
        if not self._begin_connect():
            return False
        try:
            if port:
                self.preferred_port = port
            ok = self._try_connect(port)
            if ok:
                self._retry_delay = 1.0
                CFG["serial_port"] = self.preferred_port or self.port_path or port
                CFG["baudrate"] = self.baudrate
                save_config(CFG)
            return ok
        finally:
            self._end_connect()

    # ----------------------------- hilo principal -----------------------------
    def _run(self) -> None:
        global _last_scan_log
        backoff_cap = 5.0
        while not self._stop.is_set():
            if not self.is_connected():
                now = time.time()
                if now < self._next_attempt:
                    time.sleep(0.2)
                    continue
                for port in _candidate_ports(self.preferred_port):
                    if self._stop.is_set():
                        return
                    if not self._begin_connect():
                        time.sleep(0.2)
                        continue
                    try:
                        label = short_port_label(port)
                        ts = time.time()
                        if ts - _last_scan_log >= 1.0:
                            _last_scan_log = ts
                            _log(f"connect attempt port={port} label={label}")
                        if self._try_connect(port):
                            self._retry_delay = 1.0
                            CFG["serial_port"] = self.preferred_port or port
                            CFG["baudrate"] = self.baudrate
                            save_config(CFG)
                            break
                    finally:
                        self._end_connect()
                else:
                    self._retry_delay = min(backoff_cap, self._retry_delay + 0.5)
                    self._next_attempt = time.time() + self._retry_delay
                    continue
            self._read_loop()

    # ------------------------------- conexión ---------------------------------
    def _begin_connect(self) -> bool:
        locked = self._connect_lock.acquire(blocking=False)
        if locked:
            self._connecting = True
        return locked

    def _end_connect(self) -> None:
        self._connecting = False
        try:
            self._connect_lock.release()
        except Exception:
            pass

    def _try_connect(self, port: Optional[str]) -> bool:
        if Serial is None or not port:
            return False
        try:
            kwargs = dict(port=port, baudrate=self.baudrate, timeout=0.2, write_timeout=0.3)
            try:
                kwargs["exclusive"] = True  # type: ignore[arg-type]
            except Exception:
                pass
            ser = Serial(**kwargs)
        except (SerialException, OSError, ValueError) as exc:
            _log(f"open failed on {port}: {exc}")
            return False
        try:
            ser.reset_output_buffer()
            ser.reset_input_buffer()
            ser.setDTR(False)
            ser.setRTS(False)
        except Exception:
            pass

        if not self._handshake(ser):
            try:
                ser.close()
            except Exception:
                pass
            return False

        with self._serial_lock:
            self._serial = ser
            self.port_path = port
            self.port_label = short_port_label(port)
        _log(f"connected port={port}")
        self._emit_connect(port)
        return True

    def _handshake(self, ser: Serial) -> bool:
        deadline = time.time() + 1.5
        try:
            ser.write(b'{"cmd":"door?"}\n')
            ser.flush()
        except Exception:
            pass
        buf = bytearray()
        found = False
        while time.time() < deadline:
            try:
                chunk = ser.read(max(1, ser.in_waiting or 0) or 1)
            except (SerialException, OSError):
                break
            if chunk:
                buf.extend(chunk)
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    line = raw.strip().decode("utf-8", errors="ignore")
                    if not line:
                        continue
                    if "\"boot\"" in line or "[PINMAP" in line or "\"event\":\"door\"" in line:
                        found = True
                        break
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            if obj.get("boot") == "ok":
                                found = True
                                break
                            if obj.get("event") == "door" and "closed" in obj:
                                found = True
                                break
                    except Exception:
                        continue
            else:
                time.sleep(0.05)
        return found

    # ------------------------------ lectura RX -------------------------------
    def _read_loop(self) -> None:
        while not self._stop.is_set() and self.is_connected():
            with self._serial_lock:
                ser = self._serial
            if not ser:
                break
            try:
                line = ser.readline()
            except (SerialException, OSError) as exc:
                self._handle_disconnect(exc)
                break
            if not line:
                continue
            text = line.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            _log(f"ESP→SER {text}")
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                self._dispatch_json(obj)

    def _dispatch_json(self, obj: dict) -> None:
        cb = self._on_json
        if not cb:
            return
        if self._tk_after:
            try:
                self._tk_after(0, lambda: cb(obj))
                return
            except Exception:
                pass
        try:
            cb(obj)
        except Exception:
            pass

    # ------------------------------ desconexión -------------------------------
    def _handle_disconnect(self, exc: Exception | None = None) -> None:
        if exc:
            _log(f"disconnected err={exc}")
        self._close_port()
        self._emit_disconnect()
        self._next_attempt = time.time() + max(0.5, self._retry_delay)
        self._retry_delay = min(5.0, self._retry_delay + 0.5)

    def _close_port(self) -> None:
        with self._serial_lock:
            ser = self._serial
            self._serial = None
            self.port_path = None
            self.port_label = ""
        if ser:
            try:
                ser.close()
            except Exception:
                pass

    def _emit_connect(self, port: str) -> None:
        cb = self._on_connect
        if not cb:
            return
        if self._tk_after:
            try:
                self._tk_after(0, lambda: cb(port))
                return
            except Exception:
                pass
        try:
            cb(port)
        except Exception:
            pass

    def _emit_disconnect(self) -> None:
        cb = self._on_disconnect
        if not cb:
            return
        if self._tk_after:
            try:
                self._tk_after(0, cb)
                return
            except Exception:
                pass
        try:
            cb()
        except Exception:
            pass


__all__ = [
    "SerialManager",
    "short_port_label",
    "load_config",
    "save_config",
    "CFG",
    "BAUDRATE",
    "PREFERRED_PORT",
]
