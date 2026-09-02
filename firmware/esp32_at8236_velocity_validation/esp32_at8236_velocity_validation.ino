/*
  ESP32 + AT8236 four-wheel velocity validation firmware.

  Scope:
    - USB-only, supervised raised-wheel and restricted landed validation
      before Android/BLE integration.
    - AT8236 $spd remains the inner velocity loop.
    - ESP32 supplies chassis mixing, per-wheel/direction feed-forward,
      optional slow outer correction, telemetry checks, and safe stopping.

  Safety:
    - Motion is rejected until an explicit RAISED/LANDED/TURN/STRAFE arm is accepted.
    - LANDED is straight-only, <=100 mm/s, <=5000 ms, and single-shot.
    - TURN is pivot-only, 60..100 mm/s, 1000..2000 ms, and single-shot.
    - STRAFE is lateral-only, 80..100 mm/s, 1000..2000 ms, and single-shot.
    - ARC is same-direction differential motion, tightly bounded and single-shot.
    - Normal stop keeps $spd:0 active so the AT8236 PID brakes/holds.
    - $pwm:0 is used only for explicit release or a telemetry/braking fault.
    - Optional outer correction is disabled after every boot and disarm.
*/

#include <Arduino.h>
#include <math.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;
static const unsigned long USB_BAUD = 115200;
static const unsigned long MOTOR_BAUD = 115200;

// Confirmed project parameters: 12 V 520 encoder motor, ratio 30, 11 lines,
// 80 mm mecanum wheel. The 2026-08-31 M1 log proved that mtype=1 makes the
// present motor/encoder wiring a positive-feedback loop: $spd:+50 produced
// MSPD:-1447 and $spd:0 could not brake it. The vendor manual selects type 1
// or 2 according to the actual encoder A/B relationship, so keep the wiring
// unchanged and use type 2 for this cart.
static const int AT8236_MOTOR_TYPE = 2;
static const int AT8236_GEAR_RATIO = 30;
static const int AT8236_ENCODER_LINES = 11;
static const float AT8236_WHEEL_DIAMETER_MM = 80.0f;
static const int AT8236_DEADZONE = 1600;

// The AT8236 documents $spd as a signed velocity target in [-1000, 1000].
// This validation firmware deliberately stays far below the board limit.
static const int MAX_VALIDATION_SPEED_MMPS = 250;
static const int MAX_LANDED_SPEED_MMPS = 100;
// Stage I showed that 40 mm/s sits inside the ground-turning stiction region,
// while 60 mm/s starts both turn directions reliably. Keep ineffective turn
// requests out of the landed test path, then characterize up to the already
// straight-line-validated 100 mm/s ceiling.
static const int MIN_LANDED_TURN_SPEED_MMPS = 60;
static const int MAX_LANDED_TURN_SPEED_MMPS = 100;
static const int MIN_TEST_DURATION_MS = 800;
static const int MAX_TEST_DURATION_MS = 5000;
// The first landed tests passed at 40 and 100 mm/s. Keep the verified speed
// ceiling, but allow staged straight-line tests up to 0.5 m.
static const int MAX_LANDED_DURATION_MS = 5000;
// Turning adds tyre scrub and can reveal mapping/load problems that straight
// driving does not. Start with short, symmetric counter-rotation only.
static const int MIN_LANDED_TURN_DURATION_MS = 1000;
static const int MAX_LANDED_TURN_DURATION_MS = 2000;
// Lateral motion is validated separately because mecanum roller friction and
// wheel mounting can create translation errors that encoder symmetry alone
// cannot reveal. Keep it inside the same speed envelope as the passed turn test.
static const int MIN_LANDED_STRAFE_SPEED_MMPS = 80;
static const int MAX_LANDED_STRAFE_SPEED_MMPS = 100;
static const int MIN_LANDED_STRAFE_DURATION_MS = 1000;
static const int MAX_LANDED_STRAFE_DURATION_MS = 2000;
// ARC is the first combined-motion test used by the actual following path.
// Stage L proved the commanded 100/80 and 100/60 ratios, but the short tests
// produced less than 5 degrees of visible yaw. Keep the passed 100 mm/s outer
// speed, then permit longer tests and a staged 100/40 sharper curve.
static const int REQUIRED_LANDED_ARC_OUTER_SPEED_MMPS = 100;
static const int MIN_LANDED_ARC_SIDE_SPEED_MMPS = 40;
static const int MAX_LANDED_ARC_SIDE_SPEED_MMPS = 100;
static const int MIN_LANDED_ARC_DELTA_MMPS = 20;
static const int MAX_LANDED_ARC_DELTA_MMPS = 60;
static const int MIN_LANDED_ARC_DURATION_MS = 1000;
static const int MAX_LANDED_ARC_DURATION_MS = 4000;
static const unsigned long RAISED_ARM_WINDOW_MS = 180000;
static const unsigned long LANDED_ARM_WINDOW_MS = 60000;
static const unsigned long TELEMETRY_TIMEOUT_MS = 500;
static const unsigned long CONTROL_PERIOD_MS = 50;
static const unsigned long OUTER_UPDATE_MS = 200;
static const unsigned long OUTER_DELAY_MS = 600;
static const unsigned long BRAKE_PID_GRACE_MS = 600;
static const unsigned long BRAKE_TIMEOUT_MS = 2000;
static const unsigned long ZERO_HOLD_MS = 400;
// AT8236 MSPD is quantized at roughly 19 mm/s in the captured logs. A 30 mm/s
// near-zero threshold accepts idle +/-19 mm/s noise but no longer treats a
// still-moving 38..57 mm/s wheel as settled.
static const float ZERO_SPEED_MMPS = 30.0f;
static const float BRAKE_FALLBACK_SPEED_MMPS = 120.0f;
static const float OVERSPEED_MIN_MMPS = 300.0f;
static const float OVERSPEED_RATIO = 3.0f;
static const unsigned long FEEDBACK_FAULT_CONFIRM_MS = 120;
static const int OUTER_MAX_CORRECTION_MMPS = 30;
static const int OUTER_MAX_STEP_MMPS = 2;
static const float OUTER_KI = 0.02f;
static const unsigned long TELEMETRY_PRINT_MS = 200;
static const unsigned long COOLDOWN_MS = 1000;

// With the corrected motor type, AT8236 command and MSPD feedback must have
// the same sign. Motion safety verifies this continuously before the optional
// outer loop is allowed to do any correction.
static const int MSPD_TO_COMMAND_SIGN = 1;

// Physical wheel placement used by the project:
// M3 = left front, M4 = right front, M1 = left rear, M2 = right rear.
// A positive chassis-side velocity maps to these AT8236 command signs.
static const int FORWARD_SIGN[4] = {1, -1, -1, 1};

struct WheelCalibration {
  int forwardGainPermille;
  int reverseGainPermille;
  int forwardBiasMmps;
  int reverseBiasMmps;
};

// Start neutral. Change only from repeatable raised-wheel and landed results,
// or use !G at runtime for a non-persistent test.
WheelCalibration wheelCalibration[4] = {
  {1000, 1000, 0, 0},
  {1000, 1000, 0, 0},
  {1000, 1000, 0, 0},
  {1000, 1000, 0, 0}
};

enum ControllerState {
  BOOT_HOLD = 0,
  SAFE_HOLD,
  ARMED_IDLE,
  RUNNING_RAW,
  RUNNING_DRIVE,
  BRAKING,
  RELEASED,
  FAULT_DISABLED
};

enum ArmMode {
  ARM_NONE = 0,
  ARM_RAISED,
  ARM_LANDED,
  ARM_TURN,
  ARM_STRAFE,
  ARM_ARC
};

ControllerState controllerState = BOOT_HOLD;
ArmMode armMode = ARM_NONE;

static const size_t USB_LINE_MAX = 160;
static const size_t MOTOR_FRAME_MAX = 160;
char usbLine[USB_LINE_MAX + 1] = {0};
size_t usbLineLength = 0;
bool usbLineOverflow = false;
String motorFrame;

bool telemetrySeen = false;
unsigned long lastTelemetryMs = 0;
unsigned long lastMspdMs = 0;
unsigned long lastMAllMs = 0;
float latestMspd[4] = {0, 0, 0, 0};
long latestMAll[4] = {0, 0, 0, 0};
long testStartMAll[4] = {0, 0, 0, 0};

bool armed = false;
unsigned long armedUntilMs = 0;
unsigned long motionStartedMs = 0;
unsigned long activeUntilMs = 0;
unsigned long cooldownUntilMs = 0;
unsigned long brakeStartedMs = 0;
unsigned long zeroSinceMs = 0;
unsigned long lastSequence = 0;
unsigned long lastControlMs = 0;
unsigned long lastOuterMs = 0;
unsigned long lastTelemetryPrintMs = 0;
unsigned long feedbackMismatchSinceMs[4] = {0, 0, 0, 0};
unsigned long overspeedSinceMs[4] = {0, 0, 0, 0};
bool disarmAfterBrake = false;
bool outerCorrectionEnabled = false;
bool driverConfigSent = false;

int desiredWheelMmps[4] = {0, 0, 0, 0};
int feedForwardWheelMmps[4] = {0, 0, 0, 0};
int outerCorrectionMmps[4] = {0, 0, 0, 0};
int driverCommandMmps[4] = {0, 0, 0, 0};

const char *stateName(ControllerState state) {
  switch (state) {
    case BOOT_HOLD: return "BOOT_HOLD";
    case SAFE_HOLD: return "SAFE_HOLD";
    case ARMED_IDLE: return "ARMED_IDLE";
    case RUNNING_RAW: return "RUNNING_RAW";
    case RUNNING_DRIVE: return "RUNNING_DRIVE";
    case BRAKING: return "BRAKING";
    case RELEASED: return "RELEASED";
    case FAULT_DISABLED: return "FAULT_DISABLED";
    default: return "UNKNOWN";
  }
}

const char *armModeName(ArmMode mode) {
  switch (mode) {
    case ARM_RAISED: return "RAISED";
    case ARM_LANDED: return "LANDED";
    case ARM_TURN: return "TURN";
    case ARM_STRAFE: return "STRAFE";
    case ARM_ARC: return "ARC";
    case ARM_NONE:
    default: return "NONE";
  }
}

bool isRestrictedGroundMode(ArmMode mode) {
  return mode == ARM_LANDED || mode == ARM_TURN ||
         mode == ARM_STRAFE || mode == ARM_ARC;
}

void sendMotorCommand(const String &command) {
  MotorSerial.print(command);
}

void sendSpeed(int m1, int m2, int m3, int m4) {
  char command[64];
  snprintf(command, sizeof(command), "$spd:%d,%d,%d,%d#",
           constrain(m1, -1000, 1000), constrain(m2, -1000, 1000),
           constrain(m3, -1000, 1000), constrain(m4, -1000, 1000));
  MotorSerial.print(command);
}

void sendDriverVelocityCommand() {
  sendSpeed(driverCommandMmps[0], driverCommandMmps[1],
            driverCommandMmps[2], driverCommandMmps[3]);
}

void holdWithVelocityPid() {
  for (int i = 0; i < 4; ++i) {
    desiredWheelMmps[i] = 0;
    feedForwardWheelMmps[i] = 0;
    outerCorrectionMmps[i] = 0;
    driverCommandMmps[i] = 0;
    feedbackMismatchSinceMs[i] = 0;
    overspeedSinceMs[i] = 0;
  }
  sendSpeed(0, 0, 0, 0);
}

void disablePwmOutput() {
  sendMotorCommand("$pwm:0,0,0,0#");
  for (int i = 0; i < 4; ++i) {
    desiredWheelMmps[i] = 0;
    feedForwardWheelMmps[i] = 0;
    outerCorrectionMmps[i] = 0;
    driverCommandMmps[i] = 0;
  }
}

float absFloat(float value) {
  return value < 0.0f ? -value : value;
}

bool mspdFresh() {
  return lastMspdMs != 0 && millis() - lastMspdMs <= TELEMETRY_TIMEOUT_MS;
}

bool telemetryFresh() {
  return telemetrySeen && millis() - lastTelemetryMs <= TELEMETRY_TIMEOUT_MS;
}

bool allWheelsNearZero() {
  if (!mspdFresh()) return false;
  for (int i = 0; i < 4; ++i) {
    if (absFloat(latestMspd[i]) > ZERO_SPEED_MMPS) return false;
  }
  return true;
}

void printEvent(const String &event, const String &details = "") {
  Serial.print("VEL,ms=");
  Serial.print(millis());
  Serial.print(",event=");
  Serial.print(event);
  if (details.length() > 0) {
    Serial.print(",");
    Serial.print(details);
  }
  Serial.println();
}

void printWheelVector(const int values[4]) {
  Serial.print(values[0]); Serial.print(',');
  Serial.print(values[1]); Serial.print(',');
  Serial.print(values[2]); Serial.print(',');
  Serial.print(values[3]);
}

void printFloatVector(const float values[4]) {
  Serial.print(values[0], 2); Serial.print(',');
  Serial.print(values[1], 2); Serial.print(',');
  Serial.print(values[2], 2); Serial.print(',');
  Serial.print(values[3], 2);
}

void printStatus() {
  Serial.print("!Q,state=");
  Serial.print(stateName(controllerState));
  Serial.print(",armed=");
  Serial.print(armed ? 1 : 0);
  Serial.print(",arm_mode=");
  Serial.print(armModeName(armMode));
  Serial.print(",arm_remaining_ms=");
  Serial.print(armed && millis() < armedUntilMs ? (long)(armedUntilMs - millis()) : -1);
  Serial.print(",telemetry_age_ms=");
  Serial.print(telemetrySeen ? (long)(millis() - lastTelemetryMs) : -1);
  Serial.print(",mspd_age_ms=");
  Serial.print(lastMspdMs ? (long)(millis() - lastMspdMs) : -1);
  Serial.print(",outer=");
  Serial.print(outerCorrectionEnabled ? 1 : 0);
  Serial.print(",desired=");
  printWheelVector(desiredWheelMmps);
  Serial.print(",driver=");
  printWheelVector(driverCommandMmps);
  Serial.print(",mspd=");
  printFloatVector(latestMspd);
  Serial.print(",last_seq=");
  Serial.println(lastSequence);
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

bool parseFourFloats(const String &payload, float values[4]) {
  String parts[4];
  if (splitCsv(payload, parts, 4) != 4) return false;
  for (int i = 0; i < 4; ++i) {
    parts[i].trim();
    if (parts[i].length() == 0) return false;
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

void serviceMotorSerial() {
  while (MotorSerial.available() > 0) {
    char c = (char)MotorSerial.read();
    if (c == '$') {
      motorFrame = "$";
      continue;
    }
    if (motorFrame.length() == 0) continue;
    motorFrame += c;
    if (motorFrame.length() > MOTOR_FRAME_MAX) {
      motorFrame = "";
      continue;
    }
    if (c != '#') continue;

    bool valid = false;
    if (motorFrame.startsWith("$MSPD:")) {
      String payload = motorFrame.substring(6, motorFrame.length() - 1);
      valid = parseFourFloats(payload, latestMspd);
      if (valid) lastMspdMs = millis();
    } else if (motorFrame.startsWith("$MAll:")) {
      String payload = motorFrame.substring(6, motorFrame.length() - 1);
      valid = parseFourLongs(payload, latestMAll);
      if (valid) lastMAllMs = millis();
    } else if (motorFrame.startsWith("$MTEP:")) {
      valid = true;
    } else {
      // Configuration, flash and battery replies are passed through verbatim.
      Serial.print("DRIVER,");
      Serial.println(motorFrame);
    }

    if (valid) {
      telemetrySeen = true;
      lastTelemetryMs = millis();
    }
    motorFrame = "";
  }
}

void printTelemetry() {
  unsigned long now = millis();
  if (now - lastTelemetryPrintMs < TELEMETRY_PRINT_MS) return;
  lastTelemetryPrintMs = now;
  Serial.print("VEL,ms="); Serial.print(now);
  Serial.print(",event=telemetry,state="); Serial.print(stateName(controllerState));
  Serial.print(",desired="); printWheelVector(desiredWheelMmps);
  Serial.print(",feedforward="); printWheelVector(feedForwardWheelMmps);
  Serial.print(",correction="); printWheelVector(outerCorrectionMmps);
  Serial.print(",driver="); printWheelVector(driverCommandMmps);
  Serial.print(",mspd="); printFloatVector(latestMspd);
  Serial.print(",mall=");
  Serial.print(latestMAll[0]); Serial.print(',');
  Serial.print(latestMAll[1]); Serial.print(',');
  Serial.print(latestMAll[2]); Serial.print(',');
  Serial.println(latestMAll[3]);
}

void configureAT8236() {
  // Disable output first. Configuration is persistent and some boards may
  // still hold a previous command across an ESP32 reset.
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
  // Do not overwrite MPID here. It is persistent and must first be inspected.
  sendMotorCommand("$read_flash#");
  delay(100);
  sendMotorCommand("$upload:1,1,1#");
  delay(100);
  holdWithVelocityPid();
  driverConfigSent = true;
  printEvent("driver_config_sent",
             "mtype=" + String(AT8236_MOTOR_TYPE) +
             ",mphase=" + String(AT8236_GEAR_RATIO) +
             ",mline=" + String(AT8236_ENCODER_LINES) +
             ",wdiameter=" + String(AT8236_WHEEL_DIAMETER_MM, 1) +
             ",deadzone=" + String(AT8236_DEADZONE) +
             ",mpid=read_only");
}

void disarmController() {
  armed = false;
  armMode = ARM_NONE;
  armedUntilMs = 0;
  outerCorrectionEnabled = false;
}

void beginBrake(const String &reason, bool disarmWhenSettled) {
  holdWithVelocityPid();
  controllerState = BRAKING;
  brakeStartedMs = millis();
  zeroSinceMs = 0;
  disarmAfterBrake = disarmWhenSettled;
  activeUntilMs = 0;
  printEvent("brake_start", "reason=" + reason + ",mode=spd_zero_pid_hold");
}

void enterFaultDisabled(const String &reason) {
  disablePwmOutput();
  disarmController();
  controllerState = FAULT_DISABLED;
  printEvent("fault_disabled", "reason=" + reason + ",mode=pwm_zero");
}

int applyWheelCalibration(int wheelIndex, int rawTarget) {
  if (rawTarget == 0) return 0;
  bool physicalForward = rawTarget * FORWARD_SIGN[wheelIndex] > 0;
  const WheelCalibration &cal = wheelCalibration[wheelIndex];
  int gain = physicalForward ? cal.forwardGainPermille : cal.reverseGainPermille;
  int bias = physicalForward ? cal.forwardBiasMmps : cal.reverseBiasMmps;
  long adjusted = ((long)rawTarget * gain) / 1000L;
  adjusted += rawTarget > 0 ? bias : -bias;
  return constrain((int)adjusted, -MAX_VALIDATION_SPEED_MMPS, MAX_VALIDATION_SPEED_MMPS);
}

void prepareMotion(const int rawDesired[4], bool rawMode, unsigned long durationMs) {
  for (int i = 0; i < 4; ++i) {
    desiredWheelMmps[i] = rawDesired[i];
    feedForwardWheelMmps[i] = rawMode ? rawDesired[i] : applyWheelCalibration(i, rawDesired[i]);
    outerCorrectionMmps[i] = 0;
    driverCommandMmps[i] = feedForwardWheelMmps[i];
    testStartMAll[i] = latestMAll[i];
    feedbackMismatchSinceMs[i] = 0;
    overspeedSinceMs[i] = 0;
  }
  motionStartedMs = millis();
  activeUntilMs = motionStartedMs + durationMs;
  lastControlMs = 0;
  lastOuterMs = 0;
  controllerState = rawMode ? RUNNING_RAW : RUNNING_DRIVE;
  sendDriverVelocityCommand();
  printEvent("motion_start",
             "mode=" + String(rawMode ? "raw" : "drive") +
             ",arm_mode=" + String(armModeName(armMode)) +
             ",duration_ms=" + String(durationMs));
}

bool serviceFeedbackSafety() {
  unsigned long now = millis();
  for (int i = 0; i < 4; ++i) {
    if (desiredWheelMmps[i] == 0) {
      feedbackMismatchSinceMs[i] = 0;
      overspeedSinceMs[i] = 0;
      continue;
    }

    float measuredInCommandFrame = latestMspd[i] * MSPD_TO_COMMAND_SIGN;
    bool signMismatch =
      absFloat(measuredInCommandFrame) > ZERO_SPEED_MMPS &&
      ((measuredInCommandFrame > 0) != (desiredWheelMmps[i] > 0));
    if (signMismatch) {
      if (feedbackMismatchSinceMs[i] == 0) feedbackMismatchSinceMs[i] = now;
      if (now - feedbackMismatchSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterFaultDisabled("feedback_sign_mismatch_m" + String(i + 1));
        return false;
      }
    } else {
      feedbackMismatchSinceMs[i] = 0;
    }

    float overspeedLimit = max(
      OVERSPEED_MIN_MMPS,
      absFloat((float)desiredWheelMmps[i]) * OVERSPEED_RATIO);
    if (absFloat(measuredInCommandFrame) > overspeedLimit) {
      if (overspeedSinceMs[i] == 0) overspeedSinceMs[i] = now;
      if (now - overspeedSinceMs[i] >= FEEDBACK_FAULT_CONFIRM_MS) {
        enterFaultDisabled("overspeed_m" + String(i + 1));
        return false;
      }
    } else {
      overspeedSinceMs[i] = 0;
    }
  }
  return true;
}

void serviceOuterCorrection() {
  if (controllerState != RUNNING_DRIVE || !outerCorrectionEnabled) return;
  unsigned long now = millis();
  // Keep the beginning and end of each short test feed-forward only. This
  // prevents launch transients and the braking edge from winding the outer
  // correction up.
  if (now - motionStartedMs < OUTER_DELAY_MS) return;
  if (activeUntilMs == 0 || activeUntilMs <= now ||
      activeUntilMs - now <= OUTER_DELAY_MS) return;
  if (now - lastOuterMs < OUTER_UPDATE_MS || !mspdFresh()) return;
  lastOuterMs = now;

  for (int i = 0; i < 4; ++i) {
    if (desiredWheelMmps[i] == 0) {
      outerCorrectionMmps[i] = 0;
      driverCommandMmps[i] = 0;
      continue;
    }

    float measuredInCommandFrame = latestMspd[i] * MSPD_TO_COMMAND_SIGN;
    if (absFloat(measuredInCommandFrame) > ZERO_SPEED_MMPS &&
        ((measuredInCommandFrame > 0) != (desiredWheelMmps[i] > 0))) {
      beginBrake("feedback_sign_mismatch_m" + String(i + 1), true);
      return;
    }

    float error = (float)desiredWheelMmps[i] - measuredInCommandFrame;
    int step = (int)lroundf(error * OUTER_KI);
    step = constrain(step, -OUTER_MAX_STEP_MMPS, OUTER_MAX_STEP_MMPS);
    outerCorrectionMmps[i] = constrain(
      outerCorrectionMmps[i] + step,
      -OUTER_MAX_CORRECTION_MMPS,
      OUTER_MAX_CORRECTION_MMPS);

    int next = feedForwardWheelMmps[i] + outerCorrectionMmps[i];
    next = constrain(next, -MAX_VALIDATION_SPEED_MMPS, MAX_VALIDATION_SPEED_MMPS);
    if ((next > 0) != (desiredWheelMmps[i] > 0) || next == 0) {
      next = desiredWheelMmps[i] > 0 ? 1 : -1;
    }
    driverCommandMmps[i] = next;
  }
}

void serviceMotion() {
  unsigned long now = millis();
  if (controllerState != RUNNING_RAW && controllerState != RUNNING_DRIVE) return;

  if (!telemetryFresh() || !mspdFresh()) {
    enterFaultDisabled("telemetry_timeout_while_moving");
    return;
  }
  if (!serviceFeedbackSafety()) return;
  if (!armed || now >= armedUntilMs) {
    beginBrake("arm_expired", true);
    return;
  }
  if (activeUntilMs != 0 && now >= activeUntilMs) {
    // A landed validation command is single-shot: after it settles, require
    // the operator to inspect the cart and explicitly arm the next test.
    beginBrake("duration", isRestrictedGroundMode(armMode));
    return;
  }

  serviceOuterCorrection();
  if (controllerState != RUNNING_RAW && controllerState != RUNNING_DRIVE) return;
  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    lastControlMs = now;
    sendDriverVelocityCommand();
  }
}

void serviceBrake() {
  if (controllerState != BRAKING) return;
  unsigned long now = millis();
  // Refresh zero target while braking so a stale command cannot survive.
  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    lastControlMs = now;
    sendSpeed(0, 0, 0, 0);
  }

  if (!mspdFresh()) {
    enterFaultDisabled("mspd_lost_while_braking");
    return;
  }

  // $spd:0 normally provides active PID braking. If a wrong phase setting or
  // a driver fault leaves a wheel fast after a short grace period, release
  // the PWM immediately instead of sustaining a positive-feedback loop for
  // the full brake timeout.
  if (now - brakeStartedMs >= BRAKE_PID_GRACE_MS) {
    for (int i = 0; i < 4; ++i) {
      if (absFloat(latestMspd[i]) > BRAKE_FALLBACK_SPEED_MMPS) {
        enterFaultDisabled("pid_brake_failed_m" + String(i + 1));
        return;
      }
    }
  }

  if (allWheelsNearZero()) {
    if (zeroSinceMs == 0) zeroSinceMs = now;
    if (now - zeroSinceMs >= ZERO_HOLD_MS) {
      long motionDelta[4];
      Serial.print("VEL,ms="); Serial.print(now);
      Serial.print(",event=brake_settled,delta_mall=");
      for (int i = 0; i < 4; ++i) {
        motionDelta[i] = latestMAll[i] - testStartMAll[i];
        Serial.print(motionDelta[i]);
        if (i < 3) Serial.print(',');
      }
      if (armMode == ARM_ARC) {
        long leftAbsAvg = (abs(motionDelta[0]) + abs(motionDelta[2])) / 2L;
        long rightAbsAvg = (abs(motionDelta[1]) + abs(motionDelta[3])) / 2L;
        Serial.print(",arc_left_abs_avg="); Serial.print(leftAbsAvg);
        Serial.print(",arc_right_abs_avg="); Serial.print(rightAbsAvg);
        Serial.print(",arc_abs_diff="); Serial.print(abs(leftAbsAvg - rightAbsAvg));
      }
      Serial.println();
      cooldownUntilMs = now + COOLDOWN_MS;
      if (disarmAfterBrake) disarmController();
      controllerState = armed ? ARMED_IDLE : SAFE_HOLD;
      return;
    }
  } else {
    zeroSinceMs = 0;
  }

  if (now - brakeStartedMs >= BRAKE_TIMEOUT_MS) {
    enterFaultDisabled("brake_timeout");
  }
}

bool isNewSequence(long sequence) {
  return sequence > 0 && (unsigned long)sequence > lastSequence;
}

void commitSequence(long sequence) {
  lastSequence = (unsigned long)sequence;
}

bool readyForMotion() {
  return armed && millis() < armedUntilMs && controllerState == ARMED_IDLE &&
         millis() >= cooldownUntilMs && telemetryFresh() && mspdFresh() && allWheelsNearZero();
}

void reject(const String &reason) {
  Serial.print("!ERR,");
  Serial.println(reason);
}

void handleArm(const String &line) {
  ArmMode requestedMode = ARM_NONE;
  if (line == "!A,RAISED") {
    requestedMode = ARM_RAISED;
  } else if (line == "!A,LANDED") {
    requestedMode = ARM_LANDED;
  } else if (line == "!A,TURN") {
    requestedMode = ARM_TURN;
  } else if (line == "!A,STRAFE") {
    requestedMode = ARM_STRAFE;
  } else if (line == "!A,ARC") {
    requestedMode = ARM_ARC;
  } else {
    reject("A format");
    return;
  }
  if (!driverConfigSent || !telemetryFresh() || !mspdFresh()) {
    reject("A telemetry");
    return;
  }
  if (!allWheelsNearZero()) {
    reject("A wheels_not_zero");
    return;
  }
  if (controllerState == FAULT_DISABLED) {
    reject("A fault_reboot_required");
    return;
  }
  holdWithVelocityPid();
  armed = true;
  armMode = requestedMode;
  unsigned long armWindowMs =
    isRestrictedGroundMode(armMode) ? LANDED_ARM_WINDOW_MS : RAISED_ARM_WINDOW_MS;
  armedUntilMs = millis() + armWindowMs;
  outerCorrectionEnabled = false;
  controllerState = ARMED_IDLE;
  Serial.println("!OK,A");
  printEvent("armed",
             "arm_mode=" + String(armModeName(armMode)) +
             ",window_ms=" + String(armWindowMs) + ",outer=0");
}

void handleSingleWheelTest(const String &line) {
  String parts[5];
  if (splitCsv(line, parts, 5) != 5) {
    reject("T format");
    return;
  }
  long sequence, motor, speed, duration;
  if (!parseLongStrict(parts[1], sequence) || !parseLongStrict(parts[2], motor) ||
      !parseLongStrict(parts[3], speed) || !parseLongStrict(parts[4], duration)) {
    reject("T format");
    return;
  }
  if (!isNewSequence(sequence)) { reject("T stale"); return; }
  if (armMode != ARM_RAISED) {
    reject("T raised_only");
    return;
  }
  if (motor < 1 || motor > 4 || speed == 0 ||
      abs(speed) > MAX_VALIDATION_SPEED_MMPS ||
      duration < MIN_TEST_DURATION_MS || duration > MAX_TEST_DURATION_MS) {
    reject("T range");
    return;
  }
  if (!readyForMotion()) { reject("T not_ready"); return; }
  commitSequence(sequence);
  int raw[4] = {0, 0, 0, 0};
  raw[motor - 1] = (int)speed;
  prepareMotion(raw, true, (unsigned long)duration);
  Serial.println("!OK,T");
}

void handleDriveTest(const String &line) {
  String parts[5];
  if (splitCsv(line, parts, 5) != 5) {
    reject("D format");
    return;
  }
  long sequence, left, right, duration;
  if (!parseLongStrict(parts[1], sequence) || !parseLongStrict(parts[2], left) ||
      !parseLongStrict(parts[3], right) || !parseLongStrict(parts[4], duration)) {
    reject("D format");
    return;
  }
  if (!isNewSequence(sequence)) { reject("D stale"); return; }
  if (armMode == ARM_STRAFE) { reject("D strafe_only"); return; }
  if ((left == 0 && right == 0) || abs(left) > MAX_VALIDATION_SPEED_MMPS ||
      abs(right) > MAX_VALIDATION_SPEED_MMPS ||
      duration < MIN_TEST_DURATION_MS || duration > MAX_TEST_DURATION_MS) {
    reject("D range");
    return;
  }
  if (armMode == ARM_LANDED &&
      (left != right || abs(left) > MAX_LANDED_SPEED_MMPS ||
       duration > MAX_LANDED_DURATION_MS)) {
    reject("D landed_limit");
    return;
  }
  if (armMode == ARM_TURN &&
      (left != -right || abs(left) < MIN_LANDED_TURN_SPEED_MMPS ||
       abs(left) > MAX_LANDED_TURN_SPEED_MMPS ||
       duration < MIN_LANDED_TURN_DURATION_MS ||
       duration > MAX_LANDED_TURN_DURATION_MS)) {
    reject("D turn_limit");
    return;
  }
  if (armMode == ARM_ARC &&
      (left == 0 || right == 0 || ((left > 0) != (right > 0)) ||
       abs(left) < MIN_LANDED_ARC_SIDE_SPEED_MMPS ||
       abs(right) < MIN_LANDED_ARC_SIDE_SPEED_MMPS ||
       abs(left) > MAX_LANDED_ARC_SIDE_SPEED_MMPS ||
       abs(right) > MAX_LANDED_ARC_SIDE_SPEED_MMPS ||
       max(abs(left), abs(right)) != REQUIRED_LANDED_ARC_OUTER_SPEED_MMPS ||
       abs(left - right) < MIN_LANDED_ARC_DELTA_MMPS ||
       abs(left - right) > MAX_LANDED_ARC_DELTA_MMPS ||
       duration < MIN_LANDED_ARC_DURATION_MS ||
       duration > MAX_LANDED_ARC_DURATION_MS)) {
    reject("D arc_limit");
    return;
  }
  if (!readyForMotion()) { reject("D not_ready"); return; }
  commitSequence(sequence);
  int raw[4] = {
    (int)left * FORWARD_SIGN[0],
    (int)right * FORWARD_SIGN[1],
    (int)left * FORWARD_SIGN[2],
    (int)right * FORWARD_SIGN[3]
  };
  prepareMotion(raw, false, (unsigned long)duration);
  Serial.println("!OK,D");
}

void handleStrafeTest(const String &line) {
  String parts[4];
  if (splitCsv(line, parts, 4) != 4) {
    reject("Y format");
    return;
  }
  long sequence, right, duration;
  if (!parseLongStrict(parts[1], sequence) || !parseLongStrict(parts[2], right) ||
      !parseLongStrict(parts[3], duration)) {
    reject("Y format");
    return;
  }
  if (!isNewSequence(sequence)) { reject("Y stale"); return; }
  if (armMode != ARM_STRAFE) { reject("Y strafe_only"); return; }
  if (right == 0 || abs(right) < MIN_LANDED_STRAFE_SPEED_MMPS ||
      abs(right) > MAX_LANDED_STRAFE_SPEED_MMPS ||
      duration < MIN_LANDED_STRAFE_DURATION_MS ||
      duration > MAX_LANDED_STRAFE_DURATION_MS) {
    reject("Y strafe_limit");
    return;
  }
  if (!readyForMotion()) { reject("Y not_ready"); return; }
  commitSequence(sequence);

  // Positive means chassis-right. Physical wheel directions in hardware order
  // M1=left rear, M2=right rear, M3=left front, M4=right front are -,+,+,-.
  // FORWARD_SIGN converts those physical directions to AT8236 command signs.
  int physicalForwardMmps[4] = {
    -(int)right, (int)right, (int)right, -(int)right
  };
  int raw[4];
  for (int i = 0; i < 4; ++i) {
    raw[i] = physicalForwardMmps[i] * FORWARD_SIGN[i];
  }
  prepareMotion(raw, false, (unsigned long)duration);
  Serial.println("!OK,Y");
}

void handleOuterLoop(const String &line) {
  String parts[2];
  long enabled;
  if (splitCsv(line, parts, 2) != 2 || !parseLongStrict(parts[1], enabled) ||
      (enabled != 0 && enabled != 1)) {
    reject("L format");
    return;
  }
  if (!armed || controllerState != ARMED_IDLE) {
    reject("L not_idle");
    return;
  }
  if (isRestrictedGroundMode(armMode) && enabled == 1) {
    reject("L raised_only");
    return;
  }
  outerCorrectionEnabled = enabled == 1;
  Serial.print("!OK,L,");
  Serial.println(outerCorrectionEnabled ? 1 : 0);
}

void handleCalibration(const String &line) {
  String parts[6];
  if (splitCsv(line, parts, 6) != 6) {
    reject("G format");
    return;
  }
  long motor, fg, rg, fb, rb;
  if (!parseLongStrict(parts[1], motor) || !parseLongStrict(parts[2], fg) ||
      !parseLongStrict(parts[3], rg) || !parseLongStrict(parts[4], fb) ||
      !parseLongStrict(parts[5], rb)) {
    reject("G format");
    return;
  }
  if (controllerState == RUNNING_RAW || controllerState == RUNNING_DRIVE ||
      controllerState == BRAKING) {
    reject("G busy");
    return;
  }
  if (isRestrictedGroundMode(armMode)) {
    reject("G raised_only");
    return;
  }
  if (motor < 1 || motor > 4 || fg < 500 || fg > 1500 || rg < 500 || rg > 1500 ||
      fb < 0 || fb > 100 || rb < 0 || rb > 100) {
    reject("G range");
    return;
  }
  WheelCalibration &cal = wheelCalibration[motor - 1];
  cal.forwardGainPermille = (int)fg;
  cal.reverseGainPermille = (int)rg;
  cal.forwardBiasMmps = (int)fb;
  cal.reverseBiasMmps = (int)rb;
  Serial.println("!OK,G");
  printEvent("calibration_updated",
             "motor=" + String(motor) + ",forward_gain=" + String(fg) +
             ",reverse_gain=" + String(rg) + ",forward_bias=" + String(fb) +
             ",reverse_bias=" + String(rb) + ",persistent=0");
}

void handleStop(const String &line) {
  String parts[2];
  long sequence;
  if (splitCsv(line, parts, 2) != 2 || !parseLongStrict(parts[1], sequence)) {
    reject("S format");
    return;
  }
  if (!isNewSequence(sequence)) { reject("S stale"); return; }
  if (controllerState == FAULT_DISABLED || controllerState == RELEASED) {
    reject("S unavailable");
    return;
  }
  commitSequence(sequence);
  beginBrake("manual_stop", true);
  Serial.println("!OK,S");
}

void handleRelease(const String &line) {
  String parts[2];
  long sequence;
  if (splitCsv(line, parts, 2) != 2 || !parseLongStrict(parts[1], sequence)) {
    reject("R format");
    return;
  }
  if (!isNewSequence(sequence)) { reject("R stale"); return; }
  if (controllerState == RUNNING_RAW || controllerState == RUNNING_DRIVE ||
      controllerState == BRAKING || !allWheelsNearZero()) {
    reject("R not_stationary");
    return;
  }
  commitSequence(sequence);
  disablePwmOutput();
  disarmController();
  controllerState = RELEASED;
  Serial.println("!OK,R");
  printEvent("output_released", "mode=pwm_zero");
}

void handleDriverRead(const String &line) {
  if (line == "!F") {
    sendMotorCommand("$read_flash#");
    Serial.println("!OK,F");
  } else if (line == "!B") {
    sendMotorCommand("$read_vol#");
    Serial.println("!OK,B");
  } else {
    reject("driver_read");
  }
}

void processUsbLine(const String &line) {
  if (line == "!Q") { printStatus(); return; }
  if (line == "!F" || line == "!B") { handleDriverRead(line); return; }
  if (line.startsWith("!A")) { handleArm(line); return; }
  if (line.startsWith("!T,")) { handleSingleWheelTest(line); return; }
  if (line.startsWith("!D,")) { handleDriveTest(line); return; }
  if (line.startsWith("!Y,")) { handleStrafeTest(line); return; }
  if (line.startsWith("!L,")) { handleOuterLoop(line); return; }
  if (line.startsWith("!G,")) { handleCalibration(line); return; }
  if (line.startsWith("!S,")) { handleStop(line); return; }
  if (line.startsWith("!R,")) { handleRelease(line); return; }
  reject("unsupported");
}

void pollUsb() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (usbLineOverflow) {
        reject("line_overflow");
      } else if (usbLineLength > 0) {
        usbLine[usbLineLength] = '\0';
        processUsbLine(String(usbLine));
      }
      usbLineLength = 0;
      usbLineOverflow = false;
      usbLine[0] = '\0';
      continue;
    }
    if (usbLineOverflow) continue;
    if (usbLineLength >= USB_LINE_MAX) {
      usbLineLength = 0;
      usbLineOverflow = true;
      continue;
    }
    usbLine[usbLineLength++] = c;
  }
}

void serviceArmExpiry() {
  if (armed && millis() >= armedUntilMs &&
      controllerState != RUNNING_RAW && controllerState != RUNNING_DRIVE &&
      controllerState != BRAKING) {
    beginBrake("arm_expired_idle", true);
  }
}

void setup() {
  Serial.begin(USB_BAUD);
  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);
  delay(300);
  configureAT8236();
  controllerState = BOOT_HOLD;
  Serial.println("ESP32 AT8236 velocity validation firmware ready.");
  Serial.println("Wait for MSPD, then explicitly select a validation arm mode.");
  Serial.println("LANDED mode is straight-only, <=100 mm/s, <=5000 ms, single-shot.");
  Serial.println("TURN mode is pivot-only, 60..100 mm/s, 1000..2000 ms, single-shot.");
  Serial.println("STRAFE mode uses !Y and is lateral-only, 80..100 mm/s, 1000..2000 ms, single-shot.");
  Serial.println("ARC mode requires outer=100, inner=40..80 mm/s, 1000..4000 ms, single-shot.");
}

void loop() {
  pollUsb();
  serviceMotorSerial();

  if (controllerState == BOOT_HOLD && telemetryFresh() && mspdFresh()) {
    controllerState = SAFE_HOLD;
    printEvent("ready", "mode=spd_zero_pid_hold");
  }

  printTelemetry();
  serviceMotion();
  serviceBrake();
  serviceArmExpiry();
}
