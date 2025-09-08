import serial
import time

class SerialManager:
    def __init__(self, port="COM3", baudrate=115200, timeout=1):
        try:
            self.ser = serial.Serial(port, baudrate, timeout=timeout)
            time.sleep(2)  # esperar a que ESP32 arranque
            print(f"✅ Conectado al puerto {port}")
        except Exception as e:
            print(f"❌ Error abriendo puerto serial: {e}")
            self.ser = None

    def enviar_comando(self, comando: str) -> str:
        """
        Envía un comando al ESP32 y devuelve la respuesta
        """
        if not self.ser:
            return "⚠️ Puerto no disponible"

        self.ser.write((comando + "\n").encode())
        respuesta = self.ser.readline().decode().strip()
        return respuesta if respuesta else "⚠️ Sin respuesta"

    def cerrar(self):
        if self.ser:
            self.ser.close()
            print("🔌 Conexión serial cerrada")
