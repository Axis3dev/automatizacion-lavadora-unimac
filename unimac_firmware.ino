#include <Arduino.h>
#include <ArduinoJson.h>

// ====== OUTPUT PINS ======
const uint8_t REL_BUZZER       = 4;
const uint8_t REL_Q1           = 16;
const uint8_t REL_Q2           = 17;
const uint8_t REL_Q3           = 5;
const uint8_t REL_Q4           = 18;
const uint8_t REL_WATER_FRIA   = 19;
const uint8_t REL_WATER_CALIENTE = 21;
const uint8_t REL_DRAIN        = 22;   // NA valve, HIGH = close
const uint8_t REL_DOOR_LOCK    = 23;
const uint8_t REL_MOTOR_FWD    = 13;
const uint8_t REL_MOTOR_REV    = 14;
const uint8_t REL_VFD_RUN      = 27;
const uint8_t REL_VFD_DIR      = 26;
const uint8_t REL_SPEED_BAJA   = 25;
const uint8_t REL_SPEED_MEDIA  = 33;
const uint8_t REL_SPEED_ALTA   = 32;

// ====== INPUT PINS ======
const uint8_t PIN_EMERGENCY    = 35;
const uint8_t PIN_VFD_FAULT    = 34;
const uint8_t PIN_RES_IN1      = 0;
const uint8_t PIN_RES_IN2      = 2;
const uint8_t PIN_RES_IN3      = 15;

// ====== TIMERS ======
bool fillColdActive = false;
uint32_t fillColdUntil = 0;
bool fillHotActive = false;
uint32_t fillHotUntil = 0;

bool chemActive[4] = {false, false, false, false};
uint32_t chemUntil[4] = {0, 0, 0, 0};

bool drainTimerActive = false;
bool drainTimerFinalOpen = true;
uint32_t drainTimerUntil = 0;

bool buzzerActive = false;
uint32_t buzzerUntil = 0;

String speedNivel = "medio";

// ====== HELPERS ======
void sendJson(const JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void sendAck(const char *cmd) {
  StaticJsonDocument<96> doc;
  doc["ack"] = cmd;
  sendJson(doc);
}

void allSafeOff();
void setSpeedPresets(const String &nivel);
void motorStop();
void drainSet(bool open);
void waterStop();
void stopChem(uint8_t index);

uint32_t secondsToMs(JsonVariant value) {
  if (value.isNull()) {
    return 0;
  }
  double seconds = value.as<double>();
  if (seconds <= 0) {
    return 0;
  }
  return static_cast<uint32_t>(seconds * 1000.0);
}

void scheduleFill(bool hot, uint32_t durationMs) {
  if (hot) {
    fillHotActive = durationMs > 0;
    fillHotUntil = millis() + durationMs;
  } else {
    fillColdActive = durationMs > 0;
    fillColdUntil = millis() + durationMs;
  }
}

void scheduleChem(uint8_t index, uint32_t durationMs) {
  if (index >= 4) {
    return;
  }
  chemActive[index] = durationMs > 0;
  chemUntil[index] = millis() + durationMs;
}

void scheduleDrainRevert(bool openTarget, uint32_t durationMs) {
  if (durationMs == 0) {
    drainTimerActive = false;
    return;
  }
  drainTimerActive = true;
  drainTimerFinalOpen = openTarget;
  drainTimerUntil = millis() + durationMs;
}

void scheduleBuzzer(uint32_t durationMs) {
  buzzerActive = durationMs > 0;
  buzzerUntil = millis() + durationMs;
}

void speedNone() {
  digitalWrite(REL_SPEED_BAJA, LOW);
  digitalWrite(REL_SPEED_MEDIA, LOW);
  digitalWrite(REL_SPEED_ALTA, LOW);
}

void setSpeedPresets(const String &nivel) {
  speedNone();
  if (nivel == "bajo") {
    digitalWrite(REL_SPEED_BAJA, HIGH);
  } else if (nivel == "medio") {
    digitalWrite(REL_SPEED_MEDIA, HIGH);
  } else {
    digitalWrite(REL_SPEED_ALTA, HIGH);
  }
}

void motorFwd() {
  digitalWrite(REL_MOTOR_REV, LOW);
  digitalWrite(REL_MOTOR_FWD, HIGH);
  digitalWrite(REL_VFD_DIR, HIGH);
  digitalWrite(REL_VFD_RUN, HIGH);
}

void motorRev() {
  digitalWrite(REL_MOTOR_FWD, LOW);
  digitalWrite(REL_MOTOR_REV, HIGH);
  digitalWrite(REL_VFD_DIR, LOW);
  digitalWrite(REL_VFD_RUN, HIGH);
}

void motorStop() {
  digitalWrite(REL_MOTOR_FWD, LOW);
  digitalWrite(REL_MOTOR_REV, LOW);
  digitalWrite(REL_VFD_RUN, LOW);
}

void drainSet(bool open) {
  digitalWrite(REL_DRAIN, open ? LOW : HIGH);
}

void waterStop() {
  digitalWrite(REL_WATER_FRIA, LOW);
  digitalWrite(REL_WATER_CALIENTE, LOW);
  fillColdActive = false;
  fillHotActive = false;
}

void startFill(const char *temp, uint32_t durationMs) {
  waterStop();
  drainSet(false);  // close during fill
  if (strcmp(temp, "fria") == 0) {
    digitalWrite(REL_WATER_FRIA, HIGH);
    scheduleFill(false, durationMs);
  } else if (strcmp(temp, "caliente") == 0) {
    digitalWrite(REL_WATER_CALIENTE, HIGH);
    scheduleFill(true, durationMs);
  }
}

void stopChem(uint8_t index) {
  if (index >= 4) {
    return;
  }
  const uint8_t pins[4] = {REL_Q1, REL_Q2, REL_Q3, REL_Q4};
  digitalWrite(pins[index], LOW);
  chemActive[index] = false;
}

void startChem(uint8_t index, uint32_t durationMs) {
  const uint8_t pins[4] = {REL_Q1, REL_Q2, REL_Q3, REL_Q4};
  if (index >= 4) {
    return;
  }
  digitalWrite(pins[index], HIGH);
  scheduleChem(index, durationMs);
}

void buzzerOn(uint32_t durationMs) {
  digitalWrite(REL_BUZZER, HIGH);
  scheduleBuzzer(durationMs);
}

void buzzerOff() {
  digitalWrite(REL_BUZZER, LOW);
  buzzerActive = false;
}

void allSafeOff() {
  motorStop();
  speedNone();
  waterStop();
  for (uint8_t i = 0; i < 4; ++i) {
    stopChem(i);
  }
  drainSet(true);   // open NA valve
  digitalWrite(REL_DOOR_LOCK, LOW);
  buzzerOff();
}

// ====== COMMAND HANDLERS ======
void handleVfdSpeed(JsonObject obj) {
  String level = obj["level"] | "medio";
  level.toLowerCase();
  if (level != "bajo" && level != "medio" && level != "alto") {
    level = "medio";
  }
  speedNivel = level;
  setSpeedPresets(speedNivel);

  StaticJsonDocument<128> ack;
  ack["ack"] = "vfd_speed";
  ack["level"] = speedNivel;
  sendJson(ack);
}

void handleMotor(JsonObject obj) {
  String dir = obj["dir"] | "STOP";
  dir.toUpperCase();
  if (dir == "FWD") {
    motorFwd();
  } else if (dir == "REV") {
    motorRev();
  } else {
    motorStop();
  }

  StaticJsonDocument<128> ack;
  ack["ack"] = "motor";
  ack["dir"] = dir;
  sendJson(ack);
}

void handleDrain(JsonObject obj) {
  bool open = obj.containsKey("open") ? obj["open"].as<bool>() : false;
  uint32_t durationMs = secondsToMs(obj["t_s"]);
  drainSet(open);
  if (durationMs > 0) {
    scheduleDrainRevert(!open, durationMs);
  } else {
    drainTimerActive = false;
  }

  StaticJsonDocument<160> ack;
  ack["ack"] = "drain";
  ack["open"] = open;
  if (obj.containsKey("nivel")) {
    ack["nivel"] = obj["nivel"].as<const char *>();
  }
  if (durationMs > 0) {
    ack["t_ms"] = durationMs;
  }
  sendJson(ack);
}

uint8_t chemIndex(const String &id) {
  if (id == "detergente") {
    return 0;
  }
  if (id == "quitamanchas") {
    return 1;
  }
  if (id == "suavizante") {
    return 2;
  }
  if (id == "blanqueador") {
    return 3;
  }
  return 255;
}

void handleChem(JsonObject obj) {
  String id = obj["id"] | "";
  id.toLowerCase();
  uint32_t durationMs = secondsToMs(obj["t_s"]);
  uint8_t index = chemIndex(id);
  if (index != 255) {
    if (durationMs == 0) {
      stopChem(index);
    } else {
      startChem(index, durationMs);
    }
  }

  StaticJsonDocument<160> ack;
  ack["ack"] = "chem";
  ack["id"] = id;
  ack["t_ms"] = durationMs;
  sendJson(ack);
}

void handleFill(JsonObject obj) {
  const char *temp = obj["temp"] | "fria";
  uint32_t durationMs = secondsToMs(obj["t_s"]);
  startFill(temp, durationMs);

  StaticJsonDocument<192> ack;
  ack["ack"] = "fill";
  ack["temp"] = temp;
  if (obj.containsKey("nivel")) {
    ack["nivel"] = obj["nivel"].as<const char *>();
  }
  ack["t_ms"] = durationMs;
  sendJson(ack);
}

void handleBuzzer(JsonObject obj) {
  bool on = obj.containsKey("on") ? obj["on"].as<bool>() : false;
  uint32_t durationMs = obj.containsKey("t_ms") ? obj["t_ms"].as<uint32_t>() : 0;
  if (on) {
    buzzerOn(durationMs);
  } else {
    buzzerOff();
  }

  StaticJsonDocument<128> ack;
  ack["ack"] = "buzzer";
  ack["on"] = on;
  if (durationMs > 0) {
    ack["t_ms"] = durationMs;
  }
  sendJson(ack);
}

void handleCommand(JsonObject obj) {
  const char *cmd = obj["cmd"] | "";
  if (strcmp(cmd, "vfd_speed") == 0) {
    handleVfdSpeed(obj);
  } else if (strcmp(cmd, "motor") == 0) {
    handleMotor(obj);
  } else if (strcmp(cmd, "drain") == 0) {
    handleDrain(obj);
  } else if (strcmp(cmd, "fill") == 0) {
    handleFill(obj);
  } else if (strcmp(cmd, "chem") == 0) {
    handleChem(obj);
  } else if (strcmp(cmd, "buzzer") == 0) {
    handleBuzzer(obj);
  } else {
    StaticJsonDocument<128> ack;
    ack["ack"] = "unknown";
    ack["cmd"] = cmd;
    sendJson(ack);
  }
}

// ====== SETUP & LOOP ======
void setup() {
  Serial.begin(115200);

  const uint8_t outputs[] = {
    REL_BUZZER,
    REL_Q1,
    REL_Q2,
    REL_Q3,
    REL_Q4,
    REL_WATER_FRIA,
    REL_WATER_CALIENTE,
    REL_DRAIN,
    REL_DOOR_LOCK,
    REL_MOTOR_FWD,
    REL_MOTOR_REV,
    REL_VFD_RUN,
    REL_VFD_DIR,
    REL_SPEED_BAJA,
    REL_SPEED_MEDIA,
    REL_SPEED_ALTA
  };

  for (uint8_t pin : outputs) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }

  pinMode(PIN_EMERGENCY, INPUT);
  pinMode(PIN_VFD_FAULT, INPUT);
  pinMode(PIN_RES_IN1, INPUT);
  pinMode(PIN_RES_IN2, INPUT);
  pinMode(PIN_RES_IN3, INPUT);

  allSafeOff();
  setSpeedPresets(speedNivel);

  StaticJsonDocument<48> boot;
  boot["boot"] = "ok";
  sendJson(boot);
}

void loop() {
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      StaticJsonDocument<384> doc;
      DeserializationError err = deserializeJson(doc, line);
      if (!err && doc.containsKey("cmd")) {
        handleCommand(doc.as<JsonObject>());
      }
    }
  }

  uint32_t now = millis();

  if (fillColdActive && now >= fillColdUntil) {
    digitalWrite(REL_WATER_FRIA, LOW);
    fillColdActive = false;
  }
  if (fillHotActive && now >= fillHotUntil) {
    digitalWrite(REL_WATER_CALIENTE, LOW);
    fillHotActive = false;
  }

  for (uint8_t i = 0; i < 4; ++i) {
    if (chemActive[i] && now >= chemUntil[i]) {
      stopChem(i);
    }
  }

  if (drainTimerActive && now >= drainTimerUntil) {
    drainSet(drainTimerFinalOpen);
    drainTimerActive = false;
  }

  if (buzzerActive && now >= buzzerUntil) {
    buzzerOff();
  }

  bool emergency = digitalRead(PIN_EMERGENCY) == HIGH;
  if (emergency) {
    allSafeOff();
    StaticJsonDocument<96> status;
    status["status"] = "emergency";
    sendJson(status);
    delay(100);
  }

  bool vfdFault = digitalRead(PIN_VFD_FAULT) == HIGH;
  if (vfdFault) {
    motorStop();
    StaticJsonDocument<96> status;
    status["status"] = "vfd_fault";
    sendJson(status);
    delay(100);
  }
}
