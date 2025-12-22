#!/usr/bin/env python3
"""Prueba rápida del SerialManager sin GUI."""
import json
import time

from unimac_serial.serial_manager import SerialManager


def main():
    mgr = SerialManager()
    mgr.start()
    deadline = time.time() + 5.0
    while time.time() < deadline and not mgr.is_connected():
        time.sleep(0.2)
    print(f"[SERIAL] connected={mgr.is_connected()} port={mgr.port_path} label={mgr.port_label}")
    if mgr.is_connected():
        mgr.send_line('{"cmd":"door?"}\n')
        time.sleep(1.0)
    mgr.stop()


if __name__ == "__main__":
    main()
