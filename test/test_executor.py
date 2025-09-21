# tests/test_executor.py
import sys
from pathlib import Path

# Agregar raíz del proyecto al sys.path (para que encuentre core/ y Serial/)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.params_parser import load_params_txt
from core.executor import Executor

def main():
    # Construir ruta al TXT desde la raíz del proyecto
    ruta = ROOT / "ciclos" / "test.txt"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de parámetros: {ruta}")

    params = load_params_txt(ruta)
    print("Params cargados:\n", params)

    print("\n=== EJECUCIÓN EN DRY-RUN ===\n")
    exe = Executor(dry_run=True)
    exe.ejecutar(params)
    exe.cerrar()

    # --- LIVE (ESP32) ---
    # print("\n=== EJECUCIÓN EN LIVE ===\n")
    # exe2 = Executor(serial_port="COM3", dry_run=False)  # o /dev/ttyUSB0 en RPi
    # exe2.ejecutar(params)
    # exe2.cerrar()

if __name__ == "__main__":
    main()
