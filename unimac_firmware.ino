#include <Arduino.h>
#include <ArduinoJson.h>

// ====== OUTPUT PINS ======
// ================= Pinout actualizado =================
const uint8_t REL_BUZZER         = 4;
const uint8_t REL_Q1             = 21;
const uint8_t REL_Q2             = 19;
const uint8_t REL_Q3             = 18;
const uint8_t REL_Q4             = 5;
const uint8_t REL_WATER_FRIA     = 17;  // WATER_COLD
const uint8_t REL_WATER_CALIENTE = 16;  // WATER_HOT
const uint8_t REL_DRAIN          = 22;  // NA valve, HIGH = close
const uint8_t REL_DOOR_LOCK      = 23;
const uint8_t REL_MOTOR_FWD      = 14;
const uint8_t REL_MOTOR_REV      = 27;
const uint8_t REL_VFD_RUN        = 26;
const uint8_t REL_VFD_DIR        = 25;
const uint8_t REL_SPEED_BAJA     = 33;
const uint8_t REL_SPEED_MEDIA    = 32;
const uint8_t REL_SPEED_ALTA     = 13;
// ======================================================

// ====== INPUT PINS ======
const uint8_t PIN_EMERGENCY    = 35;
const uint8_t PIN_VFD_FAULT    = 34;
const uint8_t PIN_RES_IN1      = 0;
const uint8_t PIN_RES_IN2      = 2;

// --- Puerta ---
const uint8_t IN_DOOR = 15;  // switch puerta (NC -> a GND cuando cerrada)
bool doorClosed = false;
bool lastDoorClosed = false;
unsigned long lastDoorReportMs = 0;
bool doorSampleClosed = false;
uint32_t doorDebounceAt = 0;
const uint32_t DOOR_DEBOUNCE_MS = 40;

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

void sendDoorState() {
  StaticJsonDocument<96> doc;
  doc["event"] = "door";
  doc["closed"] = doorClosed;
  sendJson(doc);
}

void sendBlocked(const char *cmd) {
  StaticJsonDocument<160> doc;
  doc["event"] = "blocked";
  doc["reason"] = "door_open";
  if (cmd && cmd[0] != '\0') {
    doc["cmd"] = cmd;
  }
  sendJson(doc);
}

bool ensureDoorClosed(const char *cmd) {
  doorClosed = (digitalRead(IN_DOOR) == LOW);
  doorSampleClosed = doorClosed;
  if (doorClosed) {
    return true;
  }
  sendBlocked(cmd);
  return false;
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
  digitalWrite(REL_SPEED_BAJA, HIGH);
  digitalWrite(REL_SPEED_MEDIA, HIGH);
  digitalWrite(REL_SPEED_ALTA, HIGH);
}

void setSpeed(const String &levelRaw) {
  String level = levelRaw;
  level.toLowerCase();
  speedNone();
  if (level == "low" || level == "bajo") {
    digitalWrite(REL_SPEED_BAJA, LOW);
  } else if (level == "med" || level == "medio" || level == "media") {
    digitalWrite(REL_SPEED_MEDIA, LOW);
  } else if (level == "high" || level == "alto" || level == "alta") {
    digitalWrite(REL_SPEED_ALTA, LOW);
  }
}

void setSpeedPresets(const String &nivel) {
  String mapped = nivel;
  mapped.toLowerCase();
  if (mapped == "bajo") mapped = "low";
  else if (mapped == "medio") mapped = "med";
  else if (mapped == "alto") mapped = "high";
  setSpeed(mapped);
}

void setMotor(const String &dirRaw) {
  String dir = dirRaw;
  dir.toUpperCase();
  if (dir == "FWD") {
    digitalWrite(REL_MOTOR_REV, HIGH);
    digitalWrite(REL_MOTOR_FWD, LOW);
    digitalWrite(REL_VFD_DIR, LOW);
    digitalWrite(REL_VFD_RUN, LOW);
  } else if (dir == "REV") {
    digitalWrite(REL_MOTOR_FWD, HIGH);
    digitalWrite(REL_MOTOR_REV, LOW);
    digitalWrite(REL_VFD_DIR, HIGH);
    digitalWrite(REL_VFD_RUN, LOW);
  } else {
    digitalWrite(REL_MOTOR_FWD, HIGH);
    digitalWrite(REL_MOTOR_REV, HIGH);
    digitalWrite(REL_VFD_RUN, HIGH);
  }
}

void motorFwd() {
  setMotor("FWD");
}

void motorRev() {
  setMotor("REV");
}

void motorStop() {
  setMotor("STOP");
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
  if (durationMs == 0) {
    return;
  }
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

void doorLock(bool lock) {
  digitalWrite(REL_DOOR_LOCK, lock ? HIGH : LOW);
}

void allSafeOff() {
  motorStop();
  speedNone();
  waterStop();
  for (uint8_t i = 0; i < 4; ++i) {
    stopChem(i);
  }
  drainSet(true);   // open NA valve
  drainTimerActive = false;
  digitalWrite(REL_DOOR_LOCK, LOW);
  buzzerOff();
}

// ====== COMMAND HANDLERS ======
void handleDoor(JsonObject obj) {
  bool lock = obj.containsKey("lock") ? obj["lock"].as<bool>() : false;
  doorClosed = (digitalRead(IN_DOOR) == LOW);
  doorSampleClosed = doorClosed;
  if (lock && !doorClosed) {
    sendBlocked("door");
    return;
  }
  doorLock(lock);

  StaticJsonDocument<128> ack;
  ack["ack"] = "door";
  ack["lock"] = lock;
  sendJson(ack);
}

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
  setMotor(dir);
  Serial.printf("[MOTOR] %s activado\n", dir.c_str());

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
  if (obj.containsKey("profile")) {
    ack["profile"] = obj["profile"].as<const char *>();
  }
  if (obj.containsKey("label")) {
    ack["label"] = obj["label"].as<const char *>();
  }
  if (durationMs > 0) {
    ack["seconds"] = durationMs / 1000.0;
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
  if (durationMs > 0) {
    ack["seconds"] = durationMs / 1000.0;
  } else {
    ack["seconds"] = 0;
  }
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
  if (durationMs > 0) {
    ack["seconds"] = durationMs / 1000.0;
  } else {
    ack["seconds"] = 0;
  }
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

void handleLegacyOut(JsonObject obj) {
  String target = obj["target"] | "";
  target.toUpperCase();
  bool active = obj.containsKey("on") ? (obj["on"].as<int>() != 0) : false;

  if (target == "DRAIN") {
    drainSet(!active);
    drainTimerActive = false;
  } else if (target == "WATER_COLD") {
    if (active) {
      drainSet(false);
      digitalWrite(REL_WATER_FRIA, HIGH);
    } else {
      digitalWrite(REL_WATER_FRIA, LOW);
    }
    fillColdActive = false;
  } else if (target == "WATER_HOT") {
    if (active) {
      drainSet(false);
      digitalWrite(REL_WATER_CALIENTE, HIGH);
    } else {
      digitalWrite(REL_WATER_CALIENTE, LOW);
    }
    fillHotActive = false;
  } else if (target == "DOOR_LOCK") {
    doorLock(active);
  } else if (target == "Q1" || target == "Q2" || target == "Q3" || target == "Q4") {
    const uint8_t pins[4] = {REL_Q1, REL_Q2, REL_Q3, REL_Q4};
    uint8_t index = target.charAt(1) - '1';
    if (index < 4) {
      digitalWrite(pins[index], active ? HIGH : LOW);
      if (!active) {
        chemActive[index] = false;
      }
    }
  }

  StaticJsonDocument<192> ack;
  ack["ack"] = "out";
  ack["target"] = target;
  ack["on"] = active;
  sendJson(ack);
}

void handleLegacyDose(JsonObject obj) {
  String which = obj["which"] | "";
  which.toUpperCase();
  uint32_t durationMs = secondsToMs(obj["seconds"]);
  uint8_t index = 255;
  if (which == "Q1") index = 0;
  else if (which == "Q2") index = 1;
  else if (which == "Q3") index = 2;
  else if (which == "Q4") index = 3;

  if (index != 255) {
    if (durationMs == 0) {
      stopChem(index);
    } else {
      startChem(index, durationMs);
    }
  }

  StaticJsonDocument<160> ack;
  ack["ack"] = "dose";
  ack["which"] = which;
  if (durationMs > 0) {
    ack["seconds"] = durationMs / 1000.0;
  } else {
    ack["seconds"] = 0;
  }
  sendJson(ack);
}

void handleLegacyVfd(JsonObject obj) {
  String run = obj["run"] | "off";
  String dir = obj["dir"] | "cw";
  String speed = obj["speed"] | "low";
  run.toLowerCase();
  dir.toLowerCase();
  speed.toLowerCase();

  String level = "med";
  if (speed == "low") level = "low";
  else if (speed == "high") level = "high";
  speedNivel = level;
  setSpeed(speedNivel);

  if (run == "on") {
    if (dir == "ccw") {
      digitalWrite(REL_VFD_DIR, HIGH);
    } else {
      digitalWrite(REL_VFD_DIR, LOW);
    }
    digitalWrite(REL_VFD_RUN, LOW);
  } else {
    digitalWrite(REL_VFD_RUN, HIGH);
  }

  StaticJsonDocument<160> ack;
  ack["ack"] = "vfd";
  ack["run"] = run;
  ack["dir"] = dir;
  ack["speed"] = speed;
  sendJson(ack);
}

void handleLegacyBeep(JsonObject obj) {
  uint32_t durationMs = obj.containsKey("ms") ? obj["ms"].as<uint32_t>() : 120;
  buzzerOn(durationMs);

  StaticJsonDocument<128> ack;
  ack["ack"] = "beep";
  ack["ms"] = durationMs;
  sendJson(ack);
}

void handleCommand(JsonObject obj) {
  const char *cmd = obj["cmd"] | "";
  if (strcmp(cmd, "door?") == 0) {
    doorClosed = (digitalRead(IN_DOOR) == LOW);
    doorSampleClosed = doorClosed;
    lastDoorReportMs = millis();
    sendDoorState();
    return;
  } else if (strcmp(cmd, "query_door") == 0) {
    doorClosed = (digitalRead(IN_DOOR) == LOW);
    doorSampleClosed = doorClosed;
    lastDoorReportMs = millis();
    sendDoorState();
    return;
  } else if (strcmp(cmd, "door") == 0) {
    handleDoor(obj);
  } else if (strcmp(cmd, "vfd_speed") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleVfdSpeed(obj);
  } else if (strcmp(cmd, "motor") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleMotor(obj);
  } else if (strcmp(cmd, "drain") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleDrain(obj);
  } else if (strcmp(cmd, "fill") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleFill(obj);
  } else if (strcmp(cmd, "chem") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleChem(obj);
  } else if (strcmp(cmd, "buzzer") == 0) {
    handleBuzzer(obj);
  } else if (strcmp(cmd, "out") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleLegacyOut(obj);
  } else if (strcmp(cmd, "dose") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleLegacyDose(obj);
  } else if (strcmp(cmd, "vfd") == 0) {
    if (!ensureDoorClosed(cmd)) {
      return;
    }
    handleLegacyVfd(obj);
  } else if (strcmp(cmd, "beep") == 0) {
    handleLegacyBeep(obj);
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

  Serial.println(F("[PINMAP] Q1=21 Q2=19 Q3=18 Q4=5 COLD=17 HOT=16 DRAIN=22 DOOR=23"));
  Serial.println(F("[PINMAP] FWD=14 REV=27 RUN=26 DIR=25 SLOW=33 MED=32 FAST=13 BUZ=4"));

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

  // Relés de motor/VFD activos en LOW: dejar apagados en reposo
  digitalWrite(REL_MOTOR_FWD, HIGH);
  digitalWrite(REL_MOTOR_REV, HIGH);
  digitalWrite(REL_VFD_RUN, HIGH);
  digitalWrite(REL_VFD_DIR, HIGH);
  digitalWrite(REL_SPEED_BAJA, HIGH);
  digitalWrite(REL_SPEED_MEDIA, HIGH);
  digitalWrite(REL_SPEED_ALTA, HIGH);

  pinMode(PIN_EMERGENCY, INPUT);
  pinMode(PIN_VFD_FAULT, INPUT);
  pinMode(PIN_RES_IN1, INPUT);
  pinMode(PIN_RES_IN2, INPUT);
  pinMode(IN_DOOR, INPUT_PULLUP);

  delay(20);
  doorSampleClosed = (digitalRead(IN_DOOR) == LOW);
  doorClosed = doorSampleClosed;
  lastDoorClosed = doorClosed;
  doorDebounceAt = millis();
  lastDoorReportMs = millis();

  allSafeOff();
  setSpeedPresets(speedNivel);

  sendDoorState();

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

  bool closedRaw = (digitalRead(IN_DOOR) == LOW);
  if (closedRaw != doorSampleClosed) {
    doorSampleClosed = closedRaw;
    doorDebounceAt = now;
  } else if ((now - doorDebounceAt) > DOOR_DEBOUNCE_MS && closedRaw != doorClosed) {
    doorClosed = closedRaw;
  }

  bool changed = doorClosed != lastDoorClosed;
  if (changed || (now - lastDoorReportMs) > 1000) {
    lastDoorReportMs = now;
    lastDoorClosed = doorClosed;
    sendDoorState();
    if (changed && !doorClosed) {
      allSafeOff();
    }
  }

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
