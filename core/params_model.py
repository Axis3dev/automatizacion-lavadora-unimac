from dataclasses import dataclass
from typing import Dict

@dataclass
class LavadoParams:
    llenado_s: int               # Segundos de llenado
    dosificar: Dict[str, int]    # {"A":int,"B":int,"C":int,"D":int}
    agitar_s: int                # Segundos de agitación
    vel: str                     # BAJA | MEDIA | ALTA

@dataclass
class EnjuagueParams:
    repeticiones: int            # Número de enjuagues
    llenado_s: int               # Segundos de llenado
    agitar_s: int                # Segundos de agitación
    vel: str                     # BAJA | MEDIA | ALTA

@dataclass
class CentrifugadoParams:
    balanceo_s: int              # Segundos de balanceo previo
    centrifugado_s: int          # Segundos de centrifugado
    vel: str                     # BAJA | MEDIA | ALTA

@dataclass
class CicloParams:
    lavado: LavadoParams
    enjuague: EnjuagueParams
    centrifugado: CentrifugadoParams
