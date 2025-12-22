# -*- coding: utf-8 -*-
import os
from typing import List, Dict
from .models import Step, Cycle

# Colocar los .txt en la carpeta 'ciclos' en la raíz del proyecto
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CICLOS_DIR = os.path.join(BASE_DIR, "ciclos")

def ensure_demo_files():
    """
    ANTES: creaba 'Ciclo_Rapido' y 'Ciclo_Industrial'.
    AHORA: solo asegura la carpeta. No crea archivos demo.
    """
    os.makedirs(CICLOS_DIR, exist_ok=True)

def purge_demo_cycles():
    """
    Elimina ciclos de demostración si aún existieran en disco.
    (Incluye variantes con/ sin acentos para mayor robustez.)
    """
    demos = [
        "Ciclo_Rapido.txt",
        "Ciclo_Industrial.txt",
        "Ciclo rapido.txt",
        "Ciclo industrial.txt",
        "Ciclo Rápido.txt",
        "Ciclo Industrial.txt",
    ]
    for name in demos:
        path = os.path.join(CICLOS_DIR, name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                # Si no se puede borrar, continuamos sin romper la app
                pass

def parse_kv(seg: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for par in seg.split(";"):
        if not par.strip():
            continue
        if "=" in par:
            k, v = par.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out

def load_cycle_from_txt(path: str) -> Cycle:
    nombre = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
    pasos = []
    agua_temp = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("nombre="):
                nombre = line.split("=", 1)[1].strip()
                continue
            if line.lower().startswith("temp_agua="):
                agua_temp = line.split("=", 1)[1].strip().lower()
                continue
            kv = parse_kv(line)
            acc = kv.get("accion")
            dur = kv.get("duracion")
            if not acc or not dur:
                continue
            try:
                dur = int(dur)
            except ValueError:
                continue
            nivel = kv.get("nivel")
            qraw = kv.get("quimicos") or ""
            chems = [c.strip() for c in qraw.replace("|", ",").split(",") if c.strip()]
            vel = kv.get("velocidad") or "medio"
            pasos.append(Step(acc, dur, nivel, chems, vel))
    return Cycle(nombre, pasos, agua_temp)

def save_cycle_to_txt(cycle: Cycle, path: str):
    lines = [f"nombre={cycle.nombre}"]
    if getattr(cycle, "agua_temp", None):
        lines.append(f"temp_agua={cycle.agua_temp}")
    for s in cycle.pasos:
        segs = [f"accion={s.accion}", f"duracion={s.duracion}"]
        if getattr(s, "nivel_agua", None):
            segs.append(f"nivel={s.nivel_agua}")
        if getattr(s, "quimicos", None):
            segs.append("quimicos=" + ",".join(s.quimicos))
        if getattr(s, "velocidad", None):
            segs.append(f"velocidad={s.velocidad}")
        lines.append(";".join(segs))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def list_cycles() -> List[str]:
    # Ya NO crea demos; solo asegura carpeta
    ensure_demo_files()
    return sorted([f for f in os.listdir(CICLOS_DIR) if f.lower().endswith(".txt")])
