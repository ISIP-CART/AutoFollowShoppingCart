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
    z  turn left in place with soft start, then stop
    c  turn right in place with soft start, then stop
    h  strafe left with soft start, then stop
    l  strafe right with soft start, then stop
    !C,<seq>,<left>,<right>  host tank control, values in [-255,255]
    !M,<seq>,<vx>,<vy>,<wz>  host mecanum control, values in [-255,255]
    !S,<seq>                host emergency stop
    !H,<timeout_ms>         host command timeout, default 500 ms
    !Q                      query current controller status
    s  stop all motors
    u  enable upload of encoder and speed data, print filtered frames
    o  disable upload of encoder and speed data
    v  verbose command echo on
    q  quiet command echo off
    p  send PWM test to M1
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>

HardwareSerial MotorSerial(2);
WebServer server(80);
DNSServer dnsServer;

static const int MOTOR_RX = 16;
static const int MOTOR_TX = 17;

static const int MOTOR_BAUD = 115200;
static const int TEST_SPEED = 80;
// Ground-driving speeds: 26--34 was enough with the chassis suspended, but
// often could not overcome roller and floor static friction.
static const int CHASSIS_TEST_SPEED = 52;
static const int TURN_TEST_SPEED = 48;
static const int STRAFE_TEST_SPEED = 68;
static const int MAX_MOTOR_SPEED = 100;
// Reach useful torque promptly, while retaining a small soft-start.
static const int CONTROL_RAMP_STEP = 6;
static const unsigned long SINGLE_MOTOR_TEST_MS = 800;
static const unsigned long CHASSIS_TEST_MS = 700;
static const int RAMP_STEP = 5;
static const unsigned long RAMP_STEP_MS = 60;
static const unsigned long AUTONOMOUS_START_DELAY_MS = 5000;
static const unsigned long DEFAULT_COMMAND_TIMEOUT_MS = 500;
static const int TEST_PWM = 1700;
static const char *WIFI_AP_SSID = "CartESP32";
static const char *WIFI_AP_PASS = "cart12345";
static const unsigned long CONTROL_UPDATE_MS = 40;
static const byte DNS_PORT = 53;
const IPAddress AP_IP(192, 168, 4, 1);
const IPAddress AP_GATEWAY(192, 168, 4, 1);
const IPAddress AP_SUBNET(255, 255, 255, 0);

// Per-wheel trim. If the cart drifts, adjust these values in 2-5% steps.
// Example: if the cart drifts left while moving forward, reduce right-side
// trim or increase left-side trim. Keep values near 100.
static const int M1_TRIM_PERCENT = 100;
static const int M2_TRIM_PERCENT = 100;
static const int M3_TRIM_PERCENT = 100;
static const int M4_TRIM_PERCENT = 100;

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
// Motor command signs required for a wheel to drive the cart forward. Keep
// these four values as the only direction-calibration point after rewiring.
// Wheel placement: M3=left-front, M4=right-front, M1=left-rear, M2=right-rear.
static const int M1_FORWARD_SIGN = 1;
static const int M2_FORWARD_SIGN = -1;
static const int M3_FORWARD_SIGN = -1;
static const int M4_FORWARD_SIGN = 1;

bool verboseEcho = false;
bool printMotorFrames = false;
String motorFrame;
unsigned long lastWebSeq = 0;

const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
  <title>ESP32 Cart Remote</title>
  <style>
    html,body{touch-action:none;overscroll-behavior:none}
    body{font-family:Arial,sans-serif;margin:0;background:#111;color:#eee;text-align:center;-webkit-user-select:none;user-select:none}
    h2{font-size:22px;margin:18px 0 6px}
    p{margin:4px 0 16px;color:#aaa}
    .grid{display:grid;grid-template-columns:repeat(3,88px);gap:12px;justify-content:center;margin-top:18px}
    button{height:68px;border:0;border-radius:10px;background:#2f6fed;color:white;font-size:26px;font-weight:700;touch-action:none;-webkit-user-select:none;user-select:none}
    button.stop{background:#d72638}
    button.side{background:#555}
    button:active{filter:brightness(1.35)}
    .hint{font-size:13px;margin:18px 24px;line-height:1.5;color:#bbb}
  </style>
</head>
<body>
  <h2>ESP32 Cart Remote</h2>
  <p>Hold a button to move. Release to stop.</p>
  <div class="grid">
    <div></div><button data-cmd="w">F</button><div></div>
    <button class="side" data-cmd="z">L</button><button class="stop" data-cmd="s">S</button><button class="side" data-cmd="c">R</button>
    <button class="side" data-cmd="h">SL</button><button data-cmd="x">B</button><button class="side" data-cmd="l">SR</button>
  </div>
  <div class="hint">
    F/B: forward/backward<br>
    L/R: turn left/right<br>
    SL/SR: strafe left/right
    <div id="status">ready</div>
  </div>
  <script>
    let timer = null;
    let lastCmd = 's';
    let pendingCmd = null;
    let inFlight = false;
    let seq = 0;
    const statusEl = document.getElementById('status');
    function pump() {
      if (inFlight || pendingCmd === null) return;
      const cmd = pendingCmd;
      pendingCmd = null;
      lastCmd = cmd;
      inFlight = true;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 350);
      fetch('/cmd?c=' + encodeURIComponent(cmd) + '&q=' + (++seq), {
        cache: 'no-store',
        signal: controller.signal
      })
        .then(() => { statusEl.textContent = 'sent: ' + cmd + ' #' + seq; })
        .catch(() => { statusEl.textContent = 'send failed, retrying latest'; })
        .finally(() => {
          clearTimeout(timeout);
          inFlight = false;
          if (pendingCmd !== null) pump();
        });
    }
    function send(cmd) {
      pendingCmd = cmd;
      pump();
    }
    function start(cmd) {
      send(cmd);
      clearInterval(timer);
      timer = setInterval(() => send(cmd), 260);
    }
    function stop() {
      clearInterval(timer);
      timer = null;
      send('s');
    }
    document.querySelectorAll('button').forEach(btn => {
      const cmd = btn.dataset.cmd;
      btn.addEventListener('pointerdown', e => {
        e.preventDefault();
        btn.setPointerCapture(e.pointerId);
        cmd === 's' ? stop() : start(cmd);
      });
      btn.addEventListener('pointerup', e => { e.preventDefault(); stop(); });
      btn.addEventListener('pointercancel', e => { e.preventDefault(); stop(); });
      btn.addEventListener('lostpointercapture', stop);
    });
    window.addEventListener('blur', stop);
  </script>
</body>
</html>
)rawliteral";
String hostCommand;

enum ControlSource {
  SOURCE_NONE,
  SOURCE_WEB,
  SOURCE_SERIAL
};

struct ChassisCommand {
  int vx;
  int vy;
  int wz;
  unsigned long seq;
  unsigned long lastUpdateMs;
  ControlSource source;
};

ChassisCommand commandState = {0, 0, 0, 0, 0, SOURCE_NONE};
int targetM1 = 0;
int targetM2 = 0;
int targetM3 = 0;
int targetM4 = 0;
int currentM1 = 0;
int currentM2 = 0;
int currentM3 = 0;
int currentM4 = 0;
unsigned long commandTimeoutMs = DEFAULT_COMMAND_TIMEOUT_MS;
unsigned long lastControlUpdateMs = 0;

void sendMotorCommand(const char *cmd) {
  MotorSerial.print(cmd);
  if (verboseEcho) {
    Serial.print("TX -> AT8236: ");
    Serial.println(cmd);
  }
}

void stopAllMotors() {
  commandState.vx = 0;
  commandState.vy = 0;
  commandState.wz = 0;
  commandState.source = SOURCE_NONE;
  targetM1 = 0;
  targetM2 = 0;
  targetM3 = 0;
  targetM4 = 0;
  currentM1 = 0;
  currentM2 = 0;
  currentM3 = 0;
  currentM4 = 0;
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
  Serial.println("  z : turn left in place with soft start, then stop");
  Serial.println("  c : turn right in place with soft start, then stop");
  Serial.println("  h : strafe left with soft start, then stop");
  Serial.println("  l : strafe right with soft start, then stop");
  Serial.println("  !C,seq,left,right : host tank control, example !C,1,40,40");
  Serial.println("  !M,seq,vx,vy,wz : host mecanum control, example !M,2,40,0,0");
  Serial.println("  !S,seq : host emergency stop, example !S,3");
  Serial.println("  !H,ms : host command timeout, example !H,500");
  Serial.println("  !Q : query current controller status");
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

int applyTrim(int speed, int trimPercent) {
  return (speed * trimPercent) / 100;
}

void sendDriveSpeed(int m1, int m2, int m3, int m4) {
  sendSpeed(
    applyTrim(m1, M1_TRIM_PERCENT),
    applyTrim(m2, M2_TRIM_PERCENT),
    applyTrim(m3, M3_TRIM_PERCENT),
    applyTrim(m4, M4_TRIM_PERCENT));
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

void setWheelTargetsRaw(int m1, int m2, int m3, int m4) {
  targetM1 = m1;
  targetM2 = m2;
  targetM3 = m3;
  targetM4 = m4;
}

void mixChassisToWheels(int vx, int vy, int wz, int &m1, int &m2, int &m3, int &m4) {
  vx = constrain(vx, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  vy = constrain(vy, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  wz = constrain(wz, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);

  // Canonical motion is converted to each motor's measured forward sign here.
  // Thus F/B, L/R, SL/SR and !M all use exactly the same wheel convention.
  m1 = M1_FORWARD_SIGN * (vx + vy - wz);  // left rear
  m2 = M2_FORWARD_SIGN * (vx - vy + wz);  // right rear
  m3 = M3_FORWARD_SIGN * (vx - vy - wz);  // left front
  m4 = M4_FORWARD_SIGN * (vx + vy + wz);  // right front

  int maxAbs = max(max(abs(m1), abs(m2)), max(abs(m3), abs(m4)));
  if (maxAbs > MAX_MOTOR_SPEED) {
    m1 = (m1 * MAX_MOTOR_SPEED) / maxAbs;
    m2 = (m2 * MAX_MOTOR_SPEED) / maxAbs;
    m3 = (m3 * MAX_MOTOR_SPEED) / maxAbs;
    m4 = (m4 * MAX_MOTOR_SPEED) / maxAbs;
  }

}

void mixChassisToWheelTargets(int vx, int vy, int wz) {
  int m1, m2, m3, m4;
  mixChassisToWheels(vx, vy, wz, m1, m2, m3, m4);
  setWheelTargetsRaw(m1, m2, m3, m4);
}

void setChassisCommand(int vx, int vy, int wz, unsigned long seq, ControlSource source) {
  if (seq > 0 && seq <= commandState.seq) {
    return;
  }

  if (seq > 0) {
    commandState.seq = seq;
  }
  commandState.vx = constrain(vx, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  commandState.vy = constrain(vy, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  commandState.wz = constrain(wz, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  commandState.lastUpdateMs = millis();
  commandState.source = source;
  mixChassisToWheelTargets(commandState.vx, commandState.vy, commandState.wz);
}

void setTankCommand(int left, int right, unsigned long seq, ControlSource source) {
  left = constrain(left, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);
  right = constrain(right, -MAX_MOTOR_SPEED, MAX_MOTOR_SPEED);

  int vx = (left + right) / 2;
  int wz = (right - left) / 2;
  setChassisCommand(vx, 0, wz, seq, source);
}

void updateControlLoop() {
  unsigned long now = millis();
  if (commandState.source != SOURCE_NONE && now - commandState.lastUpdateMs > commandTimeoutMs) {
    Serial.println("Command timeout. Stopping.");
    stopAllMotors();
    return;
  }

  if (commandState.source == SOURCE_NONE &&
      targetM1 == 0 && targetM2 == 0 && targetM3 == 0 && targetM4 == 0 &&
      currentM1 == 0 && currentM2 == 0 && currentM3 == 0 && currentM4 == 0) {
    return;
  }

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
    sendDriveSpeed(
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
    sendDriveSpeed(
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

void softChassisCommand(int vx, int vy, int wz, const char *label, unsigned long cruiseMs) {
  int m1, m2, m3, m4;
  mixChassisToWheels(vx, vy, wz, m1, m2, m3, m4);
  softChassisMove(m1, m2, m3, m4, label, cruiseMs);
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

  softChassisCommand(CHASSIS_TEST_SPEED, 0, 0, "gentle demo forward", CHASSIS_TEST_MS);
  delay(800);
  softChassisCommand(-CHASSIS_TEST_SPEED, 0, 0, "gentle demo backward", CHASSIS_TEST_MS);
}

int tokenToInt(const String &cmd, int tokenIndex) {
  int start = 0;
  int currentToken = 0;

  for (int i = 0; i <= cmd.length(); i++) {
    if (i == cmd.length() || cmd.charAt(i) == ',') {
      if (currentToken == tokenIndex) {
        return cmd.substring(start, i).toInt();
      }
      currentToken++;
      start = i + 1;
    }
  }

  return 0;
}

int countTokens(const String &cmd) {
  if (cmd.length() == 0) {
    return 0;
  }

  int count = 1;
  for (int i = 0; i < cmd.length(); i++) {
    if (cmd.charAt(i) == ',') {
      count++;
    }
  }
  return count;
}

const char *sourceName(ControlSource source) {
  switch (source) {
    case SOURCE_WEB:
      return "WEB";
    case SOURCE_SERIAL:
      return "SERIAL";
    default:
      return "NONE";
  }
}

void printStatus() {
  Serial.print("!Q,source=");
  Serial.print(sourceName(commandState.source));
  Serial.print(",seq=");
  Serial.print(commandState.seq);
  Serial.print(",vx=");
  Serial.print(commandState.vx);
  Serial.print(",vy=");
  Serial.print(commandState.vy);
  Serial.print(",wz=");
  Serial.print(commandState.wz);
  Serial.print(",target=");
  Serial.print(targetM1);
  Serial.print(",");
  Serial.print(targetM2);
  Serial.print(",");
  Serial.print(targetM3);
  Serial.print(",");
  Serial.print(targetM4);
  Serial.print(",current=");
  Serial.print(currentM1);
  Serial.print(",");
  Serial.print(currentM2);
  Serial.print(",");
  Serial.print(currentM3);
  Serial.print(",");
  Serial.print(currentM4);
  Serial.print(",timeout=");
  Serial.print(commandTimeoutMs);
  Serial.println("#");
}

bool processProtocolCommand(const String &cmd) {
  if (!cmd.startsWith("!")) {
    return false;
  }

  char type = cmd.length() > 1 ? cmd.charAt(1) : '\0';

  if (type == 'Q' || type == 'q') {
    printStatus();
    return true;
  }

  if (type == 'H' || type == 'h') {
    if (countTokens(cmd) < 2) {
      Serial.println("!ERR,H requires timeout_ms#");
      return true;
    }

    unsigned long timeoutMs = tokenToInt(cmd, 1);
    if (timeoutMs < 100 || timeoutMs > 3000) {
      Serial.println("!ERR,H timeout range is 100..3000#");
      return true;
    }

    commandTimeoutMs = timeoutMs;
    Serial.print("!OK,H,");
    Serial.print(commandTimeoutMs);
    Serial.println("#");
    return true;
  }

  if (type == 'S' || type == 's') {
    if (countTokens(cmd) >= 2) {
      unsigned long seq = tokenToInt(cmd, 1);
      if (seq > 0 && seq <= commandState.seq) {
        Serial.println("!STALE#");
        return true;
      }
      if (seq > 0) {
        commandState.seq = seq;
      }
    }
    stopAllMotors();
    Serial.println("!OK,S#");
    return true;
  }

  if (type == 'C' || type == 'c') {
    if (countTokens(cmd) < 4) {
      Serial.println("!ERR,C requires seq,left,right#");
      return true;
    }

    unsigned long seq = tokenToInt(cmd, 1);
    if (seq > 0 && seq <= commandState.seq) {
      Serial.println("!STALE#");
      return true;
    }

    int left = tokenToInt(cmd, 2);
    int right = tokenToInt(cmd, 3);
    setTankCommand(left, right, seq, SOURCE_SERIAL);
    Serial.println("!OK,C#");
    return true;
  }

  if (type == 'M' || type == 'm') {
    if (countTokens(cmd) < 5) {
      Serial.println("!ERR,M requires seq,vx,vy,wz#");
      return true;
    }

    unsigned long seq = tokenToInt(cmd, 1);
    if (seq > 0 && seq <= commandState.seq) {
      Serial.println("!STALE#");
      return true;
    }

    int vx = tokenToInt(cmd, 2);
    int vy = tokenToInt(cmd, 3);
    int wz = tokenToInt(cmd, 4);
    setChassisCommand(vx, vy, wz, seq, SOURCE_SERIAL);
    Serial.println("!OK,M#");
    return true;
  }

  Serial.println("!ERR,unknown command#");
  return true;
}

void processHostCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) {
    return;
  }

  if (processProtocolCommand(cmd)) {
    return;
  }

  if ((cmd.charAt(0) == 'c' || cmd.charAt(0) == 'C') && cmd.length() > 1) {
    int commaIndex = cmd.indexOf(',');
    if (commaIndex <= 1) {
      Serial.print("Bad control command: ");
      Serial.println(cmd);
      return;
    }

    int left = cmd.substring(1, commaIndex).toInt();
    int right = cmd.substring(commaIndex + 1).toInt();
    setTankCommand(left, right, 0, SOURCE_SERIAL);

    if (verboseEcho) {
      Serial.print("OpenBot control left/right: ");
      Serial.print(left);
      Serial.print(",");
      Serial.println(right);
    }
    return;
  }

  if ((cmd.charAt(0) == 'h' || cmd.charAt(0) == 'H') && cmd.length() > 1) {
    unsigned long interval = cmd.substring(1).toInt();
    if (interval >= 100 && interval <= 10000) {
      commandTimeoutMs = interval;
      Serial.print("Heartbeat timeout ms: ");
      Serial.println(commandTimeoutMs);
    } else {
      Serial.print("Ignored invalid heartbeat interval: ");
      Serial.println(cmd);
    }
    return;
  }

  if (cmd.length() != 1) {
    Serial.print("Unknown command: ");
    Serial.println(cmd);
    printHelp();
    return;
  }

  char c = cmd.charAt(0);
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
      softChassisCommand(CHASSIS_TEST_SPEED, 0, 0, "chassis forward", CHASSIS_TEST_MS);
      break;

    case 'x':
    case 'X':
      softChassisCommand(-CHASSIS_TEST_SPEED, 0, 0, "chassis backward", CHASSIS_TEST_MS);
      break;

    case 'g':
    case 'G':
      delayedGentleDemo();
      break;

    case 'z':
    case 'Z':
      softChassisCommand(0, 0, TURN_TEST_SPEED, "turn left", CHASSIS_TEST_MS);
      break;

    case 'c':
    case 'C':
      softChassisCommand(0, 0, -TURN_TEST_SPEED, "turn right", CHASSIS_TEST_MS);
      break;

    case 'h':
    case 'H':
      softChassisCommand(0, STRAFE_TEST_SPEED, 0, "strafe left", CHASSIS_TEST_MS);
      break;

    case 'l':
    case 'L':
      softChassisCommand(0, -STRAFE_TEST_SPEED, 0, "strafe right", CHASSIS_TEST_MS);
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

void readHostCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      processHostCommand(hostCommand);
      hostCommand = "";
      continue;
    }

    hostCommand += c;
    if (hostCommand.length() > 64) {
      Serial.println("Host command too long. Dropped.");
      hostCommand = "";
    }
  }
}

void applyWebCommand(char c) {
  switch (c) {
    case 'w':
    case 'W':
      setChassisCommand(CHASSIS_TEST_SPEED, 0, 0, 0, SOURCE_WEB);
      break;
    case 'x':
    case 'X':
      setChassisCommand(-CHASSIS_TEST_SPEED, 0, 0, 0, SOURCE_WEB);
      break;
    case 'z':
    case 'Z':
      setChassisCommand(0, 0, TURN_TEST_SPEED, 0, SOURCE_WEB);
      break;
    case 'c':
    case 'C':
      setChassisCommand(0, 0, -TURN_TEST_SPEED, 0, SOURCE_WEB);
      break;
    case 'h':
    case 'H':
      setChassisCommand(0, STRAFE_TEST_SPEED, 0, 0, SOURCE_WEB);
      break;
    case 'l':
    case 'L':
      setChassisCommand(0, -STRAFE_TEST_SPEED, 0, 0, SOURCE_WEB);
      break;
    case 's':
    case 'S':
    default:
      stopAllMotors();
      break;
  }
}

void handleRoot() {
  server.sendHeader("Cache-Control", "no-store");
  server.send_P(200, "text/html", INDEX_HTML);
}

void handleCommand() {
  if (!server.hasArg("c") || server.arg("c").length() == 0) {
    server.send(400, "text/plain", "missing command");
    return;
  }

  if (server.hasArg("q")) {
    unsigned long seq = server.arg("q").toInt();
    if (seq == 1) {
      lastWebSeq = 0;
    }
    if (seq > 0 && seq <= lastWebSeq) {
      server.sendHeader("Cache-Control", "no-store");
      server.send(200, "text/plain", "stale");
      return;
    }
    if (seq > 0) {
      lastWebSeq = seq;
    }
  }

  applyWebCommand(server.arg("c")[0]);
  server.sendHeader("Cache-Control", "no-store");
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "text/plain", "ok");
}

void setupWiFiRemote() {
  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
  WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASS, 6, 0, 1);
  dnsServer.start(DNS_PORT, "*", AP_IP);

  server.on("/", handleRoot);
  server.on("/cmd", handleCommand);
  server.onNotFound(handleRoot);
  server.begin();

  Serial.print("WiFi AP SSID: ");
  Serial.println(WIFI_AP_SSID);
  Serial.print("WiFi AP password: ");
  Serial.println(WIFI_AP_PASS);
  Serial.print("Phone URL: http://");
  Serial.println(WiFi.softAPIP());
}

void setup() {
  Serial.begin(115200);
  delay(500);

  MotorSerial.begin(MOTOR_BAUD, SERIAL_8N1, MOTOR_RX, MOTOR_TX);
  delay(500);

  printHelp();
  initAT8236();
  setupWiFiRemote();
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
  readMotorFrames();
  readHostCommands();
  updateControlLoop();
}
