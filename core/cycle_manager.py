from pathlib import Path
import os

# Carpeta base del proyecto = carpeta donde está main.py
BASE_DIR = Path(__file__).resolve().parents[1]
CICLOS_DIR = BASE_DIR / "ciclos"

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

def crear_ciclo(nombre):
    carpeta = asegurar_carpeta_ciclos()
    ruta = carpeta / f"{nombre}.txt"

    if ruta.exists():
        return f"⚠️ El ciclo '{nombre}' ya existe."

    # ---- Interactivo para definir el ciclo ----
    print("Creando ciclo de lavado...\n")

    # LAVADO
    llenado_agua = input("⏱️ Tiempo de llenado de agua para lavado (segundos): ")
    dosificar = input("💧 Químicos a dosificar (ejemplo A,B o deja vacío si ninguno): ")
    lavado = input("⏱️ Tiempo total de lavado (segundos): ")

    # ENJUAGUE
    num_enjuagues = input("🔁 Número de enjuagues: ")
    llenado_enjuague = input("⏱️ Tiempo de llenado de agua para enjuague (segundos): ")
    tiempo_enjuague = input("⏱️ Tiempo de enjuague (segundos): ")

    # CENTRIFUGADO
    balanceo = input("⚖️ Tiempo de balanceo (segundos): ")
    centrifugado = input("🌀 Tiempo de centrifugado (segundos): ")

    # ---- Estructura final ----
    contenido = f"""# Ciclo de Lavado Completo

[lavado]
llenado_agua = {llenado_agua}, baja
dosificar = {dosificar}
lavado = {lavado}, baja

[enjuague]
num_enjuagues = {num_enjuagues}
llenado_agua = {llenado_enjuague}, baja
enjuague = {tiempo_enjuague}, baja

[centrifugado]
balanceo = {balanceo}, baja
centrifugado = {centrifugado}, alta

[fin]
"""

    with open(ruta, "w") as archivo:
        archivo.write(contenido)

    return f"✅ Ciclo '{nombre}' creado correctamente."


def eliminar_ciclo(nombre):
    carpeta = asegurar_carpeta_ciclos()
    ruta = carpeta / f"{nombre}.txt"

    if ruta.exists():
        os.remove(ruta)
        return f"🗑️ Ciclo '{nombre}' eliminado correctamente."
    else:
        return f"⚠️ El ciclo '{nombre}' no existe."
