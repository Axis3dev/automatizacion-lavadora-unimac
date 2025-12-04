# -*- coding: utf-8 -*-
"""Ventana de testeo manual de salidas hacia el ESP32.

Provee botones tipo "push" para energizar/desenergizar relés y un
selector exclusivo para las velocidades del VFD.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable

try:
    from .serialconn import SerialConn
except ImportError:  # pragma: no cover - ruta alternativa
    from unimac_ui.serialconn import SerialConn


class OutputTestWindow(tk.Toplevel):
    def __init__(self, master, serial: SerialConn):
        super().__init__(master)
        self.serial = serial
        self.title("Testeo de salidas")
        self.resizable(False, False)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        push_frame = ttk.LabelFrame(root, text="Relés", padding=10)
        push_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        push_frame.columnconfigure(0, weight=1)
        push_frame.columnconfigure(1, weight=1)

        row = 0
        for text, factory in (
            ("Q1", lambda on: {"cmd": "out", "target": "Q1", "on": 1 if on else 0}),
            ("Q2", lambda on: {"cmd": "out", "target": "Q2", "on": 1 if on else 0}),
            ("Q3", lambda on: {"cmd": "out", "target": "Q3", "on": 1 if on else 0}),
            ("Q4", lambda on: {"cmd": "out", "target": "Q4", "on": 1 if on else 0}),
            ("Agua fría", lambda on: {"cmd": "out", "target": "WATER_COLD", "on": 1 if on else 0}),
            ("Agua caliente", lambda on: {"cmd": "out", "target": "WATER_HOT", "on": 1 if on else 0}),
            ("Drenaje", lambda on: {"cmd": "out", "target": "DRAIN", "on": 1 if on else 0}),
            ("Cerrojo puerta", lambda on: {"cmd": "out", "target": "DOOR_LOCK", "on": 1 if on else 0}),
            ("Motor FWD", lambda on: {"cmd": "motor", "dir": "FWD" if on else "STOP"}),
            ("Motor REV", lambda on: {"cmd": "motor", "dir": "REV" if on else "STOP"}),
            ("Buzzer", lambda on: {"cmd": "buzzer", "on": bool(on)}),
        ):
            btn = self._make_push_button(push_frame, text, factory)
            btn.grid(row=row // 2, column=row % 2, padx=4, pady=4, sticky="ew")
            row += 1

        speed_frame = ttk.LabelFrame(root, text="Velocidad VFD", padding=10)
        speed_frame.grid(row=0, column=1, sticky="nsew")
        self.speed_var = tk.StringVar(value="none")
        for idx, (label, value) in enumerate((
            ("Sin velocidad", "none"),
            ("Bajo", "bajo"),
            ("Medio", "medio"),
            ("Alto", "alto"),
        )):
            rb = ttk.Radiobutton(speed_frame, text=label, value=value, variable=self.speed_var,
                                 command=lambda val=value: self._set_speed(val))
            rb.grid(row=idx, column=0, sticky="w", pady=2, padx=4)

    def _send(self, payload: dict):
        try:
            self.serial.send_json(payload)
        except Exception:
            pass

    def _make_push_button(self, master, text: str, payload_factory: Callable[[bool], dict]) -> ttk.Button:
        btn = ttk.Button(master, text=text)

        def on_press(_event):
            self._send(payload_factory(True))

        def on_release(_event):
            self._send(payload_factory(False))

        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        return btn

    def _set_speed(self, level: str):
        if level == "none":
            # Usa STOP para dejar las salidas de velocidad desenergizadas
            self._send({"cmd": "motor", "dir": "STOP"})
            return
        self._send({"cmd": "vfd_speed", "level": level})
