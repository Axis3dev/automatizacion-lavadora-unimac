from core.cycle_manager import asegurar_carpeta_ciclos, listar_ciclos, crear_ciclo, eliminar_ciclo
from Serial.serial_manager import SerialManager

def main():
    asegurar_carpeta_ciclos()

    # Inicializar conexión serial
    serial_manager = SerialManager(port="COM3")  # Ajusta tu puerto aquí

    while True:
        print("\n--- MENÚ ---")
        print("1. Listar ciclos")
        print("2. Crear ciclo")
        print("3. Eliminar ciclo")
        print("4. Enviar comando al ESP32")
        print("5. Salir")
        
        opcion = input("Selecciona una opción: ")

        if opcion == "1":
            ciclos = listar_ciclos()
            print("Ciclos disponibles:", ciclos if ciclos else "No hay ciclos.")

        elif opcion == "2":
            nombre = input("Ingresa el nombre del nuevo ciclo: ")
            print(crear_ciclo(nombre))

        elif opcion == "3":
            ciclos = listar_ciclos()
            if not ciclos:
                print("⚠️ No hay ciclos para eliminar.")
                continue

            print("\nCiclos disponibles para eliminar :")
            for i, ciclo in enumerate(ciclos, 1):
                print(f"{i}. {ciclo}")

            try:
                opcion = int(input("Selecciona el número del ciclo a eliminar: "))
                if 1 <= opcion <= len(ciclos):
                    nombre = ciclos[opcion - 1]
                    print(eliminar_ciclo(nombre))
                else:
                    print("⚠️ Número inválido.")
            except ValueError:
                print("⚠️ Ingresa un número válido.")

        elif opcion == "4":
            comando = input("Escribe el comando a enviar al ESP32: ")
            respuesta = serial_manager.enviar_comando(comando)
            print(f"ESP32 respondió: {respuesta}")

        elif opcion == "5":
            serial_manager.cerrar()
            break

        else:
            print("⚠️ Opción no válida. ")

if __name__ == "__main__":
    main()
