/*
  ESP32 + AT8236 OpenBot BLE velocity-control firmware.

  This is the BLE integration of the motion core proven by
  esp32_at8236_velocity_validation.  Android remains the motion planner;
  ESP32 serializes commands, applies the four-wheel mapping, supervises
  freshness/feedback, and gives AT8236 true mm/s velocity targets.

  Safety and ordering rules:
    - One loop context parses BLE and USB commands and mutates motion state.
    - BLE callbacks only enqueue bytes tagged with the current connection epoch.
    - Old bytes from a disconnected BLE session are discarded.
    - Android motion commands are latest-wins; no motion is replayed after stop.
    - c0,0 starts active PID braking immediately.
    - !S,<seq> is a latched emergency stop and has priority over later commands.
    - Heartbeat freshness and motion-command freshness are checked separately.
    - Direct wheel-sign reversal is braked first and must be requested again
      after fresh MSPD confirms that all wheels have settled.
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <math.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;
static const unsigned long USB_BAUD = 115200;
static const unsigned long MOTOR_BAUD = 115200;

// Parameters proven on the project cart.  Do not replace these with the
// generic values in the vendor example for a different 310 motor.
static const int AT8236_MOTOR_TYPE = 2;
static const int AT8236_GEAR_RATIO = 30;
static const int AT8236_ENCODER_LINES = 11;
static const float AT8236_WHEEL_DIAMETER_MM = 80.0f;
static const int AT8236_DEADZONE = 1600;

// The existing OpenBot cart-follow output tops out at logical 14.  Raise that
// operating point from 100 to 160 mm/s, while reserving logical 15..21 for a
// staged higher-speed interface.  Logical 21 reaches the hard 240 mm/s limit;
// larger legacy inputs remain protocol-compatible but cannot exceed it.
// The original landed tests proved 100 mm/s, so 160/200/240 must be admitted
// progressively with raised-wheel, braking and open-floor validation.
static const int PROTOCOL_INPUT_LIMIT = 255;
static const int PROTOCOL_FULL_SPEED_INPUT = 21;
static const int MAX_WHEEL_SPEED_MMPS = 240;
static const int MIN_MOVING_WHEEL_MMPS = 40;
static const int MIN_PIVOT_WHEEL_MMPS = 80;
static const int CONTROL_RAMP_STEP_MMPS = 20;
static const unsigned long CONTROL_PERIOD_MS = 50;

static const unsigned long DEFAULT_LINK_TIMEOUT_MS = 750;
static const unsigned long MIN_LINK_TIMEOUT_MS = 100;
static const unsigned long MAX_LINK_TIMEOUT_MS = 3000;
static const unsigned long MOTION_REFRESH_TIMEOUT_MS = 500;
static const unsigned long DRIVER_BOOT_TIMEOUT_MS = 3000;
static const unsigned long TELEMETRY_TIMEOUT_MS = 500;
static const unsigned long BRAKE_PID_GRACE_MS = 600;
static const unsigned long BRAKE_TIMEOUT_MS = 2000;
static const unsigned long ZERO_HOLD_MS = 400;
static const unsigned long IDLE_ZERO_REFRESH_MS = 200;
static const float ZERO_SPEED_MMPS = 30.0f;
static const float BRAKE_FALLBACK_SPEED_MMPS = 120.0f;
static const float OVERSPEED_MIN_MMPS = 300.0f;
static const float OVERSPEED_RATIO = 3.0f;
static const float OVERSPEED_ABSOLUTE_MMPS = 500.0f;
static const unsigned long FEEDBACK_FAULT_CONFIRM_MS = 120;

static const size_t MAX_PROTOCOL_LINE_LEN = 80;
static const size_t MAX_MOTOR_FRAME_LEN = 160;
static const size_t BLE_RX_QUEUE_LEN = 384;
static const unsigned long DIAGNOSTIC_SAMPLE_MS = 200;

// Physical wheel placement:
//   M3 = left front, M4 = right front
//   M1 = left rear,  M2 = right rear
// A positive chassis-side speed maps to these AT8236 signs.
static const int FORWARD_SIGN[4] = {1, -1, -1, 1};
static const int MSPD_TO_COMMAND_SIGN = 1;

static const char *BLE_DEVICE_NAME = "OpenBot: CART_AT8236";
static const char *BLE_SERVICE_UUID = "61653dc3-4021-4d1e-ba83-8b4eec61d613";
static const char *BLE_RX_UUID = "06386c14-86ea-4d71-811c-48f97c58f8c9";
static const char *BLE_TX_UUID = "9bf1103b-834c-47cf-b149-c9e4bcf778a7";

enum ControlSource {
  SOURCE_NONE = 0,
  SOURCE_BLE,
  SOURCE_USB
};

enum SystemState {
  BOOT_HOLD = 0,
  READY_STOP,
  MANUAL_ACTIVE,
  BRAKING,
  EMERGENCY_STOP,
  DRIVER_ERROR
};

struct LineBuffer {
  char data[MAX_PROTOCOL_LINE_LEN + 1];
  size_t len;
  bool overflow;
};

struct BleRxByte {
  uint32_t epoch;
  char value;
};

BLEServer *bleServer = NULL;
BLECharacteristic *txCharacteristic = NULL;
QueueHandle_t bleRxQueue = NULL;

volatile bool bleClientConnected = false;
volatile bool bleConnectPending = false;
volatile bool bleAdvertisingNeedsRestart = false;
volatile bool bleDisconnectPending = false;
volatile bool bleRxOverflowPending = false;
volatile uint32_t bleConnectionEpoch = 0;

LineBuffer bleLineBuffer = {{0}, 0, false};
LineBuffer usbLineBuffer = {{0}, 0, false};
String motorFrame;

SystemState systemState = BOOT_HOLD;
ControlSource owner = SOURCE_NONE;

bool at8236Ready = false;
bool usbDiagnosticsEnabled = false;
bool readyPendingBle = false;
bool readyPendingUsb = false;
unsigned long bootStartMs = 0;
unsigned long commandTimeoutMs = DEFAULT_LINK_TIMEOUT_MS;
unsigned long ownerLastActivityMs = 0;
unsigned long lastMotionCommandMs = 0;
unsigned long lastControlUpdateMs = 0;
unsigned long lastIdleZeroMs = 0;
unsigned long lastValidMotorFrameMs = 0;
unsigned long lastMspdMs = 0;
unsigned long lastDiagnosticMs = 0;
unsigned long brakeStartedMs = 0;
unsigned long zeroSinceMs = 0;
unsigned long lastEmergencySequence = 0;
unsigned long acceptedMotionCount = 0;
unsigned long feedbackMismatchSinceMs[4] = {0, 0, 0, 0};
unsigned long overspeedSinceMs[4] = {0, 0, 0, 0};

int logicalLeft = 0;
int logicalRight = 0;
int targetWheelMmps[4] = {0, 0, 0, 0};
int currentWheelMmps[4] = {0, 0, 0, 0};
float latestMspd[4] = {0, 0, 0, 0};
long latestMAll[4] = {0, 0, 0, 0};

const char *sourceName(ControlSource source) {
  switch (source) {
    case SOURCE_BLE: return "BLE";
    case SOURCE_USB: return "USB";
    default: return "NONE";
  }
}

const char *stateName(SystemState state) {
  switch (state) {
    case BOOT_HOLD: return "BOOT_HOLD";
    case READY_STOP: return "READY_STOP";
    case MANUAL_ACTIVE: return "MANUAL_ACTIVE";
    case BRAKING: return "BRAKING";
    case EMERGENCY_STOP: return "EMERGENCY_STOP";
    case DRIVER_ERROR: return "DRIVER_ERROR";
    default: return "UNKNOWN";
  }
}

bool isLatchedState() {
  return systemState == EMERGENCY_STOP || systemState == DRIVER_ERROR;
}

float absFloat(float value) {
  return value < 0.0f ? -value : value;
}

void diagnostic(const String &event, const String &details = "") {
  if (!usbDiagnosticsEnabled) return;
  Serial.print("BLEVEL,ms=");
  Serial.print(millis());
  Serial.print(",event=");
  Serial.print(event);
  if (details.length() > 0) {
    Serial.print(',');
    Serial.print(details);
  }
  Serial.println();
}

void setState(SystemState nextState) {
  if (systemState == nextState) return;
  diagnostic("state", "from=" + String(stateName(systemState)) +
                      ",to=" + String(stateName(nextState)));
  systemState = nextState;
}

void sendMotorCommand(const String &command) {
  MotorSerial.print(command);
}

void sendSpeedVector(const int values[4]) {
  char command[64];
  snprintf(command, sizeof(command), "$spd:%d,%d,%d,%d#",
           constrain(values[0], -1000, 1000),
           constrain(values[1], -1000, 1000),
           constrain(values[2], -1000, 1000),
           constrain(values[3], -1000, 1000));
  MotorSerial.print(command);
}

void sendZeroVelocity() {
  static const int zero[4] = {0, 0, 0, 0};
  sendSpeedVector(zero);
}

void disablePwmOutput() {
  sendMotorCommand("$pwm:0,0,0,0#");
}

void clearMotionVectors() {
  logicalLeft = 0;
  logicalRight = 0;
  for (int i = 0; i < 4; ++i) {
    targetWheelMmps[i] = 0;
    currentWheelMmps[i] = 0;
    feedbackMismatchSinceMs[i] = 0;
    overspeedSinceMs[i] = 0;
  }
}

void releaseOwner() {
  owner = SOURCE_NONE;
  ownerLastActivityMs = 0;
  lastMotionCommandMs = 0;
}

void sendToBle(const String &line) {
  if (!bleClientConnected || txCharacteristic == NULL) return;
  txCharacteristic->setValue(line.c_str());
  txCharacteristic->notify();
}

void sendLine(ControlSource source, const String &line) {
  if (source == SOURCE_BLE) sendToBle(line);
  else if (source == SOURCE_USB) Serial.print(line);
}

void reportError(ControlSource source, const String &reason) {
  diagnostic("error", "source=" + String(sourceName(source)) + ",reason=" + reason);
  sendLine(source, "!ERR," + reason + "\n");
}

bool mspdFresh() {
  return lastMspdMs != 0 && millis() - lastMspdMs <= TELEMETRY_TIMEOUT_MS;
}

bool allWheelsNearZero() {
  if (!mspdFresh()) return false;
  for (int i = 0; i < 4; ++i) {
    if (absFloat(latestMspd[i]) > ZERO_SPEED_MMPS) return false;
  }
  return true;
}

void beginBrake(const String &reason) {
  if (isLatchedState()) return;
  clearMotionVectors();
  releaseOwner();
  sendZeroVelocity();
  brakeStartedMs = millis();
  zeroSinceMs = 0;
  lastControlUpdateMs = brakeStartedMs;
  setState(BRAKING);
  diagnostic("brake_start", "reason=" + reason + ",mode=spd_zero_pid_hold");
}

void enterLatchedFault(SystemState faultState, const String &reason) {
  clearMotionVectors();
  releaseOwner();
  sendZeroVelocity();
  delay(20);
  disablePwmOutput();
  setState(faultState);
  diagnostic("latched_stop", "reason=" + reason + ",mode=pwm_zero");
}

bool parseLongStrict(const String &text, long &value) {
  if (text.length() == 0) return false;
  char *end = NULL;
  value = strtol(text.c_str(), &end, 10);
  return end != text.c_str() && *end == '\0';
}

int splitCsv(const String &line, String parts[], int maxParts) {
  int count = 0;
  int start = 0;
  for (int i = 0; i <= line.length(); ++i) {
    if (i == line.length() || line.charAt(i) == ',') {
      if (count >= maxParts) return -1;
      parts[count++] = line.substring(start, i);
      start = i + 1;
    }
  }
  return count;
}

bool parsePair(const String &payload, long &first, long &second) {
  String parts[2];
  if (splitCsv(payload, parts, 2) != 2) return false;
  parts[0].trim();
  parts[1].trim();
  return parseLongStrict(parts[0], first) && parseLongStrict(parts[1], second);
}

bool parseFourFloats(const String &payload, float values[4]) {
  String parts[4];
  if (splitCsv(payload, parts, 4) != 4) return false;
  for (int i = 0; i < 4; ++i) {
    parts[i].trim();
    char *end = NULL;
    values[i] = strtof(parts[i].c_str(), &end);
    if (end == parts[i].c_str() || *end != '\0') return false;
  }
  return true;
}

bool parseFourLongs(const String &payload, long values[4]) {
  String parts[4];
  if (splitCsv(payload, parts, 4) != 4) return false;
  for (int i = 0; i < 4; ++i) {
    parts[i].trim();
    if (!parseLongStrict(parts[i], values[i])) return false;
  }
  return true;
}

int scaleLogicalSide(int logical) {
  logical = constrain(logical, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);
  if (logical == 0) return 0;
  long magnitude = (long)abs(logical) * MAX_WHEEL_SPEED_MMPS;
  int scaled = (int)((magnitude + PROTOCOL_FULL_SPEED_INPUT / 2) /
                     PROTOCOL_FULL_SPEED_INPUT);
  scaled = constrain(scaled, MIN_MOVING_WHEEL_MMPS, MAX_WHEEL_SPEED_MMPS);
  return logical > 0 ? scaled : -scaled;
}

bool isPurePivot(int left, int right) {
  return left != 0 && right != 0 && left == -right;
}

void calculateWheelTargets(int left, int right, int result[4]) {
  int leftMmps = scaleLogicalSide(left);
  int rightMmps = scaleLogicalSide(right);

  // Stage I-M showed that 60 mm/s only starts pivoting and 80 mm/s is the
  // reliable, smooth floor.  Apply it only to a true opposite-side pivot.
  if (isPurePivot(left, right)) {
    leftMmps = leftMmps > 0 ? max(leftMmps, MIN_PIVOT_WHEEL_MMPS)
                            : min(leftMmps, -MIN_PIVOT_WHEEL_MMPS);
    rightMmps = rightMmps > 0 ? max(rightMmps, MIN_PIVOT_WHEEL_MMPS)
                              : min(rightMmps, -MIN_PIVOT_WHEEL_MMPS);
  }

  result[0] = FORWARD_SIGN[0] * leftMmps;   // M1 left rear
  result[1] = FORWARD_SIGN[1] * rightMmps;  // M2 right rear
  result[2] = FORWARD_SIGN[2] * leftMmps;   // M3 left front
  result[3] = FORWARD_SIGN[3] * rightMmps;  // M4 right front
}

bool signReverses(int previous, int next) {
  return previous != 0 && next != 0 && ((previous > 0) != (next > 0));
}

bool requiresDirectReversal(const int requested[4]) {
  for (int i = 0; i < 4; ++i) {
    if (signReverses(targetWheelMmps[i], requested[i]) ||
        signReverses(currentWheelMmps[i], requested[i])) return true;
  }
  return false;
}

int moveToward(int current, int target, int step) {
  if (current < target) return min(current + step, target);
  if (current > target) return max(current - step, target);
  return current;
}

bool feedbackSafe() {
  unsigned long now = millis();
  for (int i = 0; i < 4; ++i) {
    if (targetWheelMmps[i] == 0) {
      feedbackMismatchSinceMs[i] = 0;
      overspeedSinceMs[i] = 0;
      continue;
    }

    float measured = latestMspd[i] * MSPD_TO_COMMAND_SIGN;
    bool signMismatch = absFloat(measured) > ZERO_SPEED_MMPS &&
                        ((measured > 0) != (targetWheelMmps[i] > 0));
    if (signMismatch) {
      if (feedbackMismatchSinceMs[i] == 0) feedbackMismatchSinceMs[i] = now;
      if (now - feedbackMismatchSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterLatchedFault(DRIVER_ERROR,
                          "feedback_sign_mismatch_m" + String(i + 1));
        return false;
      }
    } else {
      feedbackMismatchSinceMs[i] = 0;
    }

    float limit = min(
      OVERSPEED_ABSOLUTE_MMPS,
      max(OVERSPEED_MIN_MMPS,
          absFloat((float)targetWheelMmps[i]) * OVERSPEED_RATIO));
    if (absFloat(measured) > limit) {
      if (overspeedSinceMs[i] == 0) overspeedSinceMs[i] = now;
      if (now - overspeedSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterLatchedFault(DRIVER_ERROR, "overspeed_m" + String(i + 1));
        return false;
      }
    } else {
      overspeedSinceMs[i] = 0;
    }
  }
  return true;
}

void printStatus() {
  Serial.print("!Q,state="); Serial.print(stateName(systemState));
  Serial.print(",owner="); Serial.print(sourceName(owner));
  Serial.print(",ble_connected="); Serial.print(bleClientConnected ? 1 : 0);
  Serial.print(",ble_epoch="); Serial.print((unsigned long)bleConnectionEpoch);
  Serial.print(",driver_ready="); Serial.print(at8236Ready ? 1 : 0);
  Serial.print(",link_age_ms=");
  Serial.print(ownerLastActivityMs ? (long)(millis() - ownerLastActivityMs) : -1);
  Serial.print(",motion_age_ms=");
  Serial.print(lastMotionCommandMs ? (long)(millis() - lastMotionCommandMs) : -1);
  Serial.print(",accepted_motion_count="); Serial.print(acceptedMotionCount);
  Serial.print(",speed_full_input="); Serial.print(PROTOCOL_FULL_SPEED_INPUT);
  Serial.print(",speed_cap_mmps="); Serial.print(MAX_WHEEL_SPEED_MMPS);
  Serial.print(",logical="); Serial.print(logicalLeft); Serial.print(',');
  Serial.print(logicalRight);
  Serial.print(",target=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(targetWheelMmps[i]);
    Serial.print(i == 3 ? ',' : ':');
  }
  Serial.print("current=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(currentWheelMmps[i]);
    Serial.print(i == 3 ? ',' : ':');
  }
  Serial.print("mspd=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(latestMspd[i], 2);
    if (i < 3) Serial.print(':');
  }
  Serial.print(",mspd_age_ms=");
  Serial.println(lastMspdMs ? (long)(millis() - lastMspdMs) : -1);
}

void handleMotionCommand(ControlSource source, const String &line) {
  long leftValue = 0;
  long rightValue = 0;
  if (!parsePair(line.substring(1), leftValue, rightValue) ||
      leftValue < -PROTOCOL_INPUT_LIMIT || leftValue > PROTOCOL_INPUT_LIMIT ||
      rightValue < -PROTOCOL_INPUT_LIMIT || rightValue > PROTOCOL_INPUT_LIMIT) {
    reportError(source, "bad_control");
    if (owner == source && systemState == MANUAL_ACTIVE) beginBrake("bad_control");
    return;
  }

  int left = (int)leftValue;
  int right = (int)rightValue;
  unsigned long now = millis();

  // Normal STOP is allowed from either source and never waits behind a ramp.
  if (left == 0 && right == 0) {
    if (systemState == MANUAL_ACTIVE || owner != SOURCE_NONE) {
      beginBrake("control_zero");
    } else if (systemState == READY_STOP) {
      sendZeroVelocity();
      lastIdleZeroMs = now;
    }
    return;
  }

  if (isLatchedState()) {
    reportError(source, "latched_stop");
    return;
  }
  if (!at8236Ready || systemState == BOOT_HOLD) {
    reportError(source, "driver_not_ready");
    return;
  }
  if (systemState == BRAKING) {
    // Deliberately do not cache this command. Android repeats every 100 ms;
    // only a fresh command received after brake_settled may start motion.
    reportError(source, "settling");
    return;
  }
  if (owner != SOURCE_NONE && owner != source) {
    reportError(source, "owner_busy");
    return;
  }

  int requested[4];
  calculateWheelTargets(left, right, requested);
  if (systemState == MANUAL_ACTIVE && requiresDirectReversal(requested)) {
    beginBrake("direct_reversal");
    reportError(source, "reversal_braking");
    return;
  }

  owner = source;
  ownerLastActivityMs = now;
  lastMotionCommandMs = now;
  logicalLeft = left;
  logicalRight = right;
  for (int i = 0; i < 4; ++i) targetWheelMmps[i] = requested[i];
  acceptedMotionCount++;
  setState(MANUAL_ACTIVE);
  diagnostic("motion_accept",
             "seq=" + String(acceptedMotionCount) +
             ",source=" + sourceName(source) +
             ",logical=" + String(left) + "," + String(right) +
             ",target=" + String(targetWheelMmps[0]) + "," +
               String(targetWheelMmps[1]) + "," +
               String(targetWheelMmps[2]) + "," +
               String(targetWheelMmps[3]));
}

void handleHeartbeat(ControlSource source, const String &line) {
  long requested = 0;
  if (!parseLongStrict(line.substring(1), requested) ||
      requested < (long)MIN_LINK_TIMEOUT_MS ||
      requested > (long)MAX_LINK_TIMEOUT_MS) {
    reportError(source, "bad_heartbeat");
    return;
  }

  // A second transport must not keep the active owner's session alive.
  if (owner != SOURCE_NONE && owner != source) return;
  commandTimeoutMs = (unsigned long)requested;
  if (owner == source) ownerLastActivityMs = millis();
}

void handleFeatureQuery(ControlSource source) {
  sendLine(source, "fCART_AT8236:\n");
  if (at8236Ready && !isLatchedState()) {
    sendLine(source, "r\n");
  } else if (source == SOURCE_BLE) {
    readyPendingBle = true;
  } else if (source == SOURCE_USB) {
    readyPendingUsb = true;
  }
}

void handleEmergency(ControlSource source, const String &line) {
  if (!line.startsWith("!S,")) {
    reportError(source, "bad_emergency");
    return;
  }
  long sequence = 0;
  if (!parseLongStrict(line.substring(3), sequence) || sequence <= 0 ||
      (unsigned long)sequence <= lastEmergencySequence) {
    reportError(source, "stale_emergency_seq");
    return;
  }
  lastEmergencySequence = (unsigned long)sequence;
  enterLatchedFault(EMERGENCY_STOP,
                    "emergency_seq_" + String(lastEmergencySequence));
  sendLine(source, "!S,OK," + String(lastEmergencySequence) + "\n");
}

void handleDiagnostics(ControlSource source, const String &line) {
  if (source != SOURCE_USB) {
    reportError(source, "usb_only");
    return;
  }
  if (line == "!D,1") {
    usbDiagnosticsEnabled = true;
    Serial.println("!D,OK,1");
  } else if (line == "!D,0") {
    Serial.println("!D,OK,0");
    usbDiagnosticsEnabled = false;
  } else {
    Serial.println("!ERR,bad_diagnostics");
  }
}

void processCommand(ControlSource source, String line) {
  line.trim();
  if (line.length() == 0) return;

  // Once emergency stop is latched, only read-only queries are accepted.
  if (line == "f") {
    handleFeatureQuery(source);
  } else if (line == "!Q") {
    if (source == SOURCE_USB) printStatus();
    else reportError(source, "usb_only");
  } else if (line.startsWith("!D,")) {
    handleDiagnostics(source, line);
  } else if (line.startsWith("!S")) {
    handleEmergency(source, line);
  } else if (isLatchedState()) {
    reportError(source, "latched_stop");
  } else if (line.charAt(0) == 'c') {
    handleMotionCommand(source, line);
  } else if (line.charAt(0) == 'h') {
    handleHeartbeat(source, line);
  } else {
    reportError(source, "unknown_command");
    if (owner == source && systemState == MANUAL_ACTIVE) beginBrake("protocol_error");
  }
}

void resetLineBuffer(LineBuffer &buffer) {
  buffer.len = 0;
  buffer.overflow = false;
  buffer.data[0] = '\0';
}

void consumeIncomingByte(ControlSource source, LineBuffer &buffer, char value) {
  if (value == '\r') return;
  if (value == '\n') {
    if (buffer.overflow) {
      reportError(source, "line_overflow");
      if (owner == source && systemState == MANUAL_ACTIVE) beginBrake("line_overflow");
    } else if (buffer.len > 0) {
      buffer.data[buffer.len] = '\0';
      processCommand(source, String(buffer.data));
    }
    resetLineBuffer(buffer);
    return;
  }

  if (buffer.overflow) return;
  if (buffer.len >= MAX_PROTOCOL_LINE_LEN) {
    buffer.overflow = true;
    return;
  }
  buffer.data[buffer.len++] = value;
}

void serviceMotorSerial() {
  while (MotorSerial.available() > 0) {
    char value = (char)MotorSerial.read();
    if (value == '$') {
      motorFrame = "$";
      continue;
    }
    if (motorFrame.length() == 0) continue;
    motorFrame += value;
    if (motorFrame.length() > MAX_MOTOR_FRAME_LEN) {
      motorFrame = "";
      continue;
    }
    if (value != '#') continue;

    bool valid = false;
    if (motorFrame.startsWith("$MSPD:")) {
      valid = parseFourFloats(motorFrame.substring(6, motorFrame.length() - 1),
                              latestMspd);
      if (valid) lastMspdMs = millis();
    } else if (motorFrame.startsWith("$MAll:")) {
      valid = parseFourLongs(motorFrame.substring(6, motorFrame.length() - 1),
                             latestMAll);
    } else if (motorFrame.startsWith("$MTEP:")) {
      float ignored[4];
      valid = parseFourFloats(motorFrame.substring(6, motorFrame.length() - 1),
                              ignored);
    } else if (motorFrame.endsWith("OK#") ||
               motorFrame.startsWith("$Battery:") ||
               motorFrame.startsWith("$read_flash")) {
      // Configuration and readback replies prove that the UART parser is alive,
      // but motion readiness still requires a valid MSPD frame below.
      valid = true;
      diagnostic("driver_reply", motorFrame);
    }

    if (valid) lastValidMotorFrameMs = millis();
    motorFrame = "";
  }

  if (!at8236Ready && mspdFresh()) {
    at8236Ready = true;
    if (!isLatchedState() && systemState == BOOT_HOLD) setState(READY_STOP);
    diagnostic("driver_ready", "mspd=1");
  }
}

void configureAT8236() {
  // Disable a command possibly retained by the driver before writing its
  // persistent configuration. Normal runtime braking uses $spd:0 instead.
  disablePwmOutput();
  delay(100);
  sendMotorCommand("$upload:0,0,0#");
  delay(50);
  sendMotorCommand("$mtype:" + String(AT8236_MOTOR_TYPE) + "#");
  delay(100);
  sendMotorCommand("$mphase:" + String(AT8236_GEAR_RATIO) + "#");
  delay(100);
  sendMotorCommand("$mline:" + String(AT8236_ENCODER_LINES) + "#");
  delay(100);
  sendMotorCommand("$wdiameter:" + String(AT8236_WHEEL_DIAMETER_MM, 3) + "#");
  delay(100);
  sendMotorCommand("$deadzone:" + String(AT8236_DEADZONE) + "#");
  delay(100);
  // MPID is intentionally not overwritten; the validated board setting is kept.
  sendMotorCommand("$read_flash#");
  delay(100);
  sendMotorCommand("$upload:1,1,1#");
  delay(100);
  sendZeroVelocity();
}

class OpenBotBleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *server) override {
    (void)server;
    bleConnectionEpoch++;
    bleClientConnected = true;
    bleConnectPending = true;
  }

  void onDisconnect(BLEServer *server) override {
    (void)server;
    bleClientConnected = false;
    bleConnectionEpoch++;
    readyPendingBle = false;
    bleDisconnectPending = true;
    bleAdvertisingNeedsRestart = true;
  }
};

class OpenBotBleRxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    auto value = characteristic->getValue();
    uint32_t epoch = bleConnectionEpoch;
    for (size_t i = 0; i < value.length(); ++i) {
      BleRxByte item = {epoch, value[i]};
      if (bleRxQueue == NULL || xQueueSend(bleRxQueue, &item, 0) != pdTRUE) {
        bleRxOverflowPending = true;
      }
    }
  }
};

void setupBle() {
  bleRxQueue = xQueueCreate(BLE_RX_QUEUE_LEN, sizeof(BleRxByte));
  BLEDevice::init(BLE_DEVICE_NAME);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new OpenBotBleServerCallbacks());

  BLEService *service = bleServer->createService(BLE_SERVICE_UUID);
  txCharacteristic = service->createCharacteristic(
    BLE_TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  txCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic *rxCharacteristic = service->createCharacteristic(
    BLE_RX_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rxCharacteristic->setCallbacks(new OpenBotBleRxCallbacks());

  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  advertising->setScanResponse(false);
  advertising->setMinPreferred(0x06);
  advertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
}

void serviceBleEvents() {
  if (bleDisconnectPending) {
    bleDisconnectPending = false;
    diagnostic("ble_disconnect", "epoch=" + String((unsigned long)bleConnectionEpoch));
    if (owner == SOURCE_BLE && !isLatchedState()) beginBrake("ble_disconnect");
    resetLineBuffer(bleLineBuffer);
    if (bleRxQueue != NULL) xQueueReset(bleRxQueue);
  }

  if (bleConnectPending) {
    bleConnectPending = false;
    commandTimeoutMs = DEFAULT_LINK_TIMEOUT_MS;
    readyPendingBle = false;
    resetLineBuffer(bleLineBuffer);
    diagnostic("ble_connect", "epoch=" + String((unsigned long)bleConnectionEpoch));
  }

  if (bleRxOverflowPending) {
    bleRxOverflowPending = false;
    reportError(SOURCE_BLE, "rx_queue_overflow");
    if (owner == SOURCE_BLE && systemState == MANUAL_ACTIVE) {
      beginBrake("rx_queue_overflow");
    }
    resetLineBuffer(bleLineBuffer);
    if (bleRxQueue != NULL) xQueueReset(bleRxQueue);
  }

  BleRxByte item;
  while (bleRxQueue != NULL && xQueueReceive(bleRxQueue, &item, 0) == pdTRUE) {
    if (!bleClientConnected || item.epoch != bleConnectionEpoch) {
      diagnostic("stale_ble_byte_drop",
                 "item_epoch=" + String((unsigned long)item.epoch) +
                 ",active_epoch=" + String((unsigned long)bleConnectionEpoch));
      continue;
    }
    consumeIncomingByte(SOURCE_BLE, bleLineBuffer, item.value);
  }

  if (bleAdvertisingNeedsRestart) {
    bleAdvertisingNeedsRestart = false;
    delay(20);
    if (bleServer != NULL) bleServer->startAdvertising();
  }
}

void pollUsb() {
  while (Serial.available() > 0) {
    consumeIncomingByte(SOURCE_USB, usbLineBuffer, (char)Serial.read());
  }
}

void serviceReadyNotifications() {
  if (!at8236Ready || isLatchedState()) return;
  if (readyPendingBle && bleClientConnected) {
    sendToBle("r\n");
    readyPendingBle = false;
  }
  if (readyPendingUsb) {
    Serial.print("r\n");
    readyPendingUsb = false;
  }
}

void serviceTimeouts() {
  if (isLatchedState()) return;
  unsigned long now = millis();

  if (!at8236Ready && now - bootStartMs > DRIVER_BOOT_TIMEOUT_MS) {
    enterLatchedFault(DRIVER_ERROR, "driver_boot_timeout");
    return;
  }

  if (systemState != MANUAL_ACTIVE) return;
  if (ownerLastActivityMs == 0 || now - ownerLastActivityMs > commandTimeoutMs) {
    beginBrake("link_timeout");
    return;
  }
  if (lastMotionCommandMs == 0 ||
      now - lastMotionCommandMs > MOTION_REFRESH_TIMEOUT_MS) {
    beginBrake("motion_timeout");
    return;
  }
  if (!mspdFresh()) {
    enterLatchedFault(DRIVER_ERROR, "telemetry_timeout_while_moving");
  }
}

void serviceActiveMotion() {
  if (systemState != MANUAL_ACTIVE) return;
  if (!mspdFresh()) return;
  if (!feedbackSafe()) return;

  unsigned long now = millis();
  if (now - lastControlUpdateMs < CONTROL_PERIOD_MS) return;
  lastControlUpdateMs = now;
  for (int i = 0; i < 4; ++i) {
    currentWheelMmps[i] = moveToward(currentWheelMmps[i],
                                     targetWheelMmps[i],
                                     CONTROL_RAMP_STEP_MMPS);
  }
  sendSpeedVector(currentWheelMmps);

  if (usbDiagnosticsEnabled &&
      (lastDiagnosticMs == 0 || now - lastDiagnosticMs >= DIAGNOSTIC_SAMPLE_MS)) {
    lastDiagnosticMs = now;
    diagnostic("drive",
               "logical=" + String(logicalLeft) + "," + String(logicalRight) +
               ",target=" + String(targetWheelMmps[0]) + "," +
                 String(targetWheelMmps[1]) + "," +
                 String(targetWheelMmps[2]) + "," +
                 String(targetWheelMmps[3]) +
               ",current=" + String(currentWheelMmps[0]) + "," +
                 String(currentWheelMmps[1]) + "," +
                 String(currentWheelMmps[2]) + "," +
                 String(currentWheelMmps[3]) +
               ",mspd=" + String(latestMspd[0], 2) + "," +
                 String(latestMspd[1], 2) + "," +
                 String(latestMspd[2], 2) + "," +
                 String(latestMspd[3], 2));
  }
}

void serviceBrake() {
  if (systemState != BRAKING) return;
  unsigned long now = millis();
  if (now - lastControlUpdateMs >= CONTROL_PERIOD_MS) {
    lastControlUpdateMs = now;
    sendZeroVelocity();
  }

  if (!mspdFresh()) {
    enterLatchedFault(DRIVER_ERROR, "mspd_lost_while_braking");
    return;
  }

  if (now - brakeStartedMs >= BRAKE_PID_GRACE_MS) {
    for (int i = 0; i < 4; ++i) {
      if (absFloat(latestMspd[i]) > BRAKE_FALLBACK_SPEED_MMPS) {
        enterLatchedFault(DRIVER_ERROR,
                          "pid_brake_failed_m" + String(i + 1));
        return;
      }
    }
  }

  if (allWheelsNearZero()) {
    if (zeroSinceMs == 0) zeroSinceMs = now;
    if (now - zeroSinceMs >= ZERO_HOLD_MS) {
      setState(READY_STOP);
      diagnostic("brake_settled", "zero_hold_ms=" + String(ZERO_HOLD_MS));
      return;
    }
  } else {
    zeroSinceMs = 0;
  }

  if (now - brakeStartedMs >= BRAKE_TIMEOUT_MS) {
    enterLatchedFault(DRIVER_ERROR, "brake_timeout");
  }
}

void serviceIdleHold() {
  if (systemState != READY_STOP && systemState != BOOT_HOLD) return;
  unsigned long now = millis();
  if (now - lastIdleZeroMs >= IDLE_ZERO_REFRESH_MS) {
    lastIdleZeroMs = now;
    sendZeroVelocity();
  }
}

void setup() {
  Serial.begin(USB_BAUD);
  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);
  clearMotionVectors();
  releaseOwner();
  systemState = BOOT_HOLD;
  bootStartMs = millis();

  configureAT8236();
  setupBle();
  Serial.println("ESP32 AT8236 velocity BLE firmware booting");
}

void loop() {
  // All state changes and all AT8236 writes happen in this single context.
  serviceMotorSerial();
  serviceBleEvents();
  pollUsb();
  serviceReadyNotifications();
  serviceTimeouts();
  serviceActiveMotion();
  serviceBrake();
  serviceIdleHold();
}
