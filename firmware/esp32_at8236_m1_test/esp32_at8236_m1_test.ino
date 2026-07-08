/*
  ESP32 + AT8236 four-motor bring-up test

  Wiring:
    ESP32 GPIO17 / D17 / TX1 -> AT8236 RX2
    ESP32 GPIO16 / D16 / RX1 <- AT8236 TX2
    ESP32 GND               -> AT8236 GND

  Arduino IDE Serial Monitor:
    Baud: 115200
    Line ending: Newline or Both NL & CR

  Commands:
    i  initialize AT8236 parameters
    f  M1 forward low speed, keep running until stop
    r  M1 reverse low speed, keep running until stop
    1  M1 +speed for 1 second, then stop
    2  M1 -speed for 1 second, then stop
    3  M2 +speed for 1 second, then stop
    4  M2 -speed for 1 second, then stop
    5  M3 +speed for 1 second, then stop
    6  M3 -speed for 1 second, then stop
    7  M4 +speed for 1 second, then stop
    8  M4 -speed for 1 second, then stop
    a  all motors raw +speed for 1 second, then stop
    b  all motors raw -speed for 1 second, then stop
    w  chassis forward with soft start, then stop
    x  chassis backward with soft start, then stop
    g  wait 5 seconds, then run a gentle forward/backward demo
    s  stop all motors
    u  enable upload of encoder and speed data, print filtered frames
    o  disable upload of encoder and speed data
    v  verbose command echo on
    q  quiet command echo off
    p  send PWM test to M1
*/

#include <Arduino.h>

HardwareSerial MotorSerial(2);

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;

static const int MOTOR_BAUD = 115200;
static const int TEST_SPEED = 80;
static const int CHASSIS_TEST_SPEED = 35;
static const unsigned long SINGLE_MOTOR_TEST_MS = 800;
static const unsigned long CHASSIS_TEST_MS = 700;
static const int RAMP_STEP = 5;
static const unsigned long RAMP_STEP_MS = 120;
static const unsigned long AUTONOMOUS_START_DELAY_MS = 5000;
static const int TEST_PWM = 1700;

// Current measured directions, viewed from each wheel's outside:
// M1: + is CCW, - is CW
// M2: + is CCW, - is CW
// M3: + is CW,  - is CCW
// M4: + is CW,  - is CCW
//
// Suggested wheel placement:
//   M3 = left front, M4 = right front
//   M1 = left rear,  M2 = right rear
//
// For straight forward:
//   left wheels should be CW from outside, right wheels should be CCW from outside.
static const int M1_FORWARD = -CHASSIS_TEST_SPEED;
static const int M2_FORWARD = CHASSIS_TEST_SPEED;
static const int M3_FORWARD = CHASSIS_TEST_SPEED;
static const int M4_FORWARD = -CHASSIS_TEST_SPEED;

bool verboseEcho = false;
bool printMotorFrames = false;
String motorFrame;

void sendMotorCommand(const char *cmd) {
  MotorSerial.print(cmd);
  if (verboseEcho) {
    Serial.print("TX -> AT8236: ");
    Serial.println(cmd);
  }
}

void stopAllMotors() {
  sendMotorCommand("$spd:0,0,0,0#");
  delay(50);
  sendMotorCommand("$pwm:0,0,0,0#");
}

void initAT8236() {
  Serial.println();
  Serial.println("Initializing AT8236 for 12V 520 encoder motor, ratio 30...");

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
  sendMotorCommand("$upload:0,0,0#");
  delay(100);
  stopAllMotors();

  Serial.println("Init done. Default telemetry is off. Send 1-8/a/b/f/r/s/u/o/p.");
}

void printHelp() {
  Serial.println();
  Serial.println("ESP32 + AT8236 M1 test ready.");
  Serial.println("Commands:");
  Serial.println("  i : initialize AT8236 parameters");
  Serial.println("  1 : M1 +speed for 1 second, then stop");
  Serial.println("  2 : M1 -speed for 1 second, then stop");
  Serial.println("  3 : M2 +speed for 1 second, then stop");
  Serial.println("  4 : M2 -speed for 1 second, then stop");
  Serial.println("  5 : M3 +speed for 1 second, then stop");
  Serial.println("  6 : M3 -speed for 1 second, then stop");
  Serial.println("  7 : M4 +speed for 1 second, then stop");
  Serial.println("  8 : M4 -speed for 1 second, then stop");
  Serial.println("  a : all motors raw +speed for 1 second, then stop");
  Serial.println("  b : all motors raw -speed for 1 second, then stop");
  Serial.println("  w : chassis forward with soft start, then stop");
  Serial.println("  x : chassis backward with soft start, then stop");
  Serial.println("  g : wait 5 seconds, then gentle forward/backward demo");
  Serial.println("  f : M1 +speed, keep running");
  Serial.println("  r : M1 -speed, keep running");
  Serial.println("  s : stop all motors");
  Serial.println("  u : enable and print upload frames");
  Serial.println("  o : disable upload frames");
  Serial.println("  v : verbose command echo on");
  Serial.println("  q : quiet command echo off");
  Serial.println("  p : M1 PWM low power test");
  Serial.println();
}

void printFilteredMotorFrame(const String &frame) {
  static unsigned long lastPrintMs = 0;
  unsigned long now = millis();

  if (!printMotorFrames || now - lastPrintMs < 300) {
    return;
  }

  if (frame.startsWith("$MSPD:") || frame.startsWith("$MTEP:") || frame.startsWith("$MAll:")) {
    Serial.println(frame);
    lastPrintMs = now;
  }
}

void readMotorFrames() {
  while (MotorSerial.available() > 0) {
    char c = MotorSerial.read();

    if (c == '$') {
      motorFrame = "$";
      continue;
    }

    if (motorFrame.length() == 0) {
      continue;
    }

    motorFrame += c;

    if (c == '#') {
      printFilteredMotorFrame(motorFrame);
      motorFrame = "";
    } else if (motorFrame.length() > 80) {
      motorFrame = "";
    }
  }
}

void timedSpeedTest(int m1, int m2, int m3, int m4, const char *label, unsigned long durationMs) {
  char cmd[32];
  snprintf(cmd, sizeof(cmd), "$spd:%d,%d,%d,%d#", m1, m2, m3, m4);

  sendMotorCommand(cmd);
  Serial.print("Timed speed test: ");
  Serial.println(label);
  Serial.print("Duration ms: ");
  Serial.println(durationMs);

  unsigned long startMs = millis();
  while (millis() - startMs < durationMs) {
    readMotorFrames();
  }

  stopAllMotors();
  Serial.println("Timed test stopped.");
}

void sendSpeed(int m1, int m2, int m3, int m4) {
  char cmd[32];
  snprintf(cmd, sizeof(cmd), "$spd:%d,%d,%d,%d#", m1, m2, m3, m4);
  sendMotorCommand(cmd);
}

int scaleSpeed(int target, int currentAbsSpeed, int targetAbsSpeed) {
  if (target == 0 || targetAbsSpeed == 0) {
    return 0;
  }
  return (target > 0 ? 1 : -1) * currentAbsSpeed;
}

void softChassisMove(int m1Target, int m2Target, int m3Target, int m4Target, const char *label, unsigned long cruiseMs) {
  int targetAbsSpeed = max(max(abs(m1Target), abs(m2Target)), max(abs(m3Target), abs(m4Target)));
  if (targetAbsSpeed <= 0) {
    stopAllMotors();
    return;
  }

  Serial.print("Soft chassis move: ");
  Serial.println(label);
  Serial.print("Target speed: ");
  Serial.println(targetAbsSpeed);

  for (int speed = RAMP_STEP; speed <= targetAbsSpeed; speed += RAMP_STEP) {
    sendSpeed(
      scaleSpeed(m1Target, speed, targetAbsSpeed),
      scaleSpeed(m2Target, speed, targetAbsSpeed),
      scaleSpeed(m3Target, speed, targetAbsSpeed),
      scaleSpeed(m4Target, speed, targetAbsSpeed));
    unsigned long startMs = millis();
    while (millis() - startMs < RAMP_STEP_MS) {
      readMotorFrames();
    }
  }

  unsigned long cruiseStartMs = millis();
  while (millis() - cruiseStartMs < cruiseMs) {
    readMotorFrames();
  }

  for (int speed = targetAbsSpeed - RAMP_STEP; speed > 0; speed -= RAMP_STEP) {
    sendSpeed(
      scaleSpeed(m1Target, speed, targetAbsSpeed),
      scaleSpeed(m2Target, speed, targetAbsSpeed),
      scaleSpeed(m3Target, speed, targetAbsSpeed),
      scaleSpeed(m4Target, speed, targetAbsSpeed));
    unsigned long startMs = millis();
    while (millis() - startMs < RAMP_STEP_MS) {
      readMotorFrames();
    }
  }

  stopAllMotors();
  Serial.println("Soft move stopped.");
}

void delayedGentleDemo() {
  Serial.println("Gentle demo will start in 5 seconds. Keep the cart clear.");
  stopAllMotors();

  unsigned long startMs = millis();
  while (millis() - startMs < AUTONOMOUS_START_DELAY_MS) {
    readMotorFrames();
    if (Serial.available() > 0 && (Serial.peek() == 's' || Serial.peek() == 'S')) {
      Serial.read();
      stopAllMotors();
      Serial.println("Gentle demo canceled.");
      return;
    }
  }

  softChassisMove(M1_FORWARD, M2_FORWARD, M3_FORWARD, M4_FORWARD, "gentle demo forward", CHASSIS_TEST_MS);
  delay(800);
  softChassisMove(-M1_FORWARD, -M2_FORWARD, -M3_FORWARD, -M4_FORWARD, "gentle demo backward", CHASSIS_TEST_MS);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);
  delay(500);

  printHelp();
  initAT8236();
}

void loop() {
  readMotorFrames();

  if (Serial.available() <= 0) {
    return;
  }

  char c = Serial.read();
  if (c == '\r' || c == '\n' || c == ' ') {
    return;
  }

  switch (c) {
    case 'i':
    case 'I':
      initAT8236();
      break;

    case '1':
      timedSpeedTest(TEST_SPEED, 0, 0, 0, "M1 +speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '2':
      timedSpeedTest(-TEST_SPEED, 0, 0, 0, "M1 -speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '3':
      timedSpeedTest(0, TEST_SPEED, 0, 0, "M2 +speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '4':
      timedSpeedTest(0, -TEST_SPEED, 0, 0, "M2 -speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '5':
      timedSpeedTest(0, 0, TEST_SPEED, 0, "M3 +speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '6':
      timedSpeedTest(0, 0, -TEST_SPEED, 0, "M3 -speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '7':
      timedSpeedTest(0, 0, 0, TEST_SPEED, "M4 +speed", SINGLE_MOTOR_TEST_MS);
      break;

    case '8':
      timedSpeedTest(0, 0, 0, -TEST_SPEED, "M4 -speed", SINGLE_MOTOR_TEST_MS);
      break;

    case 'a':
    case 'A':
      timedSpeedTest(TEST_SPEED, TEST_SPEED, TEST_SPEED, TEST_SPEED, "all motors raw +speed", SINGLE_MOTOR_TEST_MS);
      break;

    case 'b':
    case 'B':
      timedSpeedTest(-TEST_SPEED, -TEST_SPEED, -TEST_SPEED, -TEST_SPEED, "all motors raw -speed", SINGLE_MOTOR_TEST_MS);
      break;

    case 'w':
    case 'W':
      softChassisMove(M1_FORWARD, M2_FORWARD, M3_FORWARD, M4_FORWARD, "chassis forward", CHASSIS_TEST_MS);
      break;

    case 'x':
    case 'X':
      softChassisMove(-M1_FORWARD, -M2_FORWARD, -M3_FORWARD, -M4_FORWARD, "chassis backward", CHASSIS_TEST_MS);
      break;

    case 'g':
    case 'G':
      delayedGentleDemo();
      break;

    case 'f':
    case 'F':
      sendMotorCommand("$spd:120,0,0,0#");
      Serial.println("M1 forward. Send s to stop.");
      break;

    case 'r':
    case 'R':
      sendMotorCommand("$spd:-120,0,0,0#");
      Serial.println("M1 reverse. Send s to stop.");
      break;

    case 's':
    case 'S':
      stopAllMotors();
      Serial.println("Stopped.");
      break;

    case 'u':
    case 'U':
      printMotorFrames = true;
      sendMotorCommand("$upload:1,1,1#");
      Serial.println("Upload frames enabled. Printing at most once every 300 ms.");
      break;

    case 'o':
    case 'O':
      printMotorFrames = false;
      sendMotorCommand("$upload:0,0,0#");
      Serial.println("Upload frames disabled.");
      break;

    case 'v':
    case 'V':
      verboseEcho = true;
      Serial.println("Verbose command echo enabled.");
      break;

    case 'q':
    case 'Q':
      verboseEcho = false;
      Serial.println("Quiet command echo enabled.");
      break;

    case 'p':
    case 'P':
      sendMotorCommand("$pwm:1700,0,0,0#");
      Serial.println("M1 PWM test. Send s to stop.");
      break;

    default:
      Serial.print("Unknown command: ");
      Serial.println(c);
      printHelp();
      break;
  }
}
