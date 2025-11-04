# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import List, Optional

CHEMICALS = ["Detergente", "Quitamanchas", "Suavizante", "Blanqueador"]
NIVELES_AGUA = ["Ligero", "Estándar", "Intenso"]
VELOCIDADES = ["bajo", "medio", "alto"]

@dataclass
class Step:
    accion: str
    duracion: int                  # en segundos
    nivel_agua: Optional[str] = None
    quimicos: List[str] = field(default_factory=list)
    velocidad: Optional[str] = None

    def to_human(self, idx: int) -> str:
        parts = [f"Paso {idx}: {self.accion.capitalize()} - {self.duracion // 60} min"]
        if self.nivel_agua: parts.append(f"Nivel {self.nivel_agua}")
        if self.quimicos: parts.append("Químicos: " + ", ".join(self.quimicos))
        if self.velocidad: parts.append(f"Velocidad {self.velocidad.capitalize()}")
        return " · ".join(parts)

@dataclass
class Cycle:
    nombre: str
    pasos: List[Step] = field(default_factory=list)
    agua_temp: Optional[str] = None  # 'fria' | 'caliente'

    @property
    def total_duracion(self) -> int:
        return sum(p.duracion for p in self.pasos)
