/*
  ESP32 + AT8236 OpenBot BLE safe remote firmware

  Target:
    - ESP32 WROOM-32E / ESP32 Dev Module
    - AT8236 motor controller
    - OpenBot BLE manual remote control only

  Safety scope:
    - WiFi disabled
    - no bench-test motion shortcuts
    - only BLE + USB protocol defined in README
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;
static const int MOTOR_BAUD = 115200;
static const unsigned long USB_BAUD = 115200;

static const int PROTOCOL_INPUT_LIMIT = 255;
static const int MAX_WHEEL_OUTPUT = 40;
static const int CONTROL_RAMP_STEP = 6;
static const unsigned long CONTROL_UPDATE_MS = 40;
// Default command freshness interval.  `h<timeout_ms>` may explicitly widen
// this interval up to MAX_COMMAND_TIMEOUT_MS for a manual control session.
// It is deliberately still bounded; BLE disconnect, AT8236 timeout and !S
// remain independent stop paths.
static const unsigned long MOTION_REFRESH_TIMEOUT_MS = 500;
static const unsigned long DEFAULT_COMMAND_TIMEOUT_MS = MOTION_REFRESH_TIMEOUT_MS;
static const unsigned long MIN_COMMAND_TIMEOUT_MS = 100;
static const unsigned long MAX_COMMAND_TIMEOUT_MS = 3000;
static const unsigned long AT8236_BOOT_WAIT_MS = 1500;
static const unsigned long AT8236_ACTIVE_TIMEOUT_MS = 1000;
static const unsigned long USB_DIAGNOSTIC_SAMPLE_MS = 100;
static const unsigned long REVERSAL_NEUTRAL_MS = 1000;
static const unsigned long STRAIGHT_STARTUP_ASSIST_MS = 1600;
static const unsigned long STRAIGHT_BREAKAWAY_KICK_MS = 350;
static const unsigned long TURN_STARTUP_ASSIST_MS = 1600;
static const unsigned long TURN_BREAKAWAY_KICK_MS = 400;
static const unsigned long STARTUP_ASSIST_MSPD_MAX_AGE_MS = 250;
static const float STARTUP_ASSIST_MSPD_ZERO_LIMIT = 80.0f;
static const float STRAIGHT_STALL_MSPD_LIMIT = 80.0f;
static const size_t MAX_PROTOCOL_LINE_LEN = 60;
static const size_t MAX_MOTOR_FRAME_LEN = 80;
static const size_t BLE_RX_QUEUE_LEN = 256;

// 2026-07-13 landed straight-line tests:
// - raised-wheel trim (M2=130%, M4=100%) made the cart visibly turn left;
// - aggressive landed compensation (M1=120%, M2=90%, M3=130%, M4=80%) made it
//   turn right, with left-side MSPD much higher than right-side MSPD.
// This is the next midpoint trim: the previous M1=110/M2=105/M3=115/M4=95
// still produced a slight right drift, so move one small step toward balanced
// landed straight-line output.
static const int M1_TRIM_PERCENT = 105;
static const int M2_TRIM_PERCENT = 110;
static const int M3_TRIM_PERCENT = 110;
// Landed BLE logs show M4 (right front) is the repeatable weak wheel:
// it can remain near zero on reverse while the other three are moving.
// Raise it to the same steady-state trim as M2; turn output remains bounded
// by its existing symmetric floor/kick logic.
static const int M4_TRIM_PERCENT = 110;
// The landed cart does not reliably overcome static friction at c14,14:
// applying the former per-wheel floors still produced only 14/15 output.
// Use a short per-wheel breakaway pulse, then a lower per-wheel hold so the
// cart starts straight without carrying the turn-specific high kick over.
// The later BLE trials show the right-side asymmetric pulse over-corrects:
// it makes the cart drift one way forward and the opposite way in reverse.
// Keep the proven M4 steady-state trim, but make the transient launch pulse
// symmetric so a direction reversal cannot turn the same bias into its mirror.
static const int M1_STRAIGHT_BREAKAWAY_KICK_OUTPUT = 24;
static const int M2_STRAIGHT_BREAKAWAY_KICK_OUTPUT = 24;
static const int M3_STRAIGHT_BREAKAWAY_KICK_OUTPUT = 24;
static const int M4_STRAIGHT_BREAKAWAY_KICK_OUTPUT = 24;
static const int M1_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT = 20;
static const int M2_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT = 20;
static const int M3_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT = 20;
static const int M4_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT = 20;
// A wheel which has not started after the common breakaway phase may receive
// this bounded, individual retry.  It is deliberately below the turn kick.
static const int STRAIGHT_STALL_BOOST_OUTPUT = 30;
static const int TURN_HOLD_MIN_OUTPUT = 24;
static const int TURN_STARTUP_ASSIST_MIN_OUTPUT = 32;
static const int TURN_BREAKAWAY_KICK_OUTPUT = 40;

// Wheel placement:
//   M3 = left front, M4 = right front
//   M1 = left rear,  M2 = right rear
static const int M1_FORWARD_SIGN = 1;
static const int M2_FORWARD_SIGN = -1;
static const int M3_FORWARD_SIGN = -1;
static const int M4_FORWARD_SIGN = 1;

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
  BOOT_STOP = 0,
  READY_STOP,
  MANUAL_ACTIVE,
  REVERSAL_BLOCKED,
  COM_TIMEOUT,
  EMERGENCY_STOP,
  DRIVER_ERROR
};

enum StartupAssistMode {
  STARTUP_ASSIST_NONE = 0,
  STARTUP_ASSIST_STRAIGHT,
  STARTUP_ASSIST_TURN
};

struct LineBuffer {
  char data[MAX_PROTOCOL_LINE_LEN + 1];
  size_t len;
  bool overflow;
};

BLEServer *bleServer = NULL;
BLECharacteristic *txCharacteristic = NULL;
volatile bool bleClientConnected = false;
volatile bool bleAdvertisingNeedsRestart = false;
volatile bool bleDisconnectPending = false;
volatile bool bleRxOverflowPending = false;
ControlSource readyNotificationTarget = SOURCE_NONE;
QueueHandle_t bleRxQueue = NULL;

LineBuffer bleLineBuffer = {{0}, 0, false};
LineBuffer usbLineBuffer = {{0}, 0, false};
String motorFrame;

SystemState systemState = BOOT_STOP;
ControlSource owner = SOURCE_NONE;

unsigned long commandTimeoutMs = DEFAULT_COMMAND_TIMEOUT_MS;
unsigned long ownerLastActivityMs = 0;
unsigned long lastMotionCommandMs = 0;
unsigned long lastControlUpdateMs = 0;
unsigned long startupAssistUntilMs = 0;
unsigned long startupAssistStartMs = 0;
StartupAssistMode startupAssistMode = STARTUP_ASSIST_NONE;
unsigned long bootStartMs = 0;
unsigned long lastValidMotorFrameMs = 0;
unsigned long lastMspdFrameMs = 0;
float latestMspdM1 = 0.0f;
float latestMspdM2 = 0.0f;
float latestMspdM3 = 0.0f;
float latestMspdM4 = 0.0f;
bool at8236Ready = false;
unsigned long lastEmergencySequence = 0;
bool usbDiagnosticsEnabled = false;
unsigned long motionCommandCount = 0;
unsigned long lastMotionCommandSequence = 0;
unsigned long lastMotionCommandReceivedMs = 0;
ControlSource lastMotionCommandSource = SOURCE_NONE;
int lastMotionCommandLeft = 0;
int lastMotionCommandRight = 0;
bool lastMotionCommandAccepted = false;
unsigned long lastDiagnosticDriveLogMs = 0;
bool hasLastNonzeroTarget = false;
int lastNonzeroM1 = 0;
int lastNonzeroM2 = 0;
int lastNonzeroM3 = 0;
int lastNonzeroM4 = 0;
unsigned long reversalNeutralSinceMs = 0;

int targetM1 = 0;
int targetM2 = 0;
int targetM3 = 0;
int targetM4 = 0;
int currentM1 = 0;
int currentM2 = 0;
int currentM3 = 0;
int currentM4 = 0;

const char *sourceName(ControlSource source) {
  switch (source) {
    case SOURCE_BLE:
      return "BLE";
    case SOURCE_USB:
      return "USB";
    default:
      return "NONE";
  }
}

const char *stateName(SystemState state) {
  switch (state) {
    case BOOT_STOP:
      return "BOOT_STOP";
    case READY_STOP:
      return "READY_STOP";
    case MANUAL_ACTIVE:
      return "MANUAL_ACTIVE";
    case REVERSAL_BLOCKED:
      return "REVERSAL_BLOCKED";
    case COM_TIMEOUT:
      return "COM_TIMEOUT";
    case EMERGENCY_STOP:
      return "EMERGENCY_STOP";
    case DRIVER_ERROR:
      return "DRIVER_ERROR";
    default:
      return "UNKNOWN";
  }
}

bool isLatchedState() {
  return systemState == EMERGENCY_STOP || systemState == DRIVER_ERROR;
}

void usbDiagnostic(const String &event, const String &details) {
  if (!usbDiagnosticsEnabled) return;

  String line = "!D,ms=";
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

void usbDiagnostic(const String &event) {
  usbDiagnostic(event, "");
}

void recordMotionCommand(ControlSource source, int left, int right) {
  motionCommandCount++;
  lastMotionCommandSequence = motionCommandCount;
  lastMotionCommandReceivedMs = millis();
  lastMotionCommandSource = source;
  lastMotionCommandLeft = left;
  lastMotionCommandRight = right;
  lastMotionCommandAccepted = false;

  usbDiagnostic(
    "motion_rx",
    "seq=" + String(lastMotionCommandSequence) +
      ",source=" + sourceName(source) +
      ",left=" + String(left) +
      ",right=" + String(right));
}

void recordMotionTargets() {
  lastMotionCommandAccepted = true;
  usbDiagnostic(
    "motion_target",
    "seq=" + String(lastMotionCommandSequence) +
      ",target=" + String(targetM1) + "," + String(targetM2) + "," +
      String(targetM3) + "," + String(targetM4));
}

void sendMotorCommand(const char *cmd) {
  MotorSerial.print(cmd);
}

int applyTrim(int speed, int trimPercent) {
  int trimmed = (speed * trimPercent) / 100;
  return constrain(trimmed, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT);
}

bool startupAssistActive(unsigned long now) {
  return startupAssistUntilMs != 0 && (long)(startupAssistUntilMs - now) > 0;
}

const char *startupAssistModeName(StartupAssistMode mode) {
  switch (mode) {
    case STARTUP_ASSIST_STRAIGHT:
      return "straight";
    case STARTUP_ASSIST_TURN:
      return "turn";
    case STARTUP_ASSIST_NONE:
    default:
      return "none";
  }
}

float absFloat(float value) {
  return value < 0.0f ? -value : value;
}

bool mspdFreshForStartup(unsigned long now) {
  return lastMspdFrameMs != 0 && now - lastMspdFrameMs <= STARTUP_ASSIST_MSPD_MAX_AGE_MS;
}

bool mspdStationaryForStartup(unsigned long now) {
  if (!mspdFreshForStartup(now)) {
    return false;
  }

  return absFloat(latestMspdM1) <= STARTUP_ASSIST_MSPD_ZERO_LIMIT &&
         absFloat(latestMspdM2) <= STARTUP_ASSIST_MSPD_ZERO_LIMIT &&
         absFloat(latestMspdM3) <= STARTUP_ASSIST_MSPD_ZERO_LIMIT &&
         absFloat(latestMspdM4) <= STARTUP_ASSIST_MSPD_ZERO_LIMIT;
}

int applyStartupAssist(int output, int minimumAbs) {
  if (output == 0) {
    return 0;
  }

  int magnitude = abs(output);
  if (magnitude >= minimumAbs) {
    return output;
  }

  return output > 0 ? minimumAbs : -minimumAbs;
}

bool isPureTurnTarget(int m1, int m2, int m3, int m4) {
  return m1 != 0 && m1 == m2 && m3 == m4 && m1 == -m3;
}

bool turnBreakawayKickActive(unsigned long now) {
  return startupAssistMode == STARTUP_ASSIST_TURN &&
         startupAssistStartMs != 0 &&
         now - startupAssistStartMs < TURN_BREAKAWAY_KICK_MS;
}

bool straightBreakawayKickActive(unsigned long now) {
  return startupAssistMode == STARTUP_ASSIST_STRAIGHT &&
         startupAssistStartMs != 0 &&
         now - startupAssistStartMs < STRAIGHT_BREAKAWAY_KICK_MS;
}

bool softwareWheelsAreZero() {
  return targetM1 == 0 && targetM2 == 0 && targetM3 == 0 && targetM4 == 0 &&
         currentM1 == 0 && currentM2 == 0 && currentM3 == 0 && currentM4 == 0;
}

bool stopCommandIsRedundant() {
  return owner == SOURCE_NONE &&
         systemState != MANUAL_ACTIVE &&
         systemState != REVERSAL_BLOCKED &&
         softwareWheelsAreZero() &&
         !startupAssistActive(millis());
}

StartupAssistMode startupAssistModeForCommand(int left, int right) {
  if (left == right && abs(left) >= 12) {
    return STARTUP_ASSIST_STRAIGHT;
  }

  if (left == -right && abs(left) >= 5) {
    return STARTUP_ASSIST_TURN;
  }

  return STARTUP_ASSIST_NONE;
}

unsigned long startupAssistDurationMs(StartupAssistMode mode) {
  switch (mode) {
    case STARTUP_ASSIST_STRAIGHT:
      return STRAIGHT_STARTUP_ASSIST_MS;
    case STARTUP_ASSIST_TURN:
      return TURN_STARTUP_ASSIST_MS;
    case STARTUP_ASSIST_NONE:
    default:
      return 0;
  }
}

void sendSpeed(int m1, int m2, int m3, int m4) {
  char cmd[40];
  snprintf(cmd, sizeof(cmd), "$spd:%d,%d,%d,%d#",
           constrain(m1, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT),
           constrain(m2, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT),
           constrain(m3, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT),
           constrain(m4, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT));
  sendMotorCommand(cmd);
}

void sendDriveSpeed(int m1, int m2, int m3, int m4) {
  unsigned long now = millis();
  int outputM1 = applyTrim(m1, M1_TRIM_PERCENT);
  int outputM2 = applyTrim(m2, M2_TRIM_PERCENT);
  int outputM3 = applyTrim(m3, M3_TRIM_PERCENT);
  int outputM4 = applyTrim(m4, M4_TRIM_PERCENT);
  bool assistActive = startupAssistActive(now);
  bool turnFloorActive = isPureTurnTarget(m1, m2, m3, m4);
  bool turnKickActive = assistActive && turnFloorActive && turnBreakawayKickActive(now);
  bool straightKickActive = assistActive && straightBreakawayKickActive(now);
  bool straightStallCheckActive =
    assistActive &&
    startupAssistMode == STARTUP_ASSIST_STRAIGHT &&
    !straightKickActive &&
    mspdFreshForStartup(now);
  bool straightStallM1 = straightStallCheckActive && absFloat(latestMspdM1) < STRAIGHT_STALL_MSPD_LIMIT;
  bool straightStallM2 = straightStallCheckActive && absFloat(latestMspdM2) < STRAIGHT_STALL_MSPD_LIMIT;
  bool straightStallM3 = straightStallCheckActive && absFloat(latestMspdM3) < STRAIGHT_STALL_MSPD_LIMIT;
  bool straightStallM4 = straightStallCheckActive && absFloat(latestMspdM4) < STRAIGHT_STALL_MSPD_LIMIT;
  if (turnFloorActive) {
    outputM1 = applyStartupAssist(outputM1, TURN_HOLD_MIN_OUTPUT);
    outputM2 = applyStartupAssist(outputM2, TURN_HOLD_MIN_OUTPUT);
    outputM3 = applyStartupAssist(outputM3, TURN_HOLD_MIN_OUTPUT);
    outputM4 = applyStartupAssist(outputM4, TURN_HOLD_MIN_OUTPUT);
  }

  if (straightKickActive) {
    outputM1 = applyStartupAssist(outputM1, M1_STRAIGHT_BREAKAWAY_KICK_OUTPUT);
    outputM2 = applyStartupAssist(outputM2, M2_STRAIGHT_BREAKAWAY_KICK_OUTPUT);
    outputM3 = applyStartupAssist(outputM3, M3_STRAIGHT_BREAKAWAY_KICK_OUTPUT);
    outputM4 = applyStartupAssist(outputM4, M4_STRAIGHT_BREAKAWAY_KICK_OUTPUT);
  } else if (assistActive && startupAssistMode == STARTUP_ASSIST_STRAIGHT) {
    outputM1 = applyStartupAssist(outputM1, M1_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT);
    outputM2 = applyStartupAssist(outputM2, M2_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT);
    outputM3 = applyStartupAssist(outputM3, M3_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT);
    outputM4 = applyStartupAssist(outputM4, M4_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT);
  } else if (turnKickActive) {
    outputM1 = applyStartupAssist(outputM1, TURN_BREAKAWAY_KICK_OUTPUT);
    outputM2 = applyStartupAssist(outputM2, TURN_BREAKAWAY_KICK_OUTPUT);
    outputM3 = applyStartupAssist(outputM3, TURN_BREAKAWAY_KICK_OUTPUT);
    outputM4 = applyStartupAssist(outputM4, TURN_BREAKAWAY_KICK_OUTPUT);
  } else if (assistActive && startupAssistMode == STARTUP_ASSIST_TURN) {
    outputM1 = applyStartupAssist(outputM1, TURN_STARTUP_ASSIST_MIN_OUTPUT);
    outputM2 = applyStartupAssist(outputM2, TURN_STARTUP_ASSIST_MIN_OUTPUT);
    outputM3 = applyStartupAssist(outputM3, TURN_STARTUP_ASSIST_MIN_OUTPUT);
    outputM4 = applyStartupAssist(outputM4, TURN_STARTUP_ASSIST_MIN_OUTPUT);
  }

  // Recover only the wheels whose fresh AT8236 velocity telemetry still says
  // "not moving".  This handles the observed M1/M4 reverse-direction stall
  // without reintroducing a permanent left/right speed bias.
  if (straightStallM1) outputM1 = applyStartupAssist(outputM1, STRAIGHT_STALL_BOOST_OUTPUT);
  if (straightStallM2) outputM2 = applyStartupAssist(outputM2, STRAIGHT_STALL_BOOST_OUTPUT);
  if (straightStallM3) outputM3 = applyStartupAssist(outputM3, STRAIGHT_STALL_BOOST_OUTPUT);
  if (straightStallM4) outputM4 = applyStartupAssist(outputM4, STRAIGHT_STALL_BOOST_OUTPUT);
  sendSpeed(outputM1, outputM2, outputM3, outputM4);

  if (usbDiagnosticsEnabled &&
      (lastDiagnosticDriveLogMs == 0 || now - lastDiagnosticDriveLogMs >= USB_DIAGNOSTIC_SAMPLE_MS)) {
    lastDiagnosticDriveLogMs = now;
    usbDiagnostic(
      "drive_output",
      "seq=" + String(lastMotionCommandSequence) +
        ",current=" + String(currentM1) + "," + String(currentM2) + "," +
        String(currentM3) + "," + String(currentM4) +
        ",spd=" + String(outputM1) + "," + String(outputM2) + "," +
        String(outputM3) + "," + String(outputM4) +
        ",turn_floor=" + String(turnFloorActive ? 1 : 0) +
        ",startup_assist=" + String(assistActive ? 1 : 0) +
        ",startup_assist_mode=" + String(assistActive ? startupAssistModeName(startupAssistMode) : "none") +
        ",straight_kick=" + String(straightKickActive ? 1 : 0) +
        ",straight_stall_mask=" + String(straightStallM1 ? 1 : 0) +
          String(straightStallM2 ? 1 : 0) + String(straightStallM3 ? 1 : 0) +
          String(straightStallM4 ? 1 : 0) +
        ",turn_kick=" + String(turnKickActive ? 1 : 0) +
        ",mspd=" + String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
        String(latestMspdM3, 2) + "," + String(latestMspdM4, 2) +
        ",mspd_age_ms=" + (lastMspdFrameMs == 0 ? String(-1) : String((long)(now - lastMspdFrameMs))));
  }
}

void zeroTargetsAndCurrents() {
  targetM1 = 0;
  targetM2 = 0;
  targetM3 = 0;
  targetM4 = 0;
  currentM1 = 0;
  currentM2 = 0;
  currentM3 = 0;
  currentM4 = 0;
  startupAssistUntilMs = 0;
  startupAssistStartMs = 0;
  startupAssistMode = STARTUP_ASSIST_NONE;
}

void clearReversalHistory() {
  hasLastNonzeroTarget = false;
  lastNonzeroM1 = 0;
  lastNonzeroM2 = 0;
  lastNonzeroM3 = 0;
  lastNonzeroM4 = 0;
  reversalNeutralSinceMs = 0;
}

void sendImmediateStopToDriver() {
  zeroTargetsAndCurrents();
  sendMotorCommand("$spd:0,0,0,0#");
  delay(20);
  sendMotorCommand("$pwm:0,0,0,0#");
  usbDiagnostic("immediate_stop", "seq=" + String(lastMotionCommandSequence));
}

void releaseOwner() {
  owner = SOURCE_NONE;
  ownerLastActivityMs = 0;
  lastMotionCommandMs = 0;
}

void enterState(SystemState nextState) {
  if (systemState != nextState) {
    usbDiagnostic(
      "state",
      "from=" + String(stateName(systemState)) + ",to=" + String(stateName(nextState)));
  }
  systemState = nextState;
}

void stopAndRelease(SystemState nextState) {
  sendImmediateStopToDriver();
  releaseOwner();
  clearReversalHistory();
  if (!isLatchedState()) {
    enterState(nextState);
  }
}

void enterLatchedFault(SystemState faultState) {
  sendImmediateStopToDriver();
  releaseOwner();
  enterState(faultState);
}

void sendToUsb(const String &line) {
  Serial.print(line);
}

void sendToBle(const String &line) {
  if (!bleClientConnected || txCharacteristic == NULL) {
    return;
  }
  txCharacteristic->setValue(line.c_str());
  txCharacteristic->notify();
}

void sendLine(ControlSource source, const String &line) {
  if (source == SOURCE_USB) {
    sendToUsb(line);
  } else if (source == SOURCE_BLE) {
    sendToBle(line);
  }
}

void sendReadyAfterHandshake(ControlSource source) {
  if (at8236Ready && systemState == READY_STOP) {
    sendLine(source, "r\n");
    readyNotificationTarget = SOURCE_NONE;
  }
}

int moveToward(int current, int target, int step) {
  if (current < target) {
    current += step;
    if (current > target) {
      current = target;
    }
  } else if (current > target) {
    current -= step;
    if (current < target) {
      current = target;
    }
  }
  return current;
}

void mixChassisToWheels(int vx, int vy, int wz, int &m1, int &m2, int &m3, int &m4) {
  vx = constrain(vx, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);
  vy = constrain(vy, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);
  wz = constrain(wz, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);

  m1 = M1_FORWARD_SIGN * (vx + vy - wz);
  m2 = M2_FORWARD_SIGN * (vx - vy + wz);
  m3 = M3_FORWARD_SIGN * (vx - vy - wz);
  m4 = M4_FORWARD_SIGN * (vx + vy + wz);

  int maxAbs = max(max(abs(m1), abs(m2)), max(abs(m3), abs(m4)));
  if (maxAbs > MAX_WHEEL_OUTPUT) {
    m1 = (m1 * MAX_WHEEL_OUTPUT) / maxAbs;
    m2 = (m2 * MAX_WHEEL_OUTPUT) / maxAbs;
    m3 = (m3 * MAX_WHEEL_OUTPUT) / maxAbs;
    m4 = (m4 * MAX_WHEEL_OUTPUT) / maxAbs;
  }
}

void calculateTankTargets(int left, int right, int &m1, int &m2, int &m3, int &m4) {
  left = constrain(left, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);
  right = constrain(right, -PROTOCOL_INPUT_LIMIT, PROTOCOL_INPUT_LIMIT);
  int vx = (left + right) / 2;
  int wz = (right - left) / 2;
  mixChassisToWheels(vx, 0, wz, m1, m2, m3, m4);
}

void setWheelTargets(int m1, int m2, int m3, int m4) {
  targetM1 = constrain(m1, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT);
  targetM2 = constrain(m2, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT);
  targetM3 = constrain(m3, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT);
  targetM4 = constrain(m4, -MAX_WHEEL_OUTPUT, MAX_WHEEL_OUTPUT);
}

void setTankTargets(int left, int right) {
  int m1, m2, m3, m4;
  calculateTankTargets(left, right, m1, m2, m3, m4);
  setWheelTargets(m1, m2, m3, m4);
}

bool signReverses(int previous, int next) {
  return previous != 0 && next != 0 && ((previous > 0) != (next > 0));
}

bool requiresReversalBlock(int m1, int m2, int m3, int m4) {
  if (!hasLastNonzeroTarget) return false;
  return signReverses(lastNonzeroM1, m1) ||
         signReverses(lastNonzeroM2, m2) ||
         signReverses(lastNonzeroM3, m3) ||
         signReverses(lastNonzeroM4, m4);
}

void rememberNonzeroTargets() {
  lastNonzeroM1 = targetM1;
  lastNonzeroM2 = targetM2;
  lastNonzeroM3 = targetM3;
  lastNonzeroM4 = targetM4;
  hasLastNonzeroTarget = true;
  reversalNeutralSinceMs = 0;
}

void beginReversalBlock() {
  sendImmediateStopToDriver();
  releaseOwner();
  reversalNeutralSinceMs = 0;
  enterState(REVERSAL_BLOCKED);
  usbDiagnostic(
    "reversal_block",
    "last_target=" + String(lastNonzeroM1) + "," + String(lastNonzeroM2) + "," +
      String(lastNonzeroM3) + "," + String(lastNonzeroM4));
}

void startReversalNeutralWindow() {
  if (systemState == REVERSAL_BLOCKED && reversalNeutralSinceMs == 0) {
    reversalNeutralSinceMs = millis();
    usbDiagnostic("reversal_neutral", "started=1,mspd=" +
      String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
      String(latestMspdM3, 2) + "," + String(latestMspdM4, 2));
  }
}

bool canAcceptMotion(ControlSource source, int left, int right) {
  if (isLatchedState()) {
    return false;
  }
  if (!at8236Ready || systemState == BOOT_STOP) {
    return false;
  }
  if (systemState == REVERSAL_BLOCKED) {
    return false;
  }
  if (left == 0 && right == 0) {
    return true;
  }
  return owner == SOURCE_NONE || owner == source;
}

void refreshActivity(ControlSource source) {
  if (owner == source) {
    ownerLastActivityMs = millis();
  }
}

void reportError(ControlSource source, const String &reason) {
  usbDiagnostic("error", "source=" + String(sourceName(source)) + ",reason=" + reason);
  sendLine(source, "!ERR," + reason + "\n");
}

void handleProtocolError(ControlSource source, const String &reason) {
  reportError(source, reason);
  if (owner == source && systemState == MANUAL_ACTIVE) {
    stopAndRelease(COM_TIMEOUT);
  }
}

void printStatusToUsb() {
  String line = "!Q,state=";
  line += stateName(systemState);
  line += ",owner=";
  line += sourceName(owner);
  line += ",ble=";
  line += bleClientConnected ? "1" : "0";
  line += ",ready=";
  line += at8236Ready ? "1" : "0";
  line += ",timeout_ms=";
  line += String(commandTimeoutMs);
  line += ",target=";
  line += String(targetM1) + "," + String(targetM2) + "," + String(targetM3) + "," + String(targetM4);
  line += ",current=";
  line += String(currentM1) + "," + String(currentM2) + "," + String(currentM3) + "," + String(currentM4);
  line += ",motor_frame_age_ms=";
  line += lastValidMotorFrameMs == 0 ? String(-1) : String((long)(millis() - lastValidMotorFrameMs));
  line += ",mspd=";
  line += String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
          String(latestMspdM3, 2) + "," + String(latestMspdM4, 2);
  line += ",mspd_age_ms=";
  line += lastMspdFrameMs == 0 ? String(-1) : String((long)(millis() - lastMspdFrameMs));
  line += ",startup_assist=";
  line += (startupAssistActive(millis()) ? "1" : "0");
  line += ",startup_assist_mode=";
  line += (startupAssistActive(millis()) ? startupAssistModeName(startupAssistMode) : "none");
  line += ",diag=";
  line += usbDiagnosticsEnabled ? "1" : "0";
  line += ",motion_count=";
  line += String(motionCommandCount);
  line += ",last_motion_seq=";
  line += String(lastMotionCommandSequence);
  line += ",last_motion_source=";
  line += sourceName(lastMotionCommandSource);
  line += ",last_motion=";
  line += String(lastMotionCommandLeft) + "," + String(lastMotionCommandRight);
  line += ",last_motion_accepted=";
  line += lastMotionCommandAccepted ? "1" : "0";
  line += ",last_motion_age_ms=";
  line += lastMotionCommandReceivedMs == 0 ? String(-1) : String((long)(millis() - lastMotionCommandReceivedMs));
  line += ",reversal_blocked=";
  line += systemState == REVERSAL_BLOCKED ? "1" : "0";
  line += ",reversal_neutral_age_ms=";
  line += reversalNeutralSinceMs == 0 ? String(-1) : String((long)(millis() - reversalNeutralSinceMs));
  line += ",last_nonzero_target=";
  line += String(lastNonzeroM1) + "," + String(lastNonzeroM2) + "," +
          String(lastNonzeroM3) + "," + String(lastNonzeroM4);
  line += "\n";
  sendToUsb(line);
}

bool parseLongStrict(const String &text, long &value) {
  if (text.length() == 0) {
    return false;
  }
  char *endPtr = NULL;
  value = strtol(text.c_str(), &endPtr, 10);
  return endPtr != text.c_str() && *endPtr == '\0';
}

bool parseCsvPair(const String &payload, long &first, long &second) {
  int comma = payload.indexOf(',');
  if (comma <= 0 || comma >= payload.length() - 1) {
    return false;
  }
  return parseLongStrict(payload.substring(0, comma), first) &&
         parseLongStrict(payload.substring(comma + 1), second);
}

void handleMotionCommand(ControlSource source, const String &line) {
  long left = 0;
  long right = 0;
  if (!parseCsvPair(line.substring(1), left, right)) {
    handleProtocolError(source, "c format");
    return;
  }

  if (left < -PROTOCOL_INPUT_LIMIT || left > PROTOCOL_INPUT_LIMIT ||
      right < -PROTOCOL_INPUT_LIMIT || right > PROTOCOL_INPUT_LIMIT) {
    handleProtocolError(source, "c range");
    return;
  }

  if (left == 0 && right == 0) {
    if (stopCommandIsRedundant()) {
      lastMotionCommandAccepted = true;
      if (!isLatchedState() && at8236Ready && systemState != READY_STOP) {
        enterState(READY_STOP);
      }
      sendLine(source, "!OK,stop\n");
      return;
    }

    recordMotionCommand(source, (int)left, (int)right);
    lastMotionCommandAccepted = true;
    sendImmediateStopToDriver();
    if (!isLatchedState()) {
      releaseOwner();
      if (systemState == REVERSAL_BLOCKED) {
        // pollTimeouts() starts the neutral timer only after fresh telemetry
        // proves every wheel is actually stopped.
      } else {
        // $spd:0 makes the controller stop commanding the wheels, but it
        // cannot make a moving wheel physically reach zero at once.  Keep
        // the previous direction through an explicit c0,0 and hold the next
        // non-zero command until fresh MSPD proves a full neutral interval.
        // This closes the BLE race: forward -> c0,0 -> reverse can no longer
        // energize a reverse command while any wheel is still coasting ahead.
        if (hasLastNonzeroTarget) {
          reversalNeutralSinceMs = 0;
          enterState(REVERSAL_BLOCKED);
          usbDiagnostic(
            "reversal_wait",
            "reason=explicit_stop,last_target=" + String(lastNonzeroM1) + "," +
              String(lastNonzeroM2) + "," + String(lastNonzeroM3) + "," +
              String(lastNonzeroM4) + ",zero_limit=" +
              String(STARTUP_ASSIST_MSPD_ZERO_LIMIT, 2));
        } else {
          enterState(at8236Ready ? READY_STOP : BOOT_STOP);
        }
      }
    }
    sendLine(source, "!OK,stop\n");
    return;
  }

  recordMotionCommand(source, (int)left, (int)right);

  if (systemState == REVERSAL_BLOCKED) {
    // Android keeps sending the held direction roughly every 100 ms.  Those
    // frames must stay rejected until the wheels have settled, but they must
    // not restart the already-running neutral timer; otherwise a user who
    // holds Reverse after Forward can never leave REVERSAL_BLOCKED.
    usbDiagnostic(
      "reversal_reject",
      "reason=neutral_required,neutral_age_ms=" +
        (reversalNeutralSinceMs == 0 ? String(-1) :
          String((long)(millis() - reversalNeutralSinceMs))));
    reportError(source, "reversal/neutral");
    return;
  }

  if (!canAcceptMotion(source, (int)left, (int)right)) {
    reportError(source, isLatchedState() ? "latched" : "owner/busy");
    return;
  }

  int nextM1, nextM2, nextM3, nextM4;
  calculateTankTargets((int)left, (int)right, nextM1, nextM2, nextM3, nextM4);
  if (requiresReversalBlock(nextM1, nextM2, nextM3, nextM4)) {
    beginReversalBlock();
    reportError(source, "reversal/neutral");
    return;
  }

  unsigned long now = millis();
  // BLE may deliver a second refresh before the 40 ms control task sends the
  // first non-zero current.  Do not restart the same launch-assist window in
  // that gap; restarting it makes the breakaway duration depend on BLE timing.
  bool startupAssistInProgress =
    startupAssistMode != STARTUP_ASSIST_NONE && startupAssistActive(now);
  bool startingFromStop =
    currentM1 == 0 && currentM2 == 0 && currentM3 == 0 && currentM4 == 0 &&
    !startupAssistInProgress;
  if (startingFromStop && !mspdStationaryForStartup(now)) {
    startupAssistUntilMs = 0;
    startupAssistStartMs = 0;
    startupAssistMode = STARTUP_ASSIST_NONE;
    usbDiagnostic(
      "motion_start_blocked",
      "reason=mspd_not_stationary,mspd=" +
        String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
        String(latestMspdM3, 2) + "," + String(latestMspdM4, 2) +
        ",mspd_age_ms=" +
        (lastMspdFrameMs == 0 ? String(-1) : String((long)(now - lastMspdFrameMs))));
    sendImmediateStopToDriver();
    releaseOwner();
    if (!isLatchedState()) {
      enterState(at8236Ready ? READY_STOP : BOOT_STOP);
    }
    reportError(source, "settling");
    return;
  }

  if (owner == SOURCE_NONE) {
    // A USB h<timeout> setting is useful for a supervised single-command
    // bench test, but must never silently weaken the normal BLE deadman.
    // The Android controller refreshes c continuously, so its session always
    // starts from the 500 ms safety timeout.
    if (source == SOURCE_BLE && commandTimeoutMs != DEFAULT_COMMAND_TIMEOUT_MS) {
      usbDiagnostic(
        "ble_timeout_reset",
        "from_ms=" + String(commandTimeoutMs) +
          ",to_ms=" + String(DEFAULT_COMMAND_TIMEOUT_MS));
      commandTimeoutMs = DEFAULT_COMMAND_TIMEOUT_MS;
    }
    owner = source;
  }

  setWheelTargets(nextM1, nextM2, nextM3, nextM4);
  if (startingFromStop) {
    startupAssistMode = startupAssistModeForCommand((int)left, (int)right);
    unsigned long assistDurationMs = startupAssistDurationMs(startupAssistMode);
    startupAssistUntilMs = assistDurationMs == 0 ? 0 : now + assistDurationMs;
    startupAssistStartMs = assistDurationMs == 0 ? 0 : now;

    if (startupAssistMode == STARTUP_ASSIST_STRAIGHT) {
      usbDiagnostic(
        "startup_assist",
        "mode=straight,duration_ms=" + String(assistDurationMs) +
          ",kick_ms=" + String(STRAIGHT_BREAKAWAY_KICK_MS) +
          ",kick_output=" + String(M1_STRAIGHT_BREAKAWAY_KICK_OUTPUT) + "/" +
            String(M2_STRAIGHT_BREAKAWAY_KICK_OUTPUT) + "/" +
            String(M3_STRAIGHT_BREAKAWAY_KICK_OUTPUT) + "/" +
            String(M4_STRAIGHT_BREAKAWAY_KICK_OUTPUT) +
          ",straight_start_min=" + String(M1_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT) + "/" +
            String(M2_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT) + "/" +
            String(M3_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT) + "/" +
            String(M4_STRAIGHT_STARTUP_ASSIST_MIN_OUTPUT) +
          ",stall_boost=" + String(STRAIGHT_STALL_BOOST_OUTPUT) +
          ",mspd=" + String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
          String(latestMspdM3, 2) + "," + String(latestMspdM4, 2));
    } else if (startupAssistMode == STARTUP_ASSIST_TURN) {
      usbDiagnostic(
        "startup_assist",
        "mode=turn,duration_ms=" + String(assistDurationMs) +
          ",kick_ms=" + String(TURN_BREAKAWAY_KICK_MS) +
          ",kick_output=" + String(TURN_BREAKAWAY_KICK_OUTPUT) +
          ",turn_start_min=" + String(TURN_STARTUP_ASSIST_MIN_OUTPUT) +
          ",turn_hold_min=" + String(TURN_HOLD_MIN_OUTPUT) +
          ",mspd=" + String(latestMspdM1, 2) + "," + String(latestMspdM2, 2) + "," +
          String(latestMspdM3, 2) + "," + String(latestMspdM4, 2));
    } else {
      usbDiagnostic(
        "startup_assist_disabled",
        "reason=unsupported_motion,left=" + String(left) + ",right=" + String(right));
    }
  }
  rememberNonzeroTargets();
  recordMotionTargets();
  ownerLastActivityMs = now;
  lastMotionCommandMs = ownerLastActivityMs;
  enterState(MANUAL_ACTIVE);
  sendLine(source, "!OK,c\n");
}

void handleTimeoutCommand(ControlSource source, const String &line) {
  long timeoutMs = 0;
  if (!parseLongStrict(line.substring(1), timeoutMs)) {
    handleProtocolError(source, "h format");
    return;
  }

  if (timeoutMs < (long)MIN_COMMAND_TIMEOUT_MS || timeoutMs > (long)MAX_COMMAND_TIMEOUT_MS) {
    handleProtocolError(source, "h range");
    return;
  }

  if (owner != SOURCE_NONE && owner != source) {
    reportError(source, "owner/busy");
    return;
  }

  commandTimeoutMs = (unsigned long)timeoutMs;
  refreshActivity(source);
  if (!isLatchedState() && at8236Ready && owner == SOURCE_NONE &&
      systemState != MANUAL_ACTIVE && systemState != REVERSAL_BLOCKED) {
    enterState(READY_STOP);
  }
  sendLine(source, "!OK,h\n");
}

void handleFeatureQuery(ControlSource source) {
  sendLine(source, "fCART_AT8236:\n");
  readyNotificationTarget = source;
  sendReadyAfterHandshake(source);
}

void handleEmergencyStop(ControlSource source, const String &line) {
  if (!line.startsWith("!S,")) {
    handleProtocolError(source, "!S format");
    return;
  }

  long sequence = 0;
  if (!parseLongStrict(line.substring(3), sequence) || sequence <= 0) {
    handleProtocolError(source, "!S format");
    return;
  }

  if ((unsigned long)sequence <= lastEmergencySequence) {
    reportError(source, "!S stale");
    return;
  }
  lastEmergencySequence = (unsigned long)sequence;

  enterLatchedFault(EMERGENCY_STOP);
  sendLine(source, "!OK,!S\n");
}

void handleDiagnosticsCommand(ControlSource source, const String &line) {
  if (source != SOURCE_USB) {
    reportError(source, "!D usb_only");
    return;
  }

  if (line == "!D,0") {
    usbDiagnosticsEnabled = false;
    sendToUsb("!OK,!D,0\n");
    return;
  }

  if (line == "!D,1") {
    usbDiagnosticsEnabled = true;
    lastDiagnosticDriveLogMs = 0;
    sendToUsb("!OK,!D,1\n");
    usbDiagnostic("diagnostics", "enabled=1");
    return;
  }

  handleProtocolError(source, "!D format");
}

void processCommand(ControlSource source, const String &line) {
  if (line.length() == 0) {
    return;
  }

  if (line.charAt(0) == 'c') {
    handleMotionCommand(source, line);
    return;
  }

  if (line.charAt(0) == 'h') {
    handleTimeoutCommand(source, line);
    return;
  }

  if (line == "f") {
    handleFeatureQuery(source);
    return;
  }

  if (line.startsWith("!S")) {
    handleEmergencyStop(source, line);
    return;
  }

  if (line.startsWith("!D")) {
    handleDiagnosticsCommand(source, line);
    return;
  }

  if (line == "!Q") {
    if (source != SOURCE_USB) {
      reportError(source, "!Q usb_only");
      return;
    }
    printStatusToUsb();
    return;
  }

  handleProtocolError(source, "unsupported");
}

void consumeIncomingByte(ControlSource source, LineBuffer &buffer, char c) {
  if (c == '\r') {
    return;
  }

  if (c == '\n') {
    if (buffer.overflow) {
      handleProtocolError(source, "line overflow");
    } else if (buffer.len > 0) {
      buffer.data[buffer.len] = '\0';
      processCommand(source, String(buffer.data));
    }
    buffer.len = 0;
    buffer.overflow = false;
    buffer.data[0] = '\0';
    return;
  }

  if (buffer.overflow) {
    return;
  }

  if (buffer.len >= MAX_PROTOCOL_LINE_LEN) {
    buffer.len = 0;
    buffer.overflow = true;
    buffer.data[0] = '\0';
    return;
  }

  buffer.data[buffer.len++] = c;
  buffer.data[buffer.len] = '\0';
}

bool isNumericTelemetryPayload(const String &payload, int minimumFields) {
  if (payload.length() == 0) return false;
  int fields = 1;
  bool digitInField = false;
  for (int i = 0; i < payload.length(); ++i) {
    char c = payload.charAt(i);
    if (isDigit(c)) {
      digitInField = true;
    } else if (c == ',' || c == ':') {
      if (!digitInField) return false;
      fields++;
      digitInField = false;
    } else if (c == '-' || c == '+' || c == '.' || c == ' ') {
      // AT8236 telemetry may contain signed or decimal values.
    } else {
      return false;
    }
  }
  return digitInField && fields >= minimumFields;
}

bool isRecognizedMotorFrame(const String &frame) {
  if (!frame.endsWith("#")) return false;

  const char *prefix = NULL;
  if (frame.startsWith("$MSPD:")) prefix = "$MSPD:";
  else if (frame.startsWith("$MTEP:")) prefix = "$MTEP:";
  else if (frame.startsWith("$MAll:")) prefix = "$MAll:";
  if (prefix == NULL) return false;

  int payloadStart = strlen(prefix);
  String payload = frame.substring(payloadStart, frame.length() - 1);
  return isNumericTelemetryPayload(payload, 4);
}

bool parseMspdFrame(const String &frame, float &m1, float &m2, float &m3, float &m4) {
  if (!frame.startsWith("$MSPD:") || !frame.endsWith("#")) {
    return false;
  }

  String payload = frame.substring(6, frame.length() - 1);
  float values[4] = {0.0f, 0.0f, 0.0f, 0.0f};
  int start = 0;
  for (int i = 0; i < 4; ++i) {
    int end = (i == 3) ? payload.length() : payload.indexOf(',', start);
    if (end < start) {
      return false;
    }
    String token = payload.substring(start, end);
    token.trim();
    if (token.length() == 0) {
      return false;
    }
    values[i] = token.toFloat();
    start = end + 1;
  }
  if (start < payload.length() + 1) {
    return false;
  }

  m1 = values[0];
  m2 = values[1];
  m3 = values[2];
  m4 = values[3];
  return true;
}

void updateReadyStateFromTelemetry() {
  if (!at8236Ready && lastValidMotorFrameMs != 0) {
    at8236Ready = true;
    if (!isLatchedState() && owner == SOURCE_NONE && systemState == BOOT_STOP) {
      enterState(READY_STOP);
    }
  }
}

void readMotorFrames() {
  while (MotorSerial.available() > 0) {
    char c = (char)MotorSerial.read();

    if (c == '$') {
      motorFrame = "$";
      continue;
    }

    if (motorFrame.length() == 0) {
      continue;
    }

    motorFrame += c;
    if (c == '#') {
      if (isRecognizedMotorFrame(motorFrame)) {
        lastValidMotorFrameMs = millis();
        if (parseMspdFrame(motorFrame, latestMspdM1, latestMspdM2, latestMspdM3, latestMspdM4)) {
          lastMspdFrameMs = lastValidMotorFrameMs;
        }
        updateReadyStateFromTelemetry();
      }
      motorFrame = "";
    } else if (motorFrame.length() > MAX_MOTOR_FRAME_LEN) {
      motorFrame = "";
    }
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
  sendImmediateStopToDriver();
}

class OpenBotBleServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *server) override {
    (void)server;
    bleClientConnected = true;
    readyNotificationTarget = SOURCE_NONE;
  }

  void onDisconnect(BLEServer *server) override {
    (void)server;
    bleClientConnected = false;
    bleAdvertisingNeedsRestart = true;
    readyNotificationTarget = SOURCE_NONE;
    // The callback only records the event. Motor I/O and state mutation stay in loop().
    bleDisconnectPending = true;
  }
};

class OpenBotBleRxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    auto value = characteristic->getValue();
    for (size_t i = 0; i < value.length(); ++i) {
      char c = value[i];
      if (bleRxQueue == NULL || xQueueSend(bleRxQueue, &c, 0) != pdTRUE) {
        bleRxOverflowPending = true;
      }
    }
  }
};

void setupBle() {
  bleRxQueue = xQueueCreate(BLE_RX_QUEUE_LEN, sizeof(char));
  BLEDevice::init(BLE_DEVICE_NAME);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new OpenBotBleServerCallbacks());

  BLEService *service = bleServer->createService(BLE_SERVICE_UUID);

  txCharacteristic = service->createCharacteristic(
    BLE_TX_UUID,
    BLECharacteristic::PROPERTY_NOTIFY);
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
    usbDiagnostic("ble_disconnect");
    if (owner == SOURCE_BLE && !isLatchedState()) {
      stopAndRelease(COM_TIMEOUT);
    }
    bleLineBuffer = {{0}, 0, false};
    if (bleRxQueue != NULL) xQueueReset(bleRxQueue);
  }

  if (bleRxOverflowPending) {
    bleRxOverflowPending = false;
    handleProtocolError(SOURCE_BLE, "rx queue overflow");
    bleLineBuffer = {{0}, 0, false};
    if (bleRxQueue != NULL) xQueueReset(bleRxQueue);
  }

  char c;
  while (bleRxQueue != NULL && xQueueReceive(bleRxQueue, &c, 0) == pdTRUE) {
    consumeIncomingByte(SOURCE_BLE, bleLineBuffer, c);
  }
}

void pollUsbSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    consumeIncomingByte(SOURCE_USB, usbLineBuffer, c);
  }
}

void pollTimeouts() {
  unsigned long now = millis();

  if (systemState == REVERSAL_BLOCKED) {
    // Do not use only elapsed time after c0,0.  The physical cart may still
    // coast, especially after a straight-line startup assist.  The entire
    // neutral window must consist of fresh, near-zero MSPD from all wheels.
    if (!mspdStationaryForStartup(now)) {
      if (reversalNeutralSinceMs != 0) {
        usbDiagnostic(
          "reversal_neutral",
          "reset=motion,mspd=" + String(latestMspdM1, 2) + "," +
            String(latestMspdM2, 2) + "," + String(latestMspdM3, 2) + "," +
            String(latestMspdM4, 2));
      }
      reversalNeutralSinceMs = 0;
    } else if (reversalNeutralSinceMs == 0) {
      startReversalNeutralWindow();
    } else if (now - reversalNeutralSinceMs >= REVERSAL_NEUTRAL_MS) {
      clearReversalHistory();
      enterState(at8236Ready ? READY_STOP : BOOT_STOP);
      usbDiagnostic("reversal_rearmed", "neutral_ms=" + String(REVERSAL_NEUTRAL_MS));
    }
  }

  if (!at8236Ready && now - bootStartMs > AT8236_BOOT_WAIT_MS && lastValidMotorFrameMs == 0) {
    enterState(BOOT_STOP);
  }

  if (systemState == MANUAL_ACTIVE && owner != SOURCE_NONE && now - ownerLastActivityMs > commandTimeoutMs) {
    usbDiagnostic("communication_timeout", "age_ms=" + String(now - ownerLastActivityMs));
    stopAndRelease(COM_TIMEOUT);
  }

  // Heartbeats prove that the link is alive; repeated c commands prove that the
  // control producer is alive.  The default freshness interval is 500 ms.  A
  // deliberate h<timeout_ms> command may extend both intervals together for
  // USB/bench manual testing, but never beyond the bounded safety maximum.
  if (systemState == MANUAL_ACTIVE && owner != SOURCE_NONE &&
      now - lastMotionCommandMs > commandTimeoutMs) {
    usbDiagnostic(
      "motion_timeout",
      "age_ms=" + String(now - lastMotionCommandMs) +
        ",limit_ms=" + String(commandTimeoutMs));
    stopAndRelease(COM_TIMEOUT);
  }

  if ((systemState == MANUAL_ACTIVE || systemState == REVERSAL_BLOCKED) &&
      lastValidMotorFrameMs != 0 &&
      now - lastValidMotorFrameMs > AT8236_ACTIVE_TIMEOUT_MS) {
    usbDiagnostic("driver_timeout", "age_ms=" + String(now - lastValidMotorFrameMs));
    enterLatchedFault(DRIVER_ERROR);
  }
}

void updateControlLoop() {
  if (systemState != MANUAL_ACTIVE) {
    return;
  }

  unsigned long now = millis();
  if (now - lastControlUpdateMs < CONTROL_UPDATE_MS) {
    return;
  }
  lastControlUpdateMs = now;

  currentM1 = moveToward(currentM1, targetM1, CONTROL_RAMP_STEP);
  currentM2 = moveToward(currentM2, targetM2, CONTROL_RAMP_STEP);
  currentM3 = moveToward(currentM3, targetM3, CONTROL_RAMP_STEP);
  currentM4 = moveToward(currentM4, targetM4, CONTROL_RAMP_STEP);
  sendDriveSpeed(currentM1, currentM2, currentM3, currentM4);
}

void serviceBleAdvertising() {
  if (bleAdvertisingNeedsRestart) {
    delay(50);
    bleServer->startAdvertising();
    bleAdvertisingNeedsRestart = false;
    if (!isLatchedState() && at8236Ready && owner == SOURCE_NONE &&
        systemState != BOOT_STOP && systemState != REVERSAL_BLOCKED) {
      enterState(READY_STOP);
    }
  }
}

void setup() {
  Serial.begin(USB_BAUD);
  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);

  zeroTargetsAndCurrents();
  releaseOwner();
  enterState(BOOT_STOP);
  bootStartMs = millis();

  initAT8236();
  setupBle();

  sendToUsb("ESP32 AT8236 OpenBot BLE safe remote booting\n");
}

void loop() {
  pollUsbSerial();
  serviceBleEvents();
  readMotorFrames();
  serviceBleAdvertising();
  pollTimeouts();

  if (at8236Ready && !isLatchedState() && owner == SOURCE_NONE && systemState == BOOT_STOP) {
    enterState(READY_STOP);
  }

  if (systemState != MANUAL_ACTIVE &&
      at8236Ready &&
      !isLatchedState() &&
      owner == SOURCE_NONE &&
      systemState != COM_TIMEOUT &&
      systemState != REVERSAL_BLOCKED) {
    enterState(READY_STOP);
  }

  updateControlLoop();
  if (readyNotificationTarget != SOURCE_NONE) {
    sendReadyAfterHandshake(readyNotificationTarget);
  }
}
