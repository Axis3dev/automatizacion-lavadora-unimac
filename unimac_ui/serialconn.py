# -*- coding: utf-8 -*-
"""Gestión de conexión serie y vigilancia de puertos para ESP32."""

import json
import os
import threading
import time
from typing import Callable, Iterable, Optional, Tuple

try:
    from serial import Serial, SerialException  # type: ignore
    from serial.tools import list_ports  # type: ignore
except Exception:  # pragma: no cover - entorno sin pyserial
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


class SerialConn:
    """Wrapper mínima sobre pyserial con autoconexión y envío JSON."""

    def __init__(self, baudrate: int = BAUDRATE, preferred_port: Optional[str] = PREFERRED_PORT):
        self.baudrate = int(baudrate or 115200)
        self.preferred_port = preferred_port
        self._serial: Optional[Serial] = None
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._connect_in_progress = False
        self.port_name: Optional[str] = None
        self._on_json: Optional[Callable[[dict], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_stop: Optional[threading.Event] = None
        self.status: dict = {"door_closed": None}

    # ------------------------------- utilidades -------------------------------
    def _candidate_infos(self) -> Tuple[list, list]:
        preferred: list[str] = []
        others: list[Tuple[int, str]] = []

        if self.preferred_port and not _is_blocked_port(self.preferred_port):
            preferred.append(self.preferred_port)

        if list_ports is None:
            return preferred, []

        try:
            for info in list_ports.comports():
                dev = getattr(info, "device", None)
                if not dev or _is_blocked_port(dev):
                    continue
                desc = (getattr(info, "description", "") or "").lower()
                vid = getattr(info, "vid", None)
                score = 0
                if vid in (0x1A86, 0x10C4, 0x303A):
                    score -= 2
                if "usb" in desc or "serial" in desc or "uart" in desc:
                    score -= 1
                others.append((score, dev))
        except Exception:
            pass

        others.sort()
        return preferred, [dev for _, dev in others]

    def list_ports(self) -> Iterable[str]:
        preferred, others = self._candidate_infos()
        ordered = []
        for dev in preferred:
            if dev not in ordered:
                ordered.append(dev)
        for dev in others:
            if dev not in ordered:
                ordered.append(dev)
        return ordered

    def is_connected(self) -> bool:
        with self._lock:
            ser = self._serial
        return bool(ser and ser.is_open)

    def is_connecting(self) -> bool:
        return self._connect_in_progress

    def _begin_connect(self) -> bool:
        if not self._connect_lock.acquire(blocking=False):
            return False
        self._connect_in_progress = True
        return True

    def _end_connect(self) -> None:
        self._connect_in_progress = False
        try:
            self._connect_lock.release()
        except Exception:
            pass

    # ------------------------------- conexión --------------------------------
    def connect(self, port: str, *, guarded: bool = True) -> bool:
        if guarded and not self._begin_connect():
            return False
        if _is_blocked_port(port) or Serial is None:
            if guarded:
                self._end_connect()
            return False

        try:
            ser = Serial(
                port=port,
                baudrate=self.baudrate,
                timeout=0,
                write_timeout=0.2,
            )
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except (SerialException, OSError, ValueError):
            if guarded:
                self._end_connect()
            return False

        with self._lock:
            if self._serial and self._serial.is_open:
                try:
                    self._serial.close()
                except Exception:
                    pass
            self._serial = ser
            self.port_name = port
            self.preferred_port = port
        CFG["serial_port"] = port
        CFG["baudrate"] = self.baudrate
        save_config(CFG)
        self._start_reader()
        if guarded:
            self._end_connect()
        return True

    def _probe_port(self, port: str, timeout: float = 1.8) -> Tuple[bool, Optional[bool]]:
        if Serial is None:
            return False, None
        try:
            ser = Serial(
                port=port,
                baudrate=self.baudrate,
                timeout=0.12,
                write_timeout=0.3,
                rtscts=False,
                dsrdtr=False,
            )
        except (SerialException, OSError, ValueError):
            return False, None
        try:
            ser.reset_output_buffer()
        except Exception:
            pass
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        try:
            ser.setDTR(False)
            ser.setRTS(False)
        except Exception:
            pass
        try:
            ser.write(b'{"cmd":"door?"}\n')
            ser.flush()
        except Exception:
            pass

        found = False
        door_state: Optional[bool] = None
        buf = bytearray()
        deadline = time.time() + max(0.3, float(timeout))
        while time.time() < deadline:
            try:
                chunk = ser.read(max(1, ser.in_waiting or 0))
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
                    try:
                        obj = json.loads(line)
                    except Exception:
                        obj = None
                    if isinstance(obj, dict):
                        if obj.get("boot") == "ok":
                            found = True
                        if obj.get("event") == "door" and "closed" in obj:
                            door_state = bool(obj.get("closed"))
                            found = True
            else:
                time.sleep(0.05)
        try:
            ser.close()
        except Exception:
            pass
        return found, door_state

    def connect_with_handshake(self, port: str, *, guarded: bool = True) -> bool:
        if guarded and not self._begin_connect():
            return False
        ok, door_state = self._probe_port(port)
        if not ok:
            if guarded:
                self._end_connect()
            return False
        if not self.connect(port, guarded=False):
            if guarded:
                self._end_connect()
            return False
        if door_state is not None:
            self.status["door_closed"] = door_state
            self.status["door_ts"] = time.time()
        else:
            self.send_json({"cmd": "door?"})
        if guarded:
            self._end_connect()
        return True

    def connect_auto(self) -> bool:
        if not self._begin_connect():
            return False
        try:
            for port in self.list_ports():
                if self.connect_with_handshake(port, guarded=False):
                    return True
            return False
        finally:
            self._end_connect()

    def close(self) -> None:
        with self._lock:
            ser = self._serial
            self._serial = None
            self.port_name = None
        self.status["door_closed"] = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        reader = self._reader_thread
        if reader:
            stop_event = self._reader_stop
            if stop_event:
                stop_event.set()
            if reader is not threading.current_thread():
                try:
                    reader.join(timeout=0.5)
                except Exception:
                    pass
            self._reader_thread = None
            self._reader_stop = None

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
            ser = self._serial
        if not ser or not ser.is_open:
            print("[SER] drop send_json: port closed")
            return False
        try:
            with self._lock:
                ser.write(data)
                ser.flush()
        except (SerialException, OSError) as exc:
            print(f"[SER] write error: {exc}")
            self.close()
            return False
        print(f"[SER→ESP] {line}")
        return True

    # --------------------------------- JSON RX ---------------------------------
    def set_on_json(self, cb: Optional[Callable[[dict], None]]) -> None:
        self._on_json = cb

    def _start_reader(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_stop = threading.Event()
        thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread = thread
        thread.start()

    def _reader_loop(self) -> None:
        stop_event = self._reader_stop
        buffer = bytearray()
        while stop_event and not stop_event.is_set():
            with self._lock:
                ser = self._serial
            if not ser or not ser.is_open:
                time.sleep(0.1)
                continue
            try:
                waiting = ser.in_waiting
            except (SerialException, OSError) as exc:
                print(f"[SER] in_waiting error: {exc}")
                self.close()
                time.sleep(0.2)
                continue
            if waiting <= 0:
                time.sleep(0.05)
                continue
            try:
                data = ser.read(waiting)
            except (SerialException, OSError) as exc:
                print(f"[SER] read error: {exc}")
                self.close()
                time.sleep(0.2)
                continue
            if not data:
                time.sleep(0.05)
                continue
            buffer.extend(data)
            while b"\n" in buffer:
                raw_line, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                line = raw_line.strip().decode("utf-8", errors="ignore")
                if not line:
                    continue
                print(f"[ESP→SER] {line}")
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("event") == "door":
                    if "closed" in obj:
                        self.status["door_closed"] = bool(obj.get("closed"))
                    else:
                        self.status["door_closed"] = None
                    self.status["door_ts"] = time.time()
                callback = self._on_json
                if callback:
                    try:
                        callback(obj)
                    except Exception as exc:
                        print(f"[SER] on_json callback error: {exc}")

    # ------------------------------- vigilancia -------------------------------
    def _alive_touch(self) -> bool:
        with self._lock:
            ser = self._serial
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
        self._last_door_poll = 0.0

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
        ports = list(available_ports)
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
            if self.serial.connect_with_handshake(port):
                return True
        if not target:
            for port in self.serial.list_ports():
                if self.serial.connect_with_handshake(port):
                    return True
        return False

    # --------------------------------- hilo -----------------------------------
    def run(self) -> None:
        if self._last_connected and self._last_port:
            self._emit(self._on_connect, self._last_port)

        while not self._stop.is_set():
            try:
                connected = self.serial.is_connected()
                connecting = getattr(self.serial, "is_connecting", lambda: False)()
                current_port = self.serial.port_name
                available_ports = list(self.serial.list_ports())
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
                        self._last_door_poll = 0.0
                        if current_port:
                            self._emit(self._on_connect, current_port)
                    now = time.time()
                    if now - self._last_door_poll >= 1.5:
                        if self.serial.send_json({"cmd": "door?"}):
                            self._last_door_poll = now
                        else:
                            self._last_door_poll = now
                else:
                    if self._last_connected:
                        self._last_connected = False
                        self._last_port = None
                        self._emit(self._on_disconnect)
                        self._last_door_poll = 0.0

                    if not connecting and self._attempt_reconnect(available_ports):
                        self._last_connected = True
                        self._last_port = self.serial.port_name
                        self._last_door_poll = 0.0
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
