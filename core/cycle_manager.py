# core/cycle_manager.py
from pathlib import Path
import os

# Carpeta base del proyecto (la que contiene main.py)
BASE_DIR = Path(__file__).resolve().parents[1]
CICLOS_DIR = BASE_DIR / "ciclos"

# ---------------- Utilidades internas (inputs validados) ---------------- #

def _ask_int(prompt: str, default: int = 0) -> int:
    """
    Pide un entero >= 0. No acepta 's' ni decimales.
    Enter para usar el valor por defecto.
    """
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        if raw.lower().endswith("s"):
            print("  -> No pongas 's'. Solo número en segundos.")
            continue
        try:
            n = int(raw)
            if n < 0:
                print("  -> Debe ser >= 0.")
                continue
            return n
        except ValueError:
            print("  -> Número inválido.")

def _ask_vel(prompt: str, default: str = "BAJA") -> str:
    """
    Pide una velocidad válida: BAJA | MEDIA | ALTA.
    Enter para usar el valor por defecto.
    """
    opciones = {"BAJA", "MEDIA", "ALTA"}
    while True:
        raw = input(f"{prompt} [ {default} ] (BAJA/MEDIA/ALTA): ").strip().upper()
        if raw == "":
            return default
        if raw in opciones:
            return raw
        print("  -> Velocidad inválida. Usa BAJA, MEDIA o ALTA.")

def _ask_dosificar() -> str:
    """
    Pide los tiempos de dosificación por químico (A,B,C,D).
    Devuelve un string EXACTO para el parser: A:seg,B:seg,C:seg,D:seg
    """
    print("💧 Dosificación de químicos (segundos). Deja vacío para 0.")
    vals = {}
    for k in ("A", "B", "C", "D"):
        vals[k] = _ask_int(f"  Tiempo {k} (s)", 0)
    return f"A:{vals['A']},B:{vals['B']},C:{vals['C']},D:{vals['D']}"

# ---------------- API pública del gestor de ciclos ---------------- #

def asegurar_carpeta_ciclos() -> Path:
    """
    Crea la carpeta 'ciclos' si no existe y devuelve su ruta.
    """
    CICLOS_DIR.mkdir(parents=True, exist_ok=True)
    return CICLOS_DIR

def listar_ciclos() -> list[str]:
    """
    Devuelve una lista de nombres de ciclos (sin extensión) encontrados en la carpeta 'ciclos'.
    """
    asegurar_carpeta_ciclos()
    return sorted([p.stem for p in CICLOS_DIR.glob("*.txt")])

def crear_ciclo(nombre: str) -> str:
    """
    Crea un archivo .txt con la PLANTILLA ESTÁNDAR de parámetros
    totalmente alineada con core/params_parser.py
    """
    carpeta = asegurar_carpeta_ciclos()
    ruta = carpeta / f"{nombre}.txt"

    if ruta.exists():
        return f"⚠️ El ciclo '{nombre}' ya existe."

    print("\nCreando ciclo de lavado (formato estándar)...\n")

    # ----- LAVADO -----
    llenado_lav = _ask_int("⏱️ LAVADO: tiempo de llenado de agua (segundos)", 120)
    dosificar = _ask_dosificar()
    agitar_lav = _ask_int("⏱️ LAVADO: tiempo de agitación (segundos)", 600)
    vel_lav = _ask_vel("⚙️  LAVADO: velocidad", "BAJA")

    # ----- ENJUAGUE -----
    rep_enj = _ask_int("🔁 ENJUAGUE: número de enjuagues", 2)
    llenado_enj = _ask_int("⏱️ ENJUAGUE: tiempo de llenado (segundos)", 100)
    agitar_enj = _ask_int("⏱️ ENJUAGUE: tiempo de agitación (segundos)", 300)
    vel_enj = _ask_vel("⚙️  ENJUAGUE: velocidad", "BAJA")

    # ----- CENTRIFUGADO -----
    balanceo = _ask_int("⚖️ CENTRIFUGADO: tiempo de balanceo (segundos)", 60)
    centrif = _ask_int("🌀 CENTRIFUGADO: tiempo de centrifugado (segundos)", 300)
    vel_cen = _ask_vel("⚙️  CENTRIFUGADO: velocidad", "ALTA")

    contenido = f"""[LAVADO]
LLENADO_S={llenado_lav}
DOSIFICAR={dosificar}
AGITAR_S={agitar_lav}
VEL={vel_lav}

[ENJUAGUE]
REPETICIONES={rep_enj}
LLENADO_S={llenado_enj}
AGITAR_S={agitar_enj}
VEL={vel_enj}

[CENTRIFUGADO]
BALANCEO_S={balanceo}
CENTRIFUGADO_S={centrif}
VEL={vel_cen}
"""

    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)

    return f"✅ Ciclo '{nombre}' creado correctamente en {ruta}"

def eliminar_ciclo(nombre: str) -> str:
    """
    Elimina el archivo .txt del ciclo indicado (si existe).
    """
    carpeta = asegurar_carpeta_ciclos()
    ruta = carpeta / f"{nombre}.txt"

    if ruta.exists():
        os.remove(ruta)
        return f"🗑️ Ciclo '{nombre}' eliminado correctamente."
    else:
        return f"⚠️ El ciclo '{nombre}' no existe."
