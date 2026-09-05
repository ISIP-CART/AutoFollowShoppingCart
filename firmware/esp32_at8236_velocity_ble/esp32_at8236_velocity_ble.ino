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
    - A transient MSPD/braking fault holds zero and may recover only after
      fresh MSPD confirms all four wheels stopped continuously for 1 second.
    - Emergency stop, feedback sign mismatch and overspeed remain hard latches.
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include <VL53L1X.h>
#include <math.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;
static const unsigned long USB_BAUD = 115200;
static const unsigned long MOTOR_BAUD = 115200;

// Shared 3.3 V I2C bus: center URM09 plus two independently addressed ToF
// modules.  Keep the ToF XSHUT pins independent because both devices boot at
// address 0x29.
static const int I2C_SDA_PIN = 21;
static const int I2C_SCL_PIN = 22;
static const uint32_t I2C_FREQUENCY_HZ = 100000;
static const uint16_t I2C_TIMEOUT_MS = 25;
static const int LEFT_TOF_XSHUT_PIN = 25;
static const int RIGHT_TOF_XSHUT_PIN = 26;
static const uint8_t URM09_ADDRESS = 0x11;
static const uint8_t LEFT_TOF_ADDRESS = 0x2A;
static const uint8_t RIGHT_TOF_ADDRESS = 0x2B;
static const uint8_t URM09_DISTANCE_HIGH_REGISTER = 0x03;
static const uint8_t URM09_CONFIG_REGISTER = 0x07;
static const uint8_t URM09_COMMAND_REGISTER = 0x08;
static const unsigned long URM09_TRIGGER_PERIOD_MS = 120;
static const unsigned long URM09_MEASUREMENT_WAIT_MS = 100;
static const unsigned long TOF_CONTINUOUS_PERIOD_MS = 50;
static const uint32_t TOF_TIMING_BUDGET_US = 33000;
static const uint16_t TOF_MIN_VALID_MM = 40;
static const uint16_t TOF_MAX_VALID_MM = 1300;
static const uint16_t URM09_MIN_VALID_MM = 20;
static const uint16_t URM09_MAX_VALID_MM = 5000;
static const unsigned long SENSOR_STALE_MS = 200;
static const unsigned long MIN_SONAR_REPORT_MS = 50;
static const unsigned long MAX_SONAR_REPORT_MS = 1000;

// Range risks remain calculated and logged, but the current integration phase
// is observation-only: sensor state must not reject commands or brake motion.
// Set this true only after the range-safety policy and hardware tests are
// explicitly approved.  REQUIRE_RANGE_SENSORS_FOR_MOTION is retained as the
// future policy used when gating is enabled.
static const bool RANGE_MOTION_GATING_ENABLED = false;
static const int CENTER_STOP_MM = 300;
static const int CENTER_CLEAR_MM = 400;
static const int CORNER_STOP_MM = 200;
static const int CORNER_CLEAR_MM = 300;
static const int RISK_CLEAR_VALID_SAMPLES = 3;
static const bool REQUIRE_RANGE_SENSORS_FOR_MOTION = true;

// Parameters proven on the project cart.  Do not replace these with the
// generic values in the vendor example for a different 310 motor.
static const int AT8236_MOTOR_TYPE = 2;
static const int AT8236_GEAR_RATIO = 30;
static const int AT8236_ENCODER_LINES = 11;
static const float AT8236_WHEEL_DIAMETER_MM = 80.0f;
static const int AT8236_DEADZONE = 1600;

// Keep the existing OpenBot cart-follow range (logical 0..14) unchanged, with
// logical 14 at 240 mm/s.  Extend logical 15..21 as a second, steeper range for
// the new speed+direction controller; logical 21 reaches 600 mm/s.  This keeps
// the legacy Android behaviour stable while making a supervised indoor-follow
// range available.  Larger inputs remain compatible but saturate at the cap.
static const int PROTOCOL_INPUT_LIMIT = 255;
static const int PROTOCOL_LEGACY_FULL_SPEED_INPUT = 14;
static const int LEGACY_FULL_SPEED_MMPS = 240;
static const int PROTOCOL_FULL_SPEED_INPUT = 21;
static const int MAX_WHEEL_SPEED_MMPS = 600;
static const int MIN_MOVING_WHEEL_MMPS = 40;
static const int MIN_PIVOT_WHEEL_MMPS = 80;
static const int MAX_COUNTER_ROTATION_MMPS = 240;
static const int CONTROL_RAMP_STEP_MMPS = 20;
static const unsigned long CONTROL_PERIOD_MS = 50;

static const unsigned long DEFAULT_LINK_TIMEOUT_MS = 750;
static const unsigned long MIN_LINK_TIMEOUT_MS = 100;
static const unsigned long MAX_LINK_TIMEOUT_MS = 3000;
static const unsigned long MOTION_REFRESH_TIMEOUT_MS = 500;
static const unsigned long DRIVER_BOOT_TIMEOUT_MS = 3000;
static const unsigned long TELEMETRY_TIMEOUT_MS = 500;
static const unsigned long BRAKE_PID_GRACE_MS = 600;
static const unsigned long BRAKE_TELEMETRY_GRACE_MS = 1500;
static const unsigned long BRAKE_TIMEOUT_MS = 2000;
static const unsigned long ZERO_HOLD_MS = 400;
static const unsigned long DRIVER_RECOVERY_ZERO_HOLD_MS = 1000;
static const unsigned long IDLE_ZERO_REFRESH_MS = 200;
static const unsigned long LATCHED_ERROR_REPORT_INTERVAL_MS = 500;
static const float ZERO_SPEED_MMPS = 30.0f;
static const float BRAKE_FALLBACK_SPEED_MMPS = 120.0f;
static const float OVERSPEED_MIN_MMPS = 300.0f;
// Existing AT8236 captures show about 419..590 MSPD at the c14 operating point.
// A c14->c9 curve transition also showed 533 MSPD while the new inner-wheel
// target was 154 mm/s.  Keep 1.5x as diagnostics, use 4x for the settled
// dynamic check, and retain an independent 750 mm/s absolute hard stop.
static const float OVERSPEED_WARNING_RATIO = 1.5f;
static const float OVERSPEED_RATIO = 4.0f;
static const float OVERSPEED_ABSOLUTE_MMPS = 750.0f;
static const unsigned long FEEDBACK_FAULT_CONFIRM_MS = 120;
static const unsigned long OVERSPEED_TARGET_SETTLE_MS = 500;

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

enum RangeStatus {
  RANGE_VALID = 0,
  RANGE_INVALID = 1,
  SIGNAL_INVALID = 2,
  RANGE_STALE = 3,
  RANGE_BUS_ERROR = 4,
  RANGE_NOT_PRESENT = 5
};

struct RangeReading {
  bool present;
  int rawMm;
  int filteredMm;
  RangeStatus status;
  uint8_t deviceStatus;
  unsigned long lastSampleMs;
  unsigned long lastValidMs;
  int history[3];
  uint8_t historyCount;
  uint8_t historyIndex;
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
VL53L1X leftTof;
VL53L1X rightTof;

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
unsigned long driverRecoveryZeroSinceMs = 0;
unsigned long lastDriverRecoveryZeroMs = 0;
unsigned long lastEmergencySequence = 0;
unsigned long acceptedMotionCount = 0;
unsigned long lastFaultAtMs = 0;
long lastFaultMspdAgeMs = -1;
bool lastFaultRecoverable = false;
bool brakePidWarningReported = false;
String lastFaultReason = "none";
int lastFaultTargetMmps[4] = {0, 0, 0, 0};
int lastFaultCurrentMmps[4] = {0, 0, 0, 0};
float lastFaultMspd[4] = {0, 0, 0, 0};
unsigned long lastLatchedErrorReportMs[3] = {0, 0, 0};
unsigned long feedbackMismatchSinceMs[4] = {0, 0, 0, 0};
unsigned long overspeedSinceMs[4] = {0, 0, 0, 0};
unsigned long absoluteOverspeedSinceMs[4] = {0, 0, 0, 0};
unsigned long overspeedWarningSinceMs[4] = {0, 0, 0, 0};
bool overspeedWarningReported[4] = {false, false, false, false};
unsigned long targetSettledSinceMs[4] = {0, 0, 0, 0};
unsigned long sonarReportIntervalMs[3] = {0, 0, 0};
unsigned long lastSonarReportMs[3] = {0, 0, 0};
unsigned long urm09TriggerMs = 0;
bool urm09WaitingForResult = false;
bool centerRiskLatched = false;
bool leftRiskLatched = false;
bool rightRiskLatched = false;
uint8_t centerClearSamples = 0;
uint8_t leftClearSamples = 0;
uint8_t rightClearSamples = 0;
unsigned long lastRangeDiagnosticMs = 0;

RangeReading leftRange = {false, -1, -1, RANGE_NOT_PRESENT, 0, 0, 0,
                          {0, 0, 0}, 0, 0};
RangeReading centerRange = {false, -1, -1, RANGE_NOT_PRESENT, 0, 0, 0,
                            {0, 0, 0}, 0, 0};
RangeReading rightRange = {false, -1, -1, RANGE_NOT_PRESENT, 0, 0, 0,
                           {0, 0, 0}, 0, 0};

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
    absoluteOverspeedSinceMs[i] = 0;
    overspeedWarningSinceMs[i] = 0;
    overspeedWarningReported[i] = false;
    targetSettledSinceMs[i] = 0;
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

const char *rangeStatusName(RangeStatus status) {
  switch (status) {
    case RANGE_VALID: return "VALID";
    case RANGE_INVALID: return "RANGE_INVALID";
    case SIGNAL_INVALID: return "SIGNAL_INVALID";
    case RANGE_STALE: return "STALE";
    case RANGE_BUS_ERROR: return "BUS_ERROR";
    case RANGE_NOT_PRESENT: return "NOT_PRESENT";
    default: return "UNKNOWN";
  }
}

RangeStatus effectiveRangeStatus(const RangeReading &reading) {
  if (!reading.present) return RANGE_NOT_PRESENT;
  if (reading.lastValidMs != 0 && millis() - reading.lastValidMs > SENSOR_STALE_MS) {
    return RANGE_STALE;
  }
  return reading.status;
}

long rangeAgeMs(const RangeReading &reading) {
  return reading.lastValidMs == 0 ? -1L : (long)(millis() - reading.lastValidMs);
}

bool rangeFreshAndValid(const RangeReading &reading) {
  return reading.present && reading.status == RANGE_VALID &&
         reading.lastValidMs != 0 && millis() - reading.lastValidMs <= SENSOR_STALE_MS;
}

int medianHistory(const RangeReading &reading) {
  if (reading.historyCount == 0) return -1;
  int sorted[3] = {0, 0, 0};
  for (uint8_t i = 0; i < reading.historyCount; ++i) sorted[i] = reading.history[i];
  for (uint8_t i = 0; i + 1 < reading.historyCount; ++i) {
    for (uint8_t j = i + 1; j < reading.historyCount; ++j) {
      if (sorted[j] < sorted[i]) {
        int temporary = sorted[i];
        sorted[i] = sorted[j];
        sorted[j] = temporary;
      }
    }
  }
  return sorted[reading.historyCount / 2];
}

void recordValidRange(RangeReading &reading, int distanceMm, uint8_t deviceStatus) {
  unsigned long now = millis();
  // Do not blend a newly recovered obstacle with pre-outage history.  The first
  // valid sample after a stale gap must be able to stop the cart immediately.
  if (reading.lastValidMs == 0 || now - reading.lastValidMs > SENSOR_STALE_MS) {
    reading.historyCount = 0;
    reading.historyIndex = 0;
  }
  reading.present = true;
  reading.rawMm = distanceMm;
  reading.status = RANGE_VALID;
  reading.deviceStatus = deviceStatus;
  reading.lastSampleMs = now;
  reading.lastValidMs = now;
  reading.history[reading.historyIndex] = distanceMm;
  reading.historyIndex = (reading.historyIndex + 1) % 3;
  if (reading.historyCount < 3) reading.historyCount++;
  reading.filteredMm = medianHistory(reading);
}

void recordInvalidRange(RangeReading &reading, RangeStatus status, int rawMm,
                        uint8_t deviceStatus) {
  reading.rawMm = rawMm;
  reading.status = status;
  reading.deviceStatus = deviceStatus;
  reading.lastSampleMs = millis();
}

void updateRiskLatch(const RangeReading &reading, int stopMm, int clearMm,
                     bool &latched, uint8_t &clearSamples) {
  if (!rangeFreshAndValid(reading)) {
    clearSamples = 0;
    return;
  }
  if (reading.filteredMm <= stopMm) {
    latched = true;
    clearSamples = 0;
    return;
  }
  if (!latched) return;
  if (reading.filteredMm > clearMm) {
    if (clearSamples < RISK_CLEAR_VALID_SAMPLES) clearSamples++;
    if (clearSamples >= RISK_CLEAR_VALID_SAMPLES) {
      latched = false;
      clearSamples = 0;
    }
  } else {
    clearSamples = 0;
  }
}

bool i2cProbe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

bool i2cWriteRegister(uint8_t address, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool i2cReadRegisters(uint8_t address, uint8_t reg, uint8_t *data, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  size_t received = Wire.requestFrom((int)address, (int)length);
  if (received != length) {
    while (Wire.available() > 0) Wire.read();
    return false;
  }
  for (size_t i = 0; i < length; ++i) data[i] = (uint8_t)Wire.read();
  return true;
}

bool initializeTof(VL53L1X &sensor, int xshutPin, uint8_t address,
                   RangeReading &reading, const char *label) {
  pinMode(xshutPin, INPUT);  // high impedance releases the board's XSHUT pull-up
  delay(10);
  sensor.setTimeout(200);
  if (!sensor.init()) {
    pinMode(xshutPin, OUTPUT);
    digitalWrite(xshutPin, LOW);
    reading.present = false;
    reading.status = RANGE_NOT_PRESENT;
    Serial.print("RANGE_BOOT,sensor="); Serial.print(label);
    Serial.println(",status=NOT_PRESENT");
    return false;
  }
  sensor.setAddress(address);
  if (!sensor.setDistanceMode(VL53L1X::Short) ||
      !sensor.setMeasurementTimingBudget(TOF_TIMING_BUDGET_US)) {
    reading.present = true;
    reading.status = RANGE_BUS_ERROR;
    Serial.print("RANGE_BOOT,sensor="); Serial.print(label);
    Serial.println(",status=CONFIG_ERROR");
    return false;
  }
  sensor.startContinuous(TOF_CONTINUOUS_PERIOD_MS);
  reading.present = true;
  reading.status = RANGE_STALE;
  Serial.print("RANGE_BOOT,sensor="); Serial.print(label);
  Serial.print(",address=0x"); Serial.print(address, HEX);
  Serial.println(",status=READY");
  return true;
}

void initializeRangeSensors() {
  pinMode(LEFT_TOF_XSHUT_PIN, OUTPUT);
  pinMode(RIGHT_TOF_XSHUT_PIN, OUTPUT);
  digitalWrite(LEFT_TOF_XSHUT_PIN, LOW);
  digitalWrite(RIGHT_TOF_XSHUT_PIN, LOW);
  delay(10);

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_FREQUENCY_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);

  centerRange.present = i2cProbe(URM09_ADDRESS);
  if (centerRange.present &&
      i2cWriteRegister(URM09_ADDRESS, URM09_CONFIG_REGISTER, 0x00)) {
    centerRange.status = RANGE_STALE;
    Serial.println("RANGE_BOOT,sensor=CENTER_URM09,address=0x11,status=READY");
  } else {
    centerRange.present = false;
    centerRange.status = RANGE_NOT_PRESENT;
    Serial.println("RANGE_BOOT,sensor=CENTER_URM09,address=0x11,status=NOT_PRESENT");
  }

  initializeTof(leftTof, LEFT_TOF_XSHUT_PIN, LEFT_TOF_ADDRESS,
                leftRange, "LEFT_VL53L1X");
  initializeTof(rightTof, RIGHT_TOF_XSHUT_PIN, RIGHT_TOF_ADDRESS,
                rightRange, "RIGHT_VL53L1X");
}

RangeStatus tofFailureStatus(uint8_t deviceStatus) {
  // Pololu VL53L1X RangeStatus 4/13 are range-bound failures.  The remaining
  // non-zero quality failures are treated as signal-invalid, not as clearance.
  return (deviceStatus == 4 || deviceStatus == 13)
           ? RANGE_INVALID : SIGNAL_INVALID;
}

void serviceTof(VL53L1X &sensor, RangeReading &reading,
                int stopMm, int clearMm, bool &riskLatched,
                uint8_t &clearSamples) {
  if (!reading.present || !sensor.dataReady()) return;
  uint16_t distanceMm = sensor.read(false);
  if (sensor.timeoutOccurred()) {
    recordInvalidRange(reading, RANGE_BUS_ERROR, -1, 255);
  } else {
    uint8_t deviceStatus = sensor.ranging_data.range_status;
    if (deviceStatus != 0) {
      recordInvalidRange(reading, tofFailureStatus(deviceStatus),
                         (int)distanceMm, deviceStatus);
    } else if (distanceMm < TOF_MIN_VALID_MM || distanceMm > TOF_MAX_VALID_MM) {
      recordInvalidRange(reading, RANGE_INVALID, (int)distanceMm, deviceStatus);
    } else {
      recordValidRange(reading, (int)distanceMm, deviceStatus);
    }
  }
  updateRiskLatch(reading, stopMm, clearMm, riskLatched, clearSamples);
}

void serviceUrm09() {
  if (!centerRange.present) return;
  unsigned long now = millis();
  if (!urm09WaitingForResult &&
      (urm09TriggerMs == 0 || now - urm09TriggerMs >= URM09_TRIGGER_PERIOD_MS)) {
    urm09TriggerMs = now;
    if (i2cWriteRegister(URM09_ADDRESS, URM09_COMMAND_REGISTER, 0x01)) {
      urm09WaitingForResult = true;
    } else {
      recordInvalidRange(centerRange, RANGE_BUS_ERROR, -1, 255);
      updateRiskLatch(centerRange, CENTER_STOP_MM, CENTER_CLEAR_MM,
                      centerRiskLatched, centerClearSamples);
    }
  }
  if (!urm09WaitingForResult || now - urm09TriggerMs < URM09_MEASUREMENT_WAIT_MS) {
    return;
  }

  urm09WaitingForResult = false;
  uint8_t bytes[2] = {0, 0};
  if (!i2cReadRegisters(URM09_ADDRESS, URM09_DISTANCE_HIGH_REGISTER, bytes, 2)) {
    recordInvalidRange(centerRange, RANGE_BUS_ERROR, -1, 255);
  } else {
    uint16_t distanceCm = ((uint16_t)bytes[0] << 8) | bytes[1];
    if (distanceCm == 0xFFFF) {
      recordInvalidRange(centerRange, SIGNAL_INVALID, -1, 255);
    } else {
      int distanceMm = (int)distanceCm * 10;
      if (distanceMm < URM09_MIN_VALID_MM || distanceMm > URM09_MAX_VALID_MM) {
        recordInvalidRange(centerRange, RANGE_INVALID, distanceMm, 0);
      } else {
        recordValidRange(centerRange, distanceMm, 0);
      }
    }
  }
  updateRiskLatch(centerRange, CENTER_STOP_MM, CENTER_CLEAR_MM,
                  centerRiskLatched, centerClearSamples);
}

void serviceRangeSensors() {
  serviceTof(leftTof, leftRange, CORNER_STOP_MM, CORNER_CLEAR_MM,
             leftRiskLatched, leftClearSamples);
  serviceTof(rightTof, rightRange, CORNER_STOP_MM, CORNER_CLEAR_MM,
             rightRiskLatched, rightClearSamples);
  serviceUrm09();
}

const char *motionRangeBlockReason(int left, int right) {
  if (!RANGE_MOTION_GATING_ENABLED) return NULL;

  bool forward = left + right > 0;
  bool turningLeft = right > left;
  bool turningRight = left > right;

  if (forward) {
    if (REQUIRE_RANGE_SENSORS_FOR_MOTION && !rangeFreshAndValid(centerRange)) {
      return "sensor_center_unavailable";
    }
    if (centerRiskLatched) return "sensor_center_near";
  }
  if (turningLeft) {
    if (REQUIRE_RANGE_SENSORS_FOR_MOTION && !rangeFreshAndValid(leftRange)) {
      return "sensor_left_unavailable";
    }
    if (leftRiskLatched) return "sensor_left_near";
  }
  if (turningRight) {
    if (REQUIRE_RANGE_SENSORS_FOR_MOTION && !rangeFreshAndValid(rightRange)) {
      return "sensor_right_unavailable";
    }
    if (rightRiskLatched) return "sensor_right_near";
  }
  return NULL;
}

int minimumFreshRangeMm() {
  int minimumMm = -1;
  const RangeReading *readings[3] = {&leftRange, &centerRange, &rightRange};
  for (int i = 0; i < 3; ++i) {
    if (!rangeFreshAndValid(*readings[i])) continue;
    if (minimumMm < 0 || readings[i]->filteredMm < minimumMm) {
      minimumMm = readings[i]->filteredMm;
    }
  }
  return minimumMm;
}

void serviceLegacyRangeTelemetry() {
  unsigned long now = millis();
  int minimumMm = minimumFreshRangeMm();
  if (minimumMm < 0) return;  // never encode invalid/missing as a clear distance
  for (int sourceValue = SOURCE_BLE; sourceValue <= SOURCE_USB; ++sourceValue) {
    ControlSource source = (ControlSource)sourceValue;
    if (source == SOURCE_BLE && !bleClientConnected) continue;
    unsigned long interval = sonarReportIntervalMs[sourceValue];
    if (interval == 0 || now - lastSonarReportMs[sourceValue] < interval) continue;
    lastSonarReportMs[sourceValue] = now;
    sendLine(source, "s" + String((minimumMm + 5) / 10) + "\n");
  }
}

void serviceRangeDiagnostics() {
  if (!usbDiagnosticsEnabled) return;
  unsigned long now = millis();
  if (lastRangeDiagnosticMs != 0 &&
      now - lastRangeDiagnosticMs < DIAGNOSTIC_SAMPLE_MS) return;
  lastRangeDiagnosticMs = now;
  Serial.print("RANGE,ms="); Serial.print(now);
  Serial.print(",gating="); Serial.print(RANGE_MOTION_GATING_ENABLED ? 1 : 0);
  Serial.print(",left_mm="); Serial.print(leftRange.filteredMm);
  Serial.print(",left_status="); Serial.print(rangeStatusName(effectiveRangeStatus(leftRange)));
  Serial.print(",left_age_ms="); Serial.print(rangeAgeMs(leftRange));
  Serial.print(",left_device_status="); Serial.print(leftRange.deviceStatus);
  Serial.print(",center_mm="); Serial.print(centerRange.filteredMm);
  Serial.print(",center_status="); Serial.print(rangeStatusName(effectiveRangeStatus(centerRange)));
  Serial.print(",center_age_ms="); Serial.print(rangeAgeMs(centerRange));
  Serial.print(",right_mm="); Serial.print(rightRange.filteredMm);
  Serial.print(",right_status="); Serial.print(rangeStatusName(effectiveRangeStatus(rightRange)));
  Serial.print(",right_age_ms="); Serial.print(rangeAgeMs(rightRange));
  Serial.print(",right_device_status="); Serial.print(rightRange.deviceStatus);
  Serial.print(",risk=");
  Serial.print(leftRiskLatched ? 'L' : '-');
  Serial.print(centerRiskLatched ? 'C' : '-');
  Serial.println(rightRiskLatched ? 'R' : '-');
}

void serviceRangeMotionSafety() {
  if (!RANGE_MOTION_GATING_ENABLED) return;
  if (systemState != MANUAL_ACTIVE) return;
  const char *reason = motionRangeBlockReason(logicalLeft, logicalRight);
  if (reason != NULL) beginBrake(reason);
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
  brakePidWarningReported = false;
  lastControlUpdateMs = brakeStartedMs;
  setState(BRAKING);
  diagnostic("brake_start", "reason=" + reason + ",mode=spd_zero_pid_hold");
}

void recordFaultContext(const String &reason, bool recoverable) {
  unsigned long now = millis();
  lastFaultReason = reason;
  lastFaultAtMs = now;
  lastFaultRecoverable = recoverable;
  lastFaultMspdAgeMs = lastMspdMs == 0 ? -1L : (long)(now - lastMspdMs);
  for (int i = 0; i < 4; ++i) {
    lastFaultTargetMmps[i] = targetWheelMmps[i];
    lastFaultCurrentMmps[i] = currentWheelMmps[i];
    lastFaultMspd[i] = latestMspd[i];
  }
}

void enterLatchedFault(SystemState faultState, const String &reason) {
  recordFaultContext(reason, false);
  clearMotionVectors();
  releaseOwner();
  sendZeroVelocity();
  delay(20);
  disablePwmOutput();
  setState(faultState);
  diagnostic("latched_stop", "reason=" + reason + ",mode=pwm_zero");
}

void enterDriverFault(const String &reason, bool recoverable) {
  recordFaultContext(reason, recoverable);
  clearMotionVectors();
  releaseOwner();
  sendZeroVelocity();
  delay(20);
  disablePwmOutput();
  driverRecoveryZeroSinceMs = 0;
  lastDriverRecoveryZeroMs = 0;
  for (int i = 0; i < 3; ++i) lastLatchedErrorReportMs[i] = 0;
  setState(DRIVER_ERROR);
  diagnostic("driver_fault",
             "reason=" + reason +
             ",recoverable=" + String(recoverable ? 1 : 0) +
             ",mspd_age_ms=" + String(lastFaultMspdAgeMs));
}

void reportLatchedStop(ControlSource source) {
  int index = (int)source;
  unsigned long now = millis();
  if (index < SOURCE_BLE || index > SOURCE_USB) return;
  if (lastLatchedErrorReportMs[index] != 0 &&
      now - lastLatchedErrorReportMs[index] < LATCHED_ERROR_REPORT_INTERVAL_MS) {
    return;
  }
  lastLatchedErrorReportMs[index] = now;
  reportError(source, "latched_stop");
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
  int inputMagnitude = abs(logical);
  int scaled = 0;
  if (inputMagnitude <= PROTOCOL_LEGACY_FULL_SPEED_INPUT) {
    long numerator = (long)inputMagnitude * LEGACY_FULL_SPEED_MMPS;
    scaled = (int)((numerator + PROTOCOL_LEGACY_FULL_SPEED_INPUT / 2) /
                   PROTOCOL_LEGACY_FULL_SPEED_INPUT);
  } else {
    const int inputSpan = PROTOCOL_FULL_SPEED_INPUT -
                          PROTOCOL_LEGACY_FULL_SPEED_INPUT;
    const int speedSpan = MAX_WHEEL_SPEED_MMPS - LEGACY_FULL_SPEED_MMPS;
    long numerator = (long)(inputMagnitude -
                            PROTOCOL_LEGACY_FULL_SPEED_INPUT) * speedSpan;
    scaled = LEGACY_FULL_SPEED_MMPS +
             (int)((numerator + inputSpan / 2) / inputSpan);
  }
  scaled = constrain(scaled, MIN_MOVING_WHEEL_MMPS, MAX_WHEEL_SPEED_MMPS);
  return logical > 0 ? scaled : -scaled;
}

bool isPurePivot(int left, int right) {
  return left != 0 && right != 0 && left == -right;
}

bool isCounterRotation(int left, int right) {
  return left != 0 && right != 0 && ((left > 0) != (right > 0));
}

void calculateWheelTargets(int left, int right, int result[4]) {
  int leftMmps = scaleLogicalSide(left);
  int rightMmps = scaleLogicalSide(right);

  // Stage I-M showed that 80 mm/s is the reliable pivot floor.  Raising the
  // global speed scale already maps logical +/-5 to about 86 mm/s, so keep the
  // floor unchanged instead of forcing low-speed search turns to 120 mm/s.
  if (isPurePivot(left, right)) {
    leftMmps = leftMmps > 0 ? max(leftMmps, MIN_PIVOT_WHEEL_MMPS)
                            : min(leftMmps, -MIN_PIVOT_WHEEL_MMPS);
    rightMmps = rightMmps > 0 ? max(rightMmps, MIN_PIVOT_WHEEL_MMPS)
                              : min(rightMmps, -MIN_PIVOT_WHEEL_MMPS);
  }

  // The 600 mm/s extension is for forward/reverse following and same-direction
  // differential arcs.  Any command that counter-rotates the two sides remains
  // bounded to the previously exposed 240 mm/s rotational envelope.
  if (isCounterRotation(left, right)) {
    leftMmps = constrain(leftMmps, -MAX_COUNTER_ROTATION_MMPS,
                         MAX_COUNTER_ROTATION_MMPS);
    rightMmps = constrain(rightMmps, -MAX_COUNTER_ROTATION_MMPS,
                          MAX_COUNTER_ROTATION_MMPS);
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
      absoluteOverspeedSinceMs[i] = 0;
      overspeedWarningSinceMs[i] = 0;
      overspeedWarningReported[i] = false;
      continue;
    }

    float measured = latestMspd[i] * MSPD_TO_COMMAND_SIGN;
    bool signMismatch = absFloat(measured) > ZERO_SPEED_MMPS &&
                        ((measured > 0) != (targetWheelMmps[i] > 0));
    if (signMismatch) {
      if (feedbackMismatchSinceMs[i] == 0) feedbackMismatchSinceMs[i] = now;
      if (now - feedbackMismatchSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterDriverFault("feedback_sign_mismatch_m" + String(i + 1), false);
        return false;
      }
    } else {
      feedbackMismatchSinceMs[i] = 0;
    }

    float speedReference = max(absFloat((float)currentWheelMmps[i]),
                               absFloat((float)targetWheelMmps[i]));
    float warningLimit = min(
      OVERSPEED_ABSOLUTE_MMPS,
      max(OVERSPEED_MIN_MMPS,
          speedReference * OVERSPEED_WARNING_RATIO));
    if (absFloat(measured) > warningLimit) {
      if (overspeedWarningSinceMs[i] == 0) overspeedWarningSinceMs[i] = now;
      if (!overspeedWarningReported[i] &&
          now - overspeedWarningSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        overspeedWarningReported[i] = true;
        diagnostic("overspeed_warning",
                   "wheel=" + String(i + 1) +
                   ",target=" + String(targetWheelMmps[i]) +
                   ",current=" + String(currentWheelMmps[i]) +
                   ",mspd=" + String(measured, 2) +
                   ",limit=" + String(warningLimit, 2) +
                   ",settled=" + String(targetSettledSinceMs[i] != 0 ? 1 : 0));
      }
    } else {
      overspeedWarningSinceMs[i] = 0;
      overspeedWarningReported[i] = false;
    }

    // The absolute cap is always armed, including while a wheel is ramping or
    // the AT8236 loop is settling after an inner-wheel target reduction.
    if (absFloat(measured) > OVERSPEED_ABSOLUTE_MMPS) {
      if (absoluteOverspeedSinceMs[i] == 0) absoluteOverspeedSinceMs[i] = now;
      if (now - absoluteOverspeedSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterDriverFault("overspeed_absolute_m" + String(i + 1), false);
        return false;
      }
    } else {
      absoluteOverspeedSinceMs[i] = 0;
    }

    bool dynamicCheckSettled =
      currentWheelMmps[i] == targetWheelMmps[i] &&
      targetSettledSinceMs[i] != 0 &&
      now - targetSettledSinceMs[i] >= OVERSPEED_TARGET_SETTLE_MS;
    float limit = min(
      OVERSPEED_ABSOLUTE_MMPS,
      max(OVERSPEED_MIN_MMPS,
          speedReference * OVERSPEED_RATIO));
    if (dynamicCheckSettled && absFloat(measured) > limit) {
      if (overspeedSinceMs[i] == 0) overspeedSinceMs[i] = now;
      if (now - overspeedSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterDriverFault("overspeed_dynamic_m" + String(i + 1), false);
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
  Serial.print(",speed_legacy_input=");
  Serial.print(PROTOCOL_LEGACY_FULL_SPEED_INPUT);
  Serial.print(",speed_legacy_mmps="); Serial.print(LEGACY_FULL_SPEED_MMPS);
  Serial.print(",speed_full_input="); Serial.print(PROTOCOL_FULL_SPEED_INPUT);
  Serial.print(",speed_cap_mmps="); Serial.print(MAX_WHEEL_SPEED_MMPS);
  Serial.print(",overspeed_warning_ratio=");
  Serial.print(OVERSPEED_WARNING_RATIO, 2);
  Serial.print(",overspeed_hard_ratio="); Serial.print(OVERSPEED_RATIO, 2);
  Serial.print(",overspeed_absolute_mmps=");
  Serial.print(OVERSPEED_ABSOLUTE_MMPS, 2);
  Serial.print(",overspeed_settle_ms=");
  Serial.print(OVERSPEED_TARGET_SETTLE_MS);
  Serial.print(",range_motion_gating=");
  Serial.print(RANGE_MOTION_GATING_ENABLED ? 1 : 0);
  Serial.print(",last_fault_reason="); Serial.print(lastFaultReason);
  Serial.print(",last_fault_at_ms=");
  Serial.print(lastFaultAtMs ? (long)lastFaultAtMs : -1L);
  Serial.print(",last_fault_recoverable=");
  Serial.print(lastFaultRecoverable ? 1 : 0);
  Serial.print(",driver_recovery_active=");
  Serial.print(systemState == DRIVER_ERROR && lastFaultRecoverable ? 1 : 0);
  Serial.print(",fault_mspd_age_ms="); Serial.print(lastFaultMspdAgeMs);
  Serial.print(",fault_target=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(lastFaultTargetMmps[i]);
    Serial.print(i == 3 ? ',' : ':');
  }
  Serial.print("fault_current=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(lastFaultCurrentMmps[i]);
    Serial.print(i == 3 ? ',' : ':');
  }
  Serial.print("fault_mspd=");
  for (int i = 0; i < 4; ++i) {
    Serial.print(lastFaultMspd[i], 2);
    Serial.print(i == 3 ? ',' : ':');
  }
  Serial.print("recovery_zero_age_ms=");
  Serial.print(driverRecoveryZeroSinceMs
                 ? (long)(millis() - driverRecoveryZeroSinceMs) : -1L);
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
  Serial.print(lastMspdMs ? (long)(millis() - lastMspdMs) : -1);
  Serial.print(",left_mm="); Serial.print(leftRange.filteredMm);
  Serial.print(",left_status="); Serial.print(rangeStatusName(effectiveRangeStatus(leftRange)));
  Serial.print(",left_age_ms="); Serial.print(rangeAgeMs(leftRange));
  Serial.print(",center_mm="); Serial.print(centerRange.filteredMm);
  Serial.print(",center_status="); Serial.print(rangeStatusName(effectiveRangeStatus(centerRange)));
  Serial.print(",center_age_ms="); Serial.print(rangeAgeMs(centerRange));
  Serial.print(",right_mm="); Serial.print(rightRange.filteredMm);
  Serial.print(",right_status="); Serial.print(rangeStatusName(effectiveRangeStatus(rightRange)));
  Serial.print(",right_age_ms="); Serial.print(rangeAgeMs(rightRange));
  Serial.print(",range_risk=");
  Serial.print(leftRiskLatched ? 'L' : '-');
  Serial.print(centerRiskLatched ? 'C' : '-');
  Serial.println(rightRiskLatched ? 'R' : '-');
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
    } else if (systemState == DRIVER_ERROR && lastFaultRecoverable) {
      // A recoverable driver hold uses fresh zero-speed frames to verify that
      // the velocity channel and feedback have both become healthy again.
      sendZeroVelocity();
    } else if (isLatchedState()) {
      // Hard faults and emergency stop must remain in disabled-PWM mode.
      disablePwmOutput();
    }
    return;
  }

  if (isLatchedState()) {
    reportLatchedStop(source);
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

  const char *rangeBlockReason = motionRangeBlockReason(left, right);
  if (rangeBlockReason != NULL) {
    reportError(source, rangeBlockReason);
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
  for (int i = 0; i < 4; ++i) {
    if (targetWheelMmps[i] != requested[i]) {
      targetWheelMmps[i] = requested[i];
      targetSettledSinceMs[i] = 0;
      overspeedSinceMs[i] = 0;
    }
  }
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

void handleSonarFrequency(ControlSource source, const String &line) {
  long requested = 0;
  if (!parseLongStrict(line.substring(1), requested) ||
      (requested != 0 &&
       (requested < (long)MIN_SONAR_REPORT_MS ||
        requested > (long)MAX_SONAR_REPORT_MS))) {
    reportError(source, "bad_sonar_interval");
    return;
  }
  sonarReportIntervalMs[(int)source] = (unsigned long)requested;
  lastSonarReportMs[(int)source] = 0;
}

void handleFeatureQuery(ControlSource source) {
  sendLine(source, "fCART_AT8236:s:\n");
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

  // Queries, heartbeat/telemetry setup and c0 remain safe during a stop latch;
  // non-zero motion is still rejected by handleMotionCommand().
  if (line == "f") {
    handleFeatureQuery(source);
  } else if (line == "!Q") {
    if (source == SOURCE_USB) printStatus();
    else reportError(source, "usb_only");
  } else if (line.startsWith("!D,")) {
    handleDiagnostics(source, line);
  } else if (line.startsWith("!S")) {
    handleEmergency(source, line);
  } else if (line.charAt(0) == 'c') {
    handleMotionCommand(source, line);
  } else if (line.charAt(0) == 'h') {
    handleHeartbeat(source, line);
  } else if (line.charAt(0) == 's') {
    handleSonarFrequency(source, line);
  } else if (isLatchedState()) {
    reportLatchedStop(source);
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
    sonarReportIntervalMs[SOURCE_BLE] = 0;
    lastSonarReportMs[SOURCE_BLE] = 0;
    diagnostic("ble_disconnect", "epoch=" + String((unsigned long)bleConnectionEpoch));
    if (owner == SOURCE_BLE && !isLatchedState()) beginBrake("ble_disconnect");
    resetLineBuffer(bleLineBuffer);
    if (bleRxQueue != NULL) xQueueReset(bleRxQueue);
  }

  if (bleConnectPending) {
    bleConnectPending = false;
    commandTimeoutMs = DEFAULT_LINK_TIMEOUT_MS;
    sonarReportIntervalMs[SOURCE_BLE] = 0;
    lastSonarReportMs[SOURCE_BLE] = 0;
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
    enterDriverFault("driver_boot_timeout", false);
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
    beginBrake("telemetry_timeout_while_moving");
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
    int previous = currentWheelMmps[i];
    currentWheelMmps[i] = moveToward(currentWheelMmps[i],
                                     targetWheelMmps[i],
                                     CONTROL_RAMP_STEP_MMPS);
    if (currentWheelMmps[i] == targetWheelMmps[i]) {
      if (previous != targetWheelMmps[i] || targetSettledSinceMs[i] == 0) {
        targetSettledSinceMs[i] = now;
      }
    } else {
      targetSettledSinceMs[i] = 0;
    }
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
    zeroSinceMs = 0;
    if (now - brakeStartedMs >= BRAKE_TELEMETRY_GRACE_MS) {
      enterDriverFault("mspd_lost_while_braking", true);
    }
    return;
  }

  if (now - brakeStartedMs >= BRAKE_PID_GRACE_MS) {
    for (int i = 0; i < 4; ++i) {
      if (absFloat(latestMspd[i]) > BRAKE_FALLBACK_SPEED_MMPS) {
        if (!brakePidWarningReported) {
          brakePidWarningReported = true;
          diagnostic("brake_slow",
                     "wheel=" + String(i + 1) +
                     ",mspd=" + String(latestMspd[i], 2));
        }
        break;
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
    enterDriverFault("brake_timeout", true);
  }
}

void serviceDriverRecovery() {
  if (systemState != DRIVER_ERROR || !lastFaultRecoverable) return;
  unsigned long now = millis();

  // A recoverable driver fault is still a stop state. Keep refreshing zero and
  // never replay the command that was active when the fault occurred.
  if (lastDriverRecoveryZeroMs == 0 ||
      now - lastDriverRecoveryZeroMs >= IDLE_ZERO_REFRESH_MS) {
    lastDriverRecoveryZeroMs = now;
    sendZeroVelocity();
  }

  if (!mspdFresh() || !allWheelsNearZero()) {
    driverRecoveryZeroSinceMs = 0;
    return;
  }

  if (driverRecoveryZeroSinceMs == 0) {
    driverRecoveryZeroSinceMs = now;
    diagnostic("driver_recovery_zero",
               "reason=" + lastFaultReason + ",started=1");
    return;
  }
  if (now - driverRecoveryZeroSinceMs < DRIVER_RECOVERY_ZERO_HOLD_MS) return;

  clearMotionVectors();
  releaseOwner();
  sendZeroVelocity();
  driverRecoveryZeroSinceMs = 0;
  lastDriverRecoveryZeroMs = 0;
  for (int i = 0; i < 3; ++i) lastLatchedErrorReportMs[i] = 0;
  setState(READY_STOP);
  diagnostic("driver_recovered",
             "reason=" + lastFaultReason +
             ",zero_hold_ms=" + String(DRIVER_RECOVERY_ZERO_HOLD_MS));
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

  initializeRangeSensors();
  configureAT8236();
  setupBle();
  Serial.println("ESP32 AT8236 velocity BLE firmware booting");
  Serial.println("RANGE_MODE,mode=LOG_ONLY,gating=0");
  Serial.println("FAULT_RECOVERY,version=3,transient_auto_recover=1,overspeed_hard_ratio=4.00,overspeed_absolute_mmps=750");
}

void loop() {
  // All state changes and all AT8236 writes happen in this single context.
  serviceMotorSerial();
  serviceRangeSensors();
  serviceBleEvents();
  pollUsb();
  serviceRangeMotionSafety();
  serviceReadyNotifications();
  serviceTimeouts();
  serviceActiveMotion();
  serviceBrake();
  serviceDriverRecovery();
  serviceIdleHold();
  serviceLegacyRangeTelemetry();
  serviceRangeDiagnostics();
}
