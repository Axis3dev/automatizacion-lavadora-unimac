from __future__ import annotations
from pathlib import Path
from typing import Dict, Tuple
from .params_model import LavadoParams, EnjuagueParams, CentrifugadoParams, CicloParams

SECCIONES_ESPERADAS = ("LAVADO", "ENJUAGUE", "CENTRIFUGADO")
VEL_VALIDAS = {"BAJA", "MEDIA", "ALTA"}

def _parse_kv(line: str) -> Tuple[str, str]:
    k, v = line.split("=", 1)
    return k.strip().upper(), v.strip()

def _parse_int(val: str, ctx: str) -> int:
    if val.lower().endswith("s"):
        raise ValueError(f"{ctx}: no pongas 's' (segundos). Usa solo número entero. Valor recibido: {val}")
    try:
        n = int(val)
    except Exception:
        raise ValueError(f"{ctx}: debe ser entero. Valor recibido: {val}")
    if n < 0:
        raise ValueError(f"{ctx}: no puede ser negativo. Valor recibido: {val}")
    return n

def _parse_vel(val: str, ctx: str) -> str:
    v = (val or "").strip().upper()
    if v not in VEL_VALIDAS:
        raise ValueError(f"{ctx}: VEL inválida '{val}'. Usa una de {sorted(VEL_VALIDAS)}")
    return v

def _parse_dosificar(raw: str) -> Dict[str, int]:
    """
    DOSIFICAR=A:15,B:10,C:0,D:0
    → {"A":15, "B":10, "C":0, "D":0}
    Claves faltantes se rellenan con 0.
    """
    res = {"A": 0, "B": 0, "C": 0, "D": 0}
    raw = (raw or "").strip()
    if not raw:
        return res
    parts = [p for p in raw.split(",") if p.strip()]
    for p in parts:
        if ":" not in p:
            raise ValueError(f"DOSIFICAR: formato inválido en '{p}'. Usa A:seg,B:seg,C:seg,D:seg")
        k, v = p.split(":", 1)
        k = k.strip().upper()
        if k not in res:
            raise ValueError(f"DOSIFICAR: clave desconocida '{k}'. Usa solo A, B, C, D.")
        res[k] = _parse_int(v.strip(), f"DOSIFICAR.{k}")
    return res

def _leer_secciones(path: Path) -> Dict[str, Dict[str, str]]:
    """
    Devuelve un dict por sección con claves en MAYÚSCULAS y valores crudos (strings).
    Ignora líneas vacías y comentarios (#).
    """
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo: {path}")

    data: Dict[str, Dict[str, str]] = {}
    section: str | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().upper()
            data.setdefault(section, {})
            continue
        if "=" in line and section:
            k, v = _parse_kv(line)
            data[section][k] = v
        # líneas sin "=" se ignoran silenciosamente (permite comentarios sin '#')
    return data

def _validar_secciones_presentes(data: Dict[str, Dict[str, str]]):
    faltantes = [s for s in SECCIONES_ESPERADAS if s not in data]
    if faltantes:
        raise ValueError(f"Faltan secciones: {faltantes}. Deben existir {list(SECCIONES_ESPERADAS)}")

def load_params_txt(path: Path) -> CicloParams:
    """
    Lee un TXT de parámetros y devuelve un CicloParams listo para ejecutar.
    Reglas:
      - Segundos = enteros sin 's'
      - VEL ∈ {BAJA, MEDIA, ALTA}
      - DOSIFICAR con claves A,B,C,D (faltantes → 0)
      - ENJUAGUE.REPETICIONES ≥ 0
    """
    data = _leer_secciones(path)
    _validar_secciones_presentes(data)

    # ----- LAVADO -----
    sec = "LAVADO"
    llenado_s = _parse_int(data[sec].get("LLENADO_S", "0"), f"[{sec}] LLENADO_S")
    dosificar = _parse_dosificar(data[sec].get("DOSIFICAR", ""))
    agitar_s = _parse_int(data[sec].get("AGITAR_S", "0"), f"[{sec}] AGITAR_S")
    vel_lav = _parse_vel(data[sec].get("VEL", "BAJA"), f"[{sec}] VEL")

    lavado = LavadoParams(
        llenado_s=llenado_s,
        dosificar=dosificar,
        agitar_s=agitar_s,
        vel=vel_lav
    )

    # ----- ENJUAGUE -----
    sec = "ENJUAGUE"
    repeticiones = _parse_int(data[sec].get("REPETICIONES", "0"), f"[{sec}] REPETICIONES")
    llenado_s = _parse_int(data[sec].get("LLENADO_S", "0"), f"[{sec}] LLENADO_S")
    agitar_s = _parse_int(data[sec].get("AGITAR_S", "0"), f"[{sec}] AGITAR_S")
    vel_enj = _parse_vel(data[sec].get("VEL", "BAJA"), f"[{sec}] VEL")

    enjuague = EnjuagueParams(
        repeticiones=repeticiones,
        llenado_s=llenado_s,
        agitar_s=agitar_s,
        vel=vel_enj
    )

    # ----- CENTRIFUGADO -----
    sec = "CENTRIFUGADO"
    balanceo_s = _parse_int(data[sec].get("BALANCEO_S", "0"), f"[{sec}] BALANCEO_S")
    centrifugado_s = _parse_int(data[sec].get("CENTRIFUGADO_S", "0"), f"[{sec}] CENTRIFUGADO_S")
    vel_cen = _parse_vel(data[sec].get("VEL", "ALTA"), f"[{sec}] VEL")

    centrifugado = CentrifugadoParams(
        balanceo_s=balanceo_s,
        centrifugado_s=centrifugado_s,
        vel=vel_cen
    )

    # Reglas mínimas adicionales (puedes ampliar):
    # - Enjuague.repeticiones >= 0 (ya validado por _parse_int)
    # - Si hay centrifugado>0, el Executor hará drenado breve antes (regla en ejecución)

    return CicloParams(
        lavado=lavado,
        enjuague=enjuague,
        centrifugado=centrifugado
    )
