/*
  ESP32 + AT8236 USB-only four-wheel calibration firmware.

  Use only with the wheels raised. WiFi and BLE are intentionally not started.
*/

#include <Arduino.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;
static const unsigned long USB_BAUD = 115200;
static const unsigned long MOTOR_BAUD = 115200;
static const int MAX_TEST_SPEED = 40;
static const unsigned long MIN_TEST_MS = 100;
static const unsigned long MAX_TEST_MS = 1500;
// Keep the raised-wheel test session open long enough to test all four motors.
// The session is still cancelled immediately by !S, telemetry loss, malformed
// input, or any other safety fault.
static const unsigned long ARM_WINDOW_MS = 180000;
static const unsigned long COOLDOWN_MS = 1000;
static const unsigned long TELEMETRY_TIMEOUT_MS = 1000;
static const unsigned long MIN_RAW_INTERVAL_MS = 20;
static const unsigned long MAX_RAW_INTERVAL_MS = 1000;
// !U controls telemetry sampling, while console output is coalesced to this
// interval so the monitor remains readable during a long calibration run.
static const unsigned long TELEMETRY_SUMMARY_INTERVAL_MS = 500;
static const size_t MAX_LINE_LEN = 80;
static const size_t MAX_MOTOR_FRAME_LEN = 100;

char lineBuffer[MAX_LINE_LEN + 1] = {0};
size_t lineLength = 0;
bool lineOverflow = false;
String motorFrame;

bool telemetrySeen = false;
unsigned long lastTelemetryMs = 0;
unsigned long rawTelemetryIntervalMs = 0;
unsigned long lastRawTelemetryMs = 0;
String latestMspd;
String latestMtep;
String latestMAll;
bool armed = false;
unsigned long armedUntilMs = 0;
bool testActive = false;
unsigned long testEndMs = 0;
unsigned long cooldownUntilMs = 0;
unsigned long lastSequence = 0;
int activeMotor = 0;
int activeSpeed = 0;

void sendMotorCommand(const char *command) {
  MotorSerial.print(command);
}

void sendSingleMotorSpeed(int motor, int speed) {
  int speeds[4] = {0, 0, 0, 0};
  if (motor >= 1 && motor <= 4) speeds[motor - 1] = speed;
  char command[40];
  snprintf(command, sizeof(command), "$spd:%d,%d,%d,%d#",
           speeds[0], speeds[1], speeds[2], speeds[3]);
  sendMotorCommand(command);
}

void stopAllMotors() {
  sendMotorCommand("$spd:0,0,0,0#");
  delay(20);
  sendMotorCommand("$pwm:0,0,0,0#");
}

void printEvent(const String &event, const String &details) {
  String line = "CAL,ms=";
  line += String(millis());
  line += ",event=";
  line += event;
  if (details.length() > 0) {
    line += ",";
    line += details;
  }
  line += "\n";
  Serial.print(line);
}

void printEvent(const String &event) {
  printEvent(event, "");
}

void disarmAndStop(const String &reason) {
  stopAllMotors();
  testActive = false;
  activeMotor = 0;
  activeSpeed = 0;
  armed = false;
  armedUntilMs = 0;
  cooldownUntilMs = 0;
  printEvent("stop", "reason=" + reason);
}

bool telemetryAlive() {
  return telemetrySeen && millis() - lastTelemetryMs <= TELEMETRY_TIMEOUT_MS;
}

void printTelemetrySummary() {
  unsigned long outputInterval = rawTelemetryIntervalMs > TELEMETRY_SUMMARY_INTERVAL_MS
                                   ? rawTelemetryIntervalMs
                                   : TELEMETRY_SUMMARY_INTERVAL_MS;
  if (rawTelemetryIntervalMs == 0 ||
      (lastRawTelemetryMs != 0 && millis() - lastRawTelemetryMs < outputInterval)) {
    return;
  }
  lastRawTelemetryMs = millis();
  String details = "mspd=";
  details += (latestMspd.length() > 0 ? latestMspd : "NA");
  details += ",mtep=";
  details += (latestMtep.length() > 0 ? latestMtep : "NA");
  details += ",mall=";
  details += (latestMAll.length() > 0 ? latestMAll : "NA");
  printEvent("telemetry", details);
}

bool parseLongStrict(const String &text, long &value) {
  if (text.length() == 0) return false;
  char *endPtr = NULL;
  value = strtol(text.c_str(), &endPtr, 10);
  return endPtr != text.c_str() && *endPtr == '\0';
}

int splitCsv(const String &line, String parts[], int maxParts) {
  int start = 0;
  int count = 0;
  for (int i = 0; i <= line.length(); ++i) {
    if (i == line.length() || line.charAt(i) == ',') {
      if (count >= maxParts) return -1;
      parts[count++] = line.substring(start, i);
      start = i + 1;
    }
  }
  return count;
}

bool isNumericTelemetryPayload(const String &payload) {
  if (payload.length() == 0) return false;
  bool digitInField = false;
  for (int i = 0; i < payload.length(); ++i) {
    char c = payload.charAt(i);
    if (isDigit(c)) {
      digitInField = true;
    } else if (c == ',' || c == ':') {
      if (!digitInField) return false;
      digitInField = false;
    } else if (c == '-' || c == '+' || c == '.' || c == ' ') {
      // Preserve the raw frame; this check only decides whether it is usable telemetry.
    } else {
      return false;
    }
  }
  return digitInField;
}

bool isKnownTelemetryFrame(const String &frame) {
  if (!frame.endsWith("#")) return false;
  return frame.startsWith("$MSPD:") || frame.startsWith("$MTEP:") || frame.startsWith("$MAll:");
}

bool isValidTelemetry(const String &frame) {
  if (!isKnownTelemetryFrame(frame)) return false;
  const char *prefix = frame.startsWith("$MSPD:") ? "$MSPD:" :
                       (frame.startsWith("$MTEP:") ? "$MTEP:" : "$MAll:");
  String payload = frame.substring(strlen(prefix), frame.length() - 1);
  return isNumericTelemetryPayload(payload);
}

void serviceMotorTelemetry() {
  while (MotorSerial.available() > 0) {
    char c = (char)MotorSerial.read();
    if (c == '$') {
      motorFrame = "$";
      continue;
    }
    if (motorFrame.length() == 0) continue;
    motorFrame += c;
    if (c == '#') {
      if (motorFrame.startsWith("$MSPD:")) latestMspd = motorFrame;
      else if (motorFrame.startsWith("$MTEP:")) latestMtep = motorFrame;
      else if (motorFrame.startsWith("$MAll:")) latestMAll = motorFrame;
      if (isValidTelemetry(motorFrame)) {
        telemetrySeen = true;
        lastTelemetryMs = millis();
      }
      motorFrame = "";
    } else if (motorFrame.length() > MAX_MOTOR_FRAME_LEN) {
      motorFrame = "";
    }
  }
}

void printStatus() {
  String line = "!Q,armed=";
  line += armed ? "1" : "0";
  line += ",arm_age_ms=";
  line += armed && millis() < armedUntilMs ? String(armedUntilMs - millis()) : String(-1);
  line += ",telemetry=";
  line += telemetryAlive() ? "1" : "0";
  line += ",telemetry_age_ms=";
  line += telemetrySeen ? String((long)(millis() - lastTelemetryMs)) : String(-1);
  line += ",raw_interval_ms=";
  line += String(rawTelemetryIntervalMs);
  line += ",test_active=";
  line += testActive ? "1" : "0";
  line += ",motor=";
  line += String(activeMotor);
  line += ",speed=";
  line += String(activeSpeed);
  line += ",cooldown_ms=";
  line += millis() < cooldownUntilMs ? String((long)(cooldownUntilMs - millis())) : String(0);
  line += ",last_seq=";
  line += String(lastSequence);
  line += "\n";
  Serial.print(line);
}

void rejectAndStop(const String &reason) {
  Serial.print("!ERR,");
  Serial.println(reason);
  disarmAndStop(reason);
}

void handleArm(const String &line) {
  if (line != "!A,RAISED") {
    rejectAndStop("A format");
    return;
  }
  if (!telemetryAlive()) {
    disarmAndStop("A telemetry");
    Serial.println("!ERR,A telemetry");
    return;
  }
  if (testActive || millis() < cooldownUntilMs) {
    Serial.println("!ERR,A busy");
    return;
  }
  stopAllMotors();
  armed = true;
  armedUntilMs = millis() + ARM_WINDOW_MS;
  Serial.println("!OK,A");
  printEvent("armed", "window_ms=" + String(ARM_WINDOW_MS));
}

void handleRawTelemetry(const String &line) {
  String parts[2];
  if (splitCsv(line, parts, 2) != 2) {
    rejectAndStop("U format");
    return;
  }
  long intervalMs = 0;
  if (!parseLongStrict(parts[1], intervalMs) || intervalMs < 0 ||
      (intervalMs > 0 && (intervalMs < (long)MIN_RAW_INTERVAL_MS || intervalMs > (long)MAX_RAW_INTERVAL_MS))) {
    rejectAndStop("U range");
    return;
  }
  rawTelemetryIntervalMs = (unsigned long)intervalMs;
  lastRawTelemetryMs = 0;
  Serial.print("!OK,U,");
  Serial.println(rawTelemetryIntervalMs);
}

void handleStop(const String &line) {
  String parts[2];
  long sequence = 0;
  if (splitCsv(line, parts, 2) != 2 || !parseLongStrict(parts[1], sequence) || sequence <= 0) {
    rejectAndStop("S format");
    return;
  }
  if ((unsigned long)sequence <= lastSequence) {
    Serial.println("!ERR,S stale");
    return;
  }
  lastSequence = (unsigned long)sequence;
  disarmAndStop("manual_stop");
  Serial.println("!OK,S");
}

void handleTest(const String &line) {
  String parts[5];
  if (splitCsv(line, parts, 5) != 5) {
    rejectAndStop("T format");
    return;
  }
  long sequence = 0;
  long motor = 0;
  long speed = 0;
  long durationMs = 0;
  if (!parseLongStrict(parts[1], sequence) || !parseLongStrict(parts[2], motor) ||
      !parseLongStrict(parts[3], speed) || !parseLongStrict(parts[4], durationMs)) {
    rejectAndStop("T format");
    return;
  }
  if (!armed || millis() >= armedUntilMs) {
    disarmAndStop("arm_expired");
    Serial.println("!ERR,T arm");
    return;
  }
  if (!telemetryAlive()) {
    disarmAndStop("telemetry_timeout");
    Serial.println("!ERR,T telemetry");
    return;
  }
  if (testActive || millis() < cooldownUntilMs) {
    Serial.println("!ERR,T busy");
    return;
  }
  if (sequence <= 0 || (unsigned long)sequence <= lastSequence || motor < 1 || motor > 4 ||
      speed == 0 || speed < -MAX_TEST_SPEED || speed > MAX_TEST_SPEED ||
      durationMs < (long)MIN_TEST_MS || durationMs > (long)MAX_TEST_MS) {
    rejectAndStop("T range");
    return;
  }

  lastSequence = (unsigned long)sequence;
  activeMotor = (int)motor;
  activeSpeed = (int)speed;
  testEndMs = millis() + (unsigned long)durationMs;
  testActive = true;
  sendSingleMotorSpeed(activeMotor, activeSpeed);
  Serial.println("!OK,T");
  printEvent("test_start", "seq=" + String(lastSequence) + ",motor=" + String(activeMotor) +
             ",speed=" + String(activeSpeed) + ",duration_ms=" + String(durationMs));
}

void processLine(const String &line) {
  if (line == "!Q") {
    printStatus();
    return;
  }
  if (line.startsWith("!A")) {
    handleArm(line);
    return;
  }
  if (line.startsWith("!U")) {
    handleRawTelemetry(line);
    return;
  }
  if (line.startsWith("!S")) {
    handleStop(line);
    return;
  }
  if (line.startsWith("!T")) {
    handleTest(line);
    return;
  }
  rejectAndStop("unsupported");
}

void pollUsb() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (lineOverflow) {
        rejectAndStop("line overflow");
      } else if (lineLength > 0) {
        lineBuffer[lineLength] = '\0';
        processLine(String(lineBuffer));
      }
      lineLength = 0;
      lineOverflow = false;
      lineBuffer[0] = '\0';
      continue;
    }
    if (lineOverflow) continue;
    if (lineLength >= MAX_LINE_LEN) {
      lineLength = 0;
      lineOverflow = true;
      continue;
    }
    lineBuffer[lineLength++] = c;
  }
}

void serviceSafety() {
  unsigned long now = millis();
  if (testActive && now >= testEndMs) {
    stopAllMotors();
    testActive = false;
    activeMotor = 0;
    activeSpeed = 0;
    cooldownUntilMs = now + COOLDOWN_MS;
    printEvent("test_stop", "reason=duration,cooldown_ms=1000");
  }
  if (armed && now >= armedUntilMs) {
    disarmAndStop("arm_timeout");
  }
  if (armed && !telemetryAlive()) {
    disarmAndStop("telemetry_timeout");
  }
}

void initAT8236() {
  sendMotorCommand("$mtype:1#");
  delay(100);
  sendMotorCommand("$mphase:30#");
  delay(100);
  sendMotorCommand("$mline:11#");
  delay(100);
  sendMotorCommand("$wdiameter:80.000#");
  delay(100);
  sendMotorCommand("$deadzone:1600#");
  delay(100);
  sendMotorCommand("$upload:1,1,1#");
  delay(100);
  stopAllMotors();
}

void setup() {
  Serial.begin(USB_BAUD);
  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);
  initAT8236();
  Serial.println("ESP32 AT8236 USB calibration ready; wheels must be raised.");
  Serial.println("Send !U,50 to log raw telemetry, then !A,RAISED to arm.");
}

void loop() {
  pollUsb();
  serviceMotorTelemetry();
  printTelemetrySummary();
  serviceSafety();
}
