#include <Arduino.h>
#include <ArduinoJson.h>

// Output pin definitions
const uint8_t PIN_BUZZER = 4;

const uint8_t PIN_Q1_DETERGENTE = 16;
const uint8_t PIN_Q2_QUITAMANCHAS = 17;
const uint8_t PIN_Q3_SUAVIZANTE = 5;
const uint8_t PIN_Q4_BLANQUEADOR = 18;

const uint8_t PIN_V_AF_FRIA = 19;
const uint8_t PIN_V_AC_CALIENTE = 21;
const uint8_t PIN_DREN_CERRAR = 22;
const uint8_t PIN_LOCK_PUERTA = 23;

const uint8_t PIN_MOTOR_FWD = 13;
const uint8_t PIN_MOTOR_REV = 14;
const uint8_t PIN_VFD_RUN = 27;
const uint8_t PIN_VFD_DIR = 26;

const uint8_t PIN_SPEED_BAJA = 25;
const uint8_t PIN_SPEED_MEDIA = 33;
const uint8_t PIN_SPEED_ALTA = 32;

// Input pin definitions
const uint8_t PIN_EMERGENCY_STOP = 35;
const uint8_t PIN_VFD_FAULT = 34;
const uint8_t PIN_RES_IN1 = 0;
const uint8_t PIN_RES_IN2 = 2;
const uint8_t PIN_RES_IN3 = 15;

struct TimedPin {
  uint8_t pin;
  bool active;
  uint32_t until;
};

struct DrainTimer {
  bool active;
  bool finalOpen;
  uint32_t until;
};

TimedPin fillTask = {0, false, 0};
TimedPin chemTasks[4];
DrainTimer drainTask = {false, true, 0};

bool emergencyLatched = false;
bool vfdFaultLatched = false;
String speedNivel = "medio";

void sendJson(const JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void sendAck(const char *event) {
  StaticJsonDocument<96> doc;
  doc["ack"] = event;
  sendJson(doc);
}

void sendAck(const char *event, JsonDocument &payload) {
  payload["ack"] = event;
  sendJson(payload);
}

void sendStatus(const char *status) {
  StaticJsonDocument<96> doc;
  doc["status"] = status;
  sendJson(doc);
}

void allSafeOff();
void setDrain(bool open);
void setFill(const char *temp, bool on);
void stopFill();
void doseChem(uint8_t index, uint32_t ms);
void stopChem(uint8_t index);
void setSpeedNone();
void setSpeedBaja();
void setSpeedMedia();
void setSpeedAlta();
void setSpeedPresets(const String &nivel);
void motorFwd();
void motorRev();
void motorOff();

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

void cancelFillTask() {
  if (fillTask.active) {
    digitalWrite(fillTask.pin, LOW);
    fillTask.active = false;
  }
}

void handleFill(JsonDocument &doc) {
  const char *temp = doc["temp"] | "";
  uint32_t duration = secondsToMs(doc["seconds"]);

  StaticJsonDocument<160> ack;
  ack["temp"] = temp;
  ack["ms"] = duration;

  if (strcmp(temp, "fria") == 0) {
    cancelFillTask();
    setFill("fria", true);
    if (duration > 0) {
      fillTask.pin = PIN_V_AF_FRIA;
      fillTask.active = true;
      fillTask.until = millis() + duration;
    }
  } else if (strcmp(temp, "caliente") == 0) {
    cancelFillTask();
    setFill("caliente", true);
    if (duration > 0) {
      fillTask.pin = PIN_V_AC_CALIENTE;
      fillTask.active = true;
      fillTask.until = millis() + duration;
    }
  } else {
    // Unknown temperature - stop fill for safety
    cancelFillTask();
    setFill("fria", false);
    setFill("caliente", false);
  }

  sendAck("fill", ack);
}

void handleChem(JsonDocument &doc) {
  const char *id = doc["id"] | "";
  uint32_t duration = secondsToMs(doc["seconds"]);
  uint8_t index = 255;
  uint8_t pin = 0;

  if (strcmp(id, "detergente") == 0) {
    index = 0;
    pin = PIN_Q1_DETERGENTE;
  } else if (strcmp(id, "quitamanchas") == 0) {
    index = 1;
    pin = PIN_Q2_QUITAMANCHAS;
  } else if (strcmp(id, "suavizante") == 0) {
    index = 2;
    pin = PIN_Q3_SUAVIZANTE;
  } else if (strcmp(id, "blanqueador") == 0) {
    index = 3;
    pin = PIN_Q4_BLANQUEADOR;
  }

  StaticJsonDocument<160> ack;
  ack["id"] = id;
  ack["ms"] = duration;

  if (index != 255 && duration > 0) {
    doseChem(index, duration);
  }

  sendAck("chem", ack);
}

void handleDrain(JsonDocument &doc) {
  bool openCmd = doc.containsKey("open") ? doc["open"].as<bool>() : true;
  double secondsValue = doc.containsKey("seconds") ? doc["seconds"].as<double>() : 0.0;
  uint32_t duration = secondsToMs(doc["seconds"]);
  const char *profile = doc.containsKey("profile") ? doc["profile"].as<const char *>() : "";
  const char *label = doc.containsKey("label") ? doc["label"].as<const char *>() : "";

  setDrain(openCmd);

  drainTask.active = false;
  if (duration > 0) {
    drainTask.active = true;
    drainTask.finalOpen = openCmd ? false : true;
    drainTask.until = millis() + duration;
  }

  StaticJsonDocument<192> ack;
  ack["open"] = openCmd;
  ack["seconds"] = secondsValue;
  if (profile && profile[0]) {
    ack["profile"] = profile;
  }
  if (label && label[0]) {
    ack["label"] = label;
  }
  sendAck("drain", ack);
}

void handleSpeed(JsonDocument &doc) {
  const char *nivelPtr = doc["nivel"] | "medio";
  String nivel = String(nivelPtr);
  nivel.toLowerCase();
  if (nivel != "bajo" && nivel != "medio" && nivel != "alto") {
    nivel = "medio";
  }
  speedNivel = nivel;
  setSpeedPresets(speedNivel);

  StaticJsonDocument<160> ack;
  ack["nivel"] = speedNivel;
  sendAck("speed", ack);
}

void handleMotorFwd() {
  motorFwd();
  StaticJsonDocument<128> ack;
  ack["dir"] = "FWD";
  sendAck("motor_fwd", ack);
}

void handleMotorRev() {
  motorRev();
  StaticJsonDocument<128> ack;
  ack["dir"] = "REV";
  sendAck("motor_rev", ack);
}

void handleMotorOff() {
  motorOff();
  sendAck("motor_off");
}

void handlePause(JsonDocument &doc) {
  StaticJsonDocument<160> ack;
  ack["reason"] = doc["reason"] | "";
  ack["seconds"] = doc["seconds"] | 0;
  sendAck("pause", ack);
}

void handleStart(JsonDocument &doc) {
  allSafeOff();
  StaticJsonDocument<192> ack;
  ack["cycle"] = doc["cycle"] | "";
  ack["steps"] = doc["steps"] | 0;
  ack["total"] = doc["total"] | 0;
  sendAck("start", ack);
}

void handleStep(JsonDocument &doc) {
  StaticJsonDocument<256> ack;
  ack["index"] = doc["index"] | 0;
  ack["accion"] = doc["accion"] | "";
  ack["duracion"] = doc["duracion"] | 0;
  ack["nivel"] = doc["nivel"] | "";
  ack["velocidad"] = doc["velocidad"] | "";
  JsonArray src = doc["quimicos"].as<JsonArray>();
  if (!src.isNull()) {
    JsonArray dst = ack.createNestedArray("quimicos");
    for (JsonVariant v : src) {
      dst.add(v.as<const char *>());
    }
  }
  sendAck("step", ack);
}

void handleFinish() {
  allSafeOff();
  sendAck("finish");
}

void handleStop(const char *event) {
  allSafeOff();
  StaticJsonDocument<96> ack;
  ack["event"] = event;
  sendAck(event, ack);
}

void processEvent(JsonDocument &doc) {
  const char *event = doc["event"] | "";
  if (strcmp(event, "start") == 0) {
    handleStart(doc);
  } else if (strcmp(event, "step") == 0) {
    handleStep(doc);
  } else if (strcmp(event, "fill") == 0) {
    handleFill(doc);
  } else if (strcmp(event, "chem") == 0) {
    handleChem(doc);
  } else if (strcmp(event, "drain") == 0) {
    handleDrain(doc);
  } else if (strcmp(event, "speed") == 0) {
    handleSpeed(doc);
  } else if (strcmp(event, "motor_fwd") == 0) {
    handleMotorFwd();
  } else if (strcmp(event, "motor_rev") == 0) {
    handleMotorRev();
  } else if (strcmp(event, "motor_off") == 0) {
    handleMotorOff();
  } else if (strcmp(event, "pause") == 0) {
    handlePause(doc);
  } else if (strcmp(event, "finish") == 0) {
    handleFinish();
  } else if (strcmp(event, "stop") == 0) {
    handleStop("stop");
  } else if (strcmp(event, "emergency") == 0) {
    handleStop("emergency");
  }
}

void setup() {
  Serial.begin(115200);

  const uint8_t outputs[] = {
    PIN_BUZZER,
    PIN_Q1_DETERGENTE,
    PIN_Q2_QUITAMANCHAS,
    PIN_Q3_SUAVIZANTE,
    PIN_Q4_BLANQUEADOR,
    PIN_V_AF_FRIA,
    PIN_V_AC_CALIENTE,
    PIN_DREN_CERRAR,
    PIN_LOCK_PUERTA,
    PIN_MOTOR_FWD,
    PIN_MOTOR_REV,
    PIN_VFD_RUN,
    PIN_VFD_DIR,
    PIN_SPEED_BAJA,
    PIN_SPEED_MEDIA,
    PIN_SPEED_ALTA
  };

  for (uint8_t pin : outputs) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }

  pinMode(PIN_EMERGENCY_STOP, INPUT);
  pinMode(PIN_VFD_FAULT, INPUT);
  pinMode(PIN_RES_IN1, INPUT);
  pinMode(PIN_RES_IN2, INPUT);
  pinMode(PIN_RES_IN3, INPUT);

  for (TimedPin &task : chemTasks) {
    task.active = false;
    task.pin = 0;
    task.until = 0;
  }

  allSafeOff();
  setSpeedPresets(speedNivel);

  StaticJsonDocument<48> boot;
  boot["boot"] = "ok";
  sendJson(boot);
}

void loop() {
  // Read incoming lines
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      StaticJsonDocument<512> doc;
      DeserializationError err = deserializeJson(doc, line);
      if (!err) {
        if (doc.containsKey("event")) {
          processEvent(doc);
        }
      }
    }
  }

  uint32_t now = millis();

  if (fillTask.active && now >= fillTask.until) {
    digitalWrite(fillTask.pin, LOW);
    fillTask.active = false;
  }

  for (uint8_t i = 0; i < 4; ++i) {
    if (chemTasks[i].active && now >= chemTasks[i].until) {
      stopChem(i);
    }
  }

  if (drainTask.active && now >= drainTask.until) {
    setDrain(drainTask.finalOpen);
    drainTask.active = false;
  }

  bool emergency = digitalRead(PIN_EMERGENCY_STOP) == HIGH;
  if (emergency && !emergencyLatched) {
    allSafeOff();
    sendStatus("emergency");
    emergencyLatched = true;
  } else if (!emergency) {
    emergencyLatched = false;
  }

  bool vfdFault = digitalRead(PIN_VFD_FAULT) == HIGH;
  if (vfdFault && !vfdFaultLatched) {
    motorOff();
    setSpeedNone();
    sendStatus("vfd_fault");
    vfdFaultLatched = true;
  } else if (!vfdFault) {
    vfdFaultLatched = false;
  }
}

void allSafeOff() {
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_Q1_DETERGENTE, LOW);
  digitalWrite(PIN_Q2_QUITAMANCHAS, LOW);
  digitalWrite(PIN_Q3_SUAVIZANTE, LOW);
  digitalWrite(PIN_Q4_BLANQUEADOR, LOW);
  digitalWrite(PIN_V_AF_FRIA, LOW);
  digitalWrite(PIN_V_AC_CALIENTE, LOW);
  motorOff();
  setSpeedNone();
  speedNivel = "medio";
  setDrain(true);
  digitalWrite(PIN_LOCK_PUERTA, LOW);
  fillTask.active = false;
  for (uint8_t i = 0; i < 4; ++i) {
    chemTasks[i].active = false;
  }
  drainTask.active = false;
  drainTask.finalOpen = true;
}

void setDrain(bool open) {
  digitalWrite(PIN_DREN_CERRAR, open ? LOW : HIGH);
}

void setFill(const char *temp, bool on) {
  if (strcmp(temp, "fria") == 0) {
    digitalWrite(PIN_V_AF_FRIA, on ? HIGH : LOW);
    if (on) {
      digitalWrite(PIN_V_AC_CALIENTE, LOW);
      setDrain(false);
    }
  } else if (strcmp(temp, "caliente") == 0) {
    digitalWrite(PIN_V_AC_CALIENTE, on ? HIGH : LOW);
    if (on) {
      digitalWrite(PIN_V_AF_FRIA, LOW);
      setDrain(false);
    }
  }
}

void stopFill() {
  digitalWrite(PIN_V_AF_FRIA, LOW);
  digitalWrite(PIN_V_AC_CALIENTE, LOW);
  fillTask.active = false;
}

void doseChem(uint8_t index, uint32_t ms) {
  uint8_t pin = 0;
  switch (index) {
    case 0:
      pin = PIN_Q1_DETERGENTE;
      break;
    case 1:
      pin = PIN_Q2_QUITAMANCHAS;
      break;
    case 2:
      pin = PIN_Q3_SUAVIZANTE;
      break;
    case 3:
      pin = PIN_Q4_BLANQUEADOR;
      break;
  }
  if (pin == 0) {
    return;
  }
  digitalWrite(pin, HIGH);
  chemTasks[index].pin = pin;
  chemTasks[index].active = true;
  chemTasks[index].until = millis() + ms;
}

void stopChem(uint8_t index) {
  uint8_t pin = chemTasks[index].pin;
  if (chemTasks[index].active && pin != 0) {
    digitalWrite(pin, LOW);
    chemTasks[index].active = false;
  }
}

void setSpeedNone() {
  digitalWrite(PIN_SPEED_BAJA, LOW);
  digitalWrite(PIN_SPEED_MEDIA, LOW);
  digitalWrite(PIN_SPEED_ALTA, LOW);
}

void setSpeedBaja() {
  digitalWrite(PIN_SPEED_BAJA, HIGH);
  digitalWrite(PIN_SPEED_MEDIA, LOW);
  digitalWrite(PIN_SPEED_ALTA, LOW);
}

void setSpeedMedia() {
  digitalWrite(PIN_SPEED_BAJA, LOW);
  digitalWrite(PIN_SPEED_MEDIA, HIGH);
  digitalWrite(PIN_SPEED_ALTA, LOW);
}

void setSpeedAlta() {
  digitalWrite(PIN_SPEED_BAJA, LOW);
  digitalWrite(PIN_SPEED_MEDIA, LOW);
  digitalWrite(PIN_SPEED_ALTA, HIGH);
}

void setSpeedPresets(const String &nivel) {
  setSpeedNone();
  if (nivel == "bajo") {
    setSpeedBaja();
  } else if (nivel == "medio") {
    setSpeedMedia();
  } else {
    setSpeedAlta();
  }
}

void motorFwd() {
  digitalWrite(PIN_MOTOR_REV, LOW);
  digitalWrite(PIN_MOTOR_FWD, HIGH);
  digitalWrite(PIN_VFD_DIR, LOW);
  digitalWrite(PIN_VFD_RUN, HIGH);
}

void motorRev() {
  digitalWrite(PIN_MOTOR_FWD, LOW);
  digitalWrite(PIN_MOTOR_REV, HIGH);
  digitalWrite(PIN_VFD_DIR, HIGH);
  digitalWrite(PIN_VFD_RUN, HIGH);
}

void motorOff() {
  digitalWrite(PIN_MOTOR_FWD, LOW);
  digitalWrite(PIN_MOTOR_REV, LOW);
  digitalWrite(PIN_VFD_RUN, LOW);
  digitalWrite(PIN_VFD_DIR, LOW);
}
