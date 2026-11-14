// First balancing test. Written at HackPrinceton, Nov 14 2026 (overnight).
// FRONT = battery side. Right wheel = board A (IO4/IO5, fwd DIR HIGH), left wheel = board B (IO6/IO7, fwd DIR LOW).
// IMU MPU-6050 on IO8/IO9. Pitch = tiltY, leaning toward the front = positive. EN = IO15 (LOW = on).
//
// Control: the steppers are told an ACCELERATION (state feedback, gains from an LQR design on the CAD
// mass properties, checked in simulation for pendulum lengths 0.2-0.35 m):
//   a = KX*(x-xt) + KV*(v-vt) + KT*(pitch - trim) + KW*pitchRate + KI*integral(x-xt)   [m/s^2]
//   The KI term (added Nov 14) keeps pushing until the robot reaches its target, so a steady pull or drag
//   can't leave it parked leaning, short of where it was told to go.
// Wheel speed = integral of a. Steps come from a 40 kHz hardware-timer interrupt.
//
// Serial commands (115200):
//   g = arm: starts balancing if held within 6 deg of upright; stops by itself after RUN_MS
//   x = stop now             z = set trim to the current pitch (hold it at its balance point first)
//   i = telemetry on/off     p = print gains
//   q/a = KT up/down 10%     w/s = KW up/down 10%     e/d = KV up/down 10%     r/f = KX up/down 10%
//   t/y = trim +/- 0.25 deg     u/j = KI up/down 10%
//   n/m = rolling-resistance lean feedforward +/- 0.25 deg (lean it adds while driving)
//   L / R = turn exactly 90 deg left / right, closed loop on the IMU's yaw gyro (slip-proof)
//   G = stand up by itself from the kickstand (target angle swings from the kickstand angle to trim in 0.4 s;
//       it rolls ~45 cm toward the battery side while doing it)
//   P = park: lean gently back onto the kickstand, then motors off
//   F / B = drive exactly MOVE_DIST forward / back on a braking profile, then report "move done" with the error
//   v = flip the yaw gyro sign (only if L/R turn the wrong way)
//   k = (not balancing) lock the wheels with motor holding torque, no balancing: floor-grip test. k again = release
//   h = fast log on/off: 50 Hz CSV  t_ms,pitch,accAngleRaw,gyro,v,x,xt,a,Iterm,ffLean,yaw  (replaces the 10 Hz telemetry)
// Driving feedforward (added Nov 14): while a speed is commanded the target angle moves by
//   atan(target accel / g) + FF_RR * (direction of travel), so it leans and goes at once instead of lagging 1.5-3 s.
//   c = recalibrate gyro (robot must be STILL for 2 s)
//   Driving while balancing: 8/2 = speed +/- 0.1 m/s (max 0.3), 4/6 = turn left/right +/- 0.5 rad/s (max 1.5), 5 = stop and hold here
// Safety: motors off at boot, off when |pitch - trim| > 30 deg, off after RUN_MS.

#include <Wire.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#if __has_include("secrets.h")      // WIFI_SSID / WIFI_PASS: copy secrets.example.h to secrets.h (git-ignored)
#include "secrets.h"
#else                              // no secrets.h: Wi-Fi stays off, USB control still works
#define WIFI_SSID "YOUR_HOTSPOT_NAME"
#define WIFI_PASS ""
#endif

// ---------- Wi-Fi control (team contract): UDP port 4210, newline-free JSON packets
//   laptop -> robot: {"t":"cmd","v":0.3,"w":0.0,"mode":"drive"}   v m/s (max 0.3), w rad/s left + (max 1.5)
//                    mode: drive | balance (hold here) | idle (motors off). Arming is only by the plain packet "g".
//   any packet not starting with '{' is treated as the same one-letter commands as the serial port (g, x, L, R, ...)
//   robot -> laptop (20 Hz, to whoever sent the last packet):
//     {"t":"tel","pitch":..,"rate":..,"vl":..,"vr":..,"batt":null,"state":"idle|balance|drive","fault":null,"x":..,"yaw":..}
//   Safety: drive commands older than 300 ms -> speed and turn go to 0 and it holds position.
const uint16_t UDP_PORT = 4210;
WiFiUDP udp;
IPAddress peerIP; uint16_t peerPort = 0; bool havePeer = false, wifiUp = false, netDriving = false;
uint32_t lastNetCmd = 0;
const char *lastFault = nullptr;

const int STEP_R = 4, DIR_R = 5, STEP_L = 6, DIR_L = 7, EN = 15;
const uint8_t MPU = 0x68;
const float STEPS_PER_M = 3200.0f / (PI * 0.085f);   // 11983
const float DT = 0.005f;                               // 200 Hz control loop
const float VMAX = 1.0f, AMAX = 6.0f;                  // m/s, m/s^2 (VMAX was 0.8; raised with faster driving, check with T)
const uint32_t RUN_MS = 300000;                        // each g balances for at most 5 min (tilt cutoff and Wi-Fi watchdog still apply)
const float HALF_TRACK = 0.0775f;                      // wheel centre to robot centre, m (CAD)
const uint32_t ISR_HZ = 40000;

float KT = 0.443f;             // m/s^2 per degree. Was 0.785; softer to tolerate ~30-50 ms motor lag (Nov 14)
float KW = 0.072f;             // m/s^2 per deg/s. 0.054 without the phone; 0.072 with the phone on top (Nov 14)
float KV = 3.0f;               // m/s^2 per m/s
float KX = 2.0f;               // m/s^2 per m
float KI = 0.77f;              // m/s^2 per (m*s); clamped to +/- I_LIM. 1.5 caused a slow +/-20 cm swing (Nov 14)
const float I_LIM = 1.0f;      // m/s^2, about 2.3 deg of lean (was 1.5: wound up and lurched)
const float VT_ACC = 0.5f;     // m/s^2: drive commands ramp the target speed this fast (was 0.4)
float FF_CREEP = 0.6f;         // deg toward the target when >3 cm off while holding. 1.75 without the phone; with it, that rocked at 0.45 Hz
float FF_RR = 0.5f;            // deg of extra lean while moving (rolling resistance). 1.25 without the phone
float trim = -1.25f;           // deg. With the phone: stands still at -1.25 with wheels locked (was +0.5 without it), Nov 14

// ---------- step generation (DDS in a timer interrupt)
volatile uint32_t incR = 0, incL = 0;      // phase increment per tick (0 = stopped)
volatile int32_t posR = 0, posL = 0;       // steps, forward positive
volatile int8_t sgnR = 1, sgnL = 1;
hw_timer_t *tmr = nullptr;

void IRAM_ATTR onTimer() {
  static uint32_t phR = 0, phL = 0;
  digitalWrite(STEP_R, LOW);
  digitalWrite(STEP_L, LOW);
  uint32_t o = phR; phR += incR;
  if (phR < o) { digitalWrite(STEP_R, HIGH); posR += sgnR; }
  o = phL; phL += incL;
  if (phL < o) { digitalWrite(STEP_L, HIGH); posL += sgnL; }
}

void setWheelSpeed(float vR, float vL) {               // m/s, forward positive
  float sR = vR * STEPS_PER_M, sL = vL * STEPS_PER_M;
  int8_t nR = sR >= 0 ? 1 : -1, nL = sL >= 0 ? 1 : -1;
  digitalWrite(DIR_R, nR > 0 ? HIGH : LOW);             // right: forward = HIGH
  digitalWrite(DIR_L, nL > 0 ? LOW : HIGH);             // left:  forward = LOW
  uint32_t iR = (uint32_t)(fabsf(sR) * (4294967296.0f / ISR_HZ));
  uint32_t iL = (uint32_t)(fabsf(sL) * (4294967296.0f / ISR_HZ));
  noInterrupts(); sgnR = nR; sgnL = nL; incR = iR; incL = iL; interrupts();
}

// ---------- IMU
bool mpuRead(uint8_t reg, uint8_t *buf, int n) {
  Wire.beginTransmission(MPU); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU, n) != n) return false;
  for (int i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}
void mpuWrite(uint8_t reg, uint8_t val) { Wire.beginTransmission(MPU); Wire.write(reg); Wire.write(val); Wire.endTransmission(); }

float gyroBias = 0;     // deg/s, gyro Y
float gyroBiasZ = 0, yawRateRaw = 0;   // deg/s, gyro Z (yaw), bias removed
float accNormG = 1.0f;                 // total acceleration in g; ~1 when the accelerometer only sees gravity
bool readPitch(float &accPitch, float &rate) {
  uint8_t b[14];
  if (!mpuRead(0x3B, b, 14)) return false;
  int16_t ax = (b[0] << 8) | b[1], ay = (b[2] << 8) | b[3], az = (b[4] << 8) | b[5];
  int16_t gy = (b[10] << 8) | b[11];
  int16_t gz = (b[12] << 8) | b[13];
  yawRateRaw = gz / 65.5f - gyroBiasZ;
  accPitch = atan2f(-ax, sqrtf((float)ay * ay + (float)az * az)) * 57.2958f;   // tiltY, forward = +
  accNormG = sqrtf((float)ax * ax + (float)ay * ay + (float)az * az) / 8192.0f; // +-4 g range: 8192 LSB/g
  rate = gy / 65.5f - gyroBias;                                                 // same sign as tiltY
  return true;
}

// ---------- state
float vt = 0, wt = 0, xt = 0;   // drive targets: speed m/s, turn rad/s (left +), target position m
float vtr = 0;                  // ramped target speed actually used
float ffLean = 0;               // feedforward lean, deg (low-passed)
bool hold = false;
float YAW_SIGN = 1.0f;          // +1 if gyro Z reads positive for a LEFT turn
float yaw = 0, turnTarget = 0;  // deg, left positive
bool turning = false;
bool standGuard = false;        // true for 2.5 s after a G stand-up starts
int rampMode = 0;               // 0 none, 1 standing up, 2 parking
float rampFrom = 0, rampTo = 0, rampDur = 0.4f, trimEff = 0;
uint32_t rampStart = 0;
const float KICKSTAND_MIN = 5.0f, KICKSTAND_MAX = 16.0f;   // pitch range that means 'resting on the kickstand' (reads ~10.8-13)
float kickAngle = 11.0f;        // measured at each stand-up (G)
uint32_t parkLockTime = 0;      // wheels held locked after parking, released 1.5 s later
const float MOVE_DIST = 0.5f;   // m for F / B
float MOVE_V = 0.2f;            // m/s for F / B; > / < change it by 0.05 (0.1-0.5)
float headingTarget = 0;        // deg; held with the yaw gyro during F / B
int moving = 0;                 // 0 none, 1 cruising, 2 braking/settling
float moveTarget = 0; uint32_t moveStart = 0, settleStart = 0;
uint32_t turnStart = 0;
float pitch = 0, rate = 0, vcmd = 0, xpos = 0, aApplied = 0;   // aApplied: last wheel acceleration, m/s^2
float Ix = 0, lastA = 0, lastAp = 0;
bool running = false, telem = true, hlog = false;
uint32_t runStart = 0;

void motorsOff(const char *why) {
  setWheelSpeed(0, 0);
  aApplied = 0; vcmd = 0;
  digitalWrite(EN, HIGH);
  if (running) { Serial.printf("STOP: %s\n", why); lastFault = why; }
  netDriving = false;
  moving = 0; turning = false; rampMode = 0;
  running = false;
}

void printGains() {
  Serial.printf("KT %.3f/deg  KW %.3f/(deg/s)  KV %.2f  KX %.2f  KI %.2f  trim %.2f deg  FF_RR %.2f deg  FF_CREEP %.2f deg\n", KT, KW, KV, KX, KI, trim, FF_RR, FF_CREEP);
}

void calibrate() {
  Serial.println("Calibrating gyro: keep the robot STILL for 2 s...");
  gyroBias = 0; gyroBiasZ = 0;
  float sum = 0, sumZ = 0; int n = 0; float ap, r;
  for (int i = 0; i < 400; i++) { if (readPitch(ap, r)) { sum += r; sumZ += yawRateRaw; n++; } delay(5); }
  gyroBias = n ? sum / n : 0;
  gyroBiasZ = n ? sumZ / n : 0;
  readPitch(ap, r); pitch = ap;
  Serial.printf("Gyro bias %.2f deg/s (yaw %.2f). Pitch now %.1f deg.\n", gyroBias, gyroBiasZ, pitch);
}

void setup() {
  pinMode(EN, OUTPUT); digitalWrite(EN, HIGH);          // motors OFF first
  pinMode(STEP_R, OUTPUT); pinMode(DIR_R, OUTPUT);
  pinMode(STEP_L, OUTPUT); pinMode(DIR_L, OUTPUT);
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Balance test ===");
  Wire.begin(8, 9, 400000);
  mpuWrite(0x6B, 0x00); mpuWrite(0x1B, 0x08); mpuWrite(0x1C, 0x08); mpuWrite(0x1A, 0x03);
  delay(100);

  calibrate();

  tmr = timerBegin(1000000);                            // 1 MHz tick
  timerAttachInterrupt(tmr, &onTimer);
  timerAlarm(tmr, 1000000 / ISR_HZ, true, 0);           // every 25 us
  printGains();
  if (strcmp(WIFI_SSID, "YOUR_HOTSPOT_NAME") != 0) { WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.begin(WIFI_SSID, WIFI_PASS); Serial.printf("Joining Wi-Fi '%s'...\n", WIFI_SSID); }
  else Serial.println("Wi-Fi not set up (edit secrets.h).");
  Serial.println("Ready. Hold it upright, then send g.");
}

void handleChar(char c) {
    switch (c) {
      case 'g':
        if (fabsf(pitch - trim) > 6) { Serial.printf("Not upright (pitch-trim = %.1f). Hold it upright first.\n", pitch - trim); break; }
        rampMode = 0; lastFault = nullptr; hold = false; vcmd = 0; xpos = 0; aApplied = 0; Ix = 0; vt = wt = xt = vtr = 0; ffLean = 0; yaw = 0; turning = false; noInterrupts(); posR = posL = 0; interrupts();
        digitalWrite(EN, LOW); running = true; runStart = millis();
        Serial.printf("BALANCING (%lu s max)\n", (unsigned long)(RUN_MS / 1000)); break;
      case '8': vt = constrain(vt + 0.1f, -0.5f, 0.5f); Serial.printf("drive v %.1f w %.1f\n", vt, wt); break;
      case '2': vt = constrain(vt - 0.1f, -0.5f, 0.5f); Serial.printf("drive v %.1f w %.1f\n", vt, wt); break;
      case '4': wt = constrain(wt + 0.5f, -1.5f, 1.5f); Serial.printf("drive v %.1f w %.1f\n", vt, wt); break;
      case '6': wt = constrain(wt - 0.5f, -1.5f, 1.5f); Serial.printf("drive v %.1f w %.1f\n", vt, wt); break;
      case '5': vt = 0; wt = 0; turning = false; moving = 0; Serial.println("drive stop: ramping down, then holding"); break;
      case 'L': turnTarget = roundf(yaw / 90.0f) * 90.0f + 90; turning = true; turnStart = millis(); Serial.printf("turn LEFT 90: yaw %.1f -> %.1f\n", yaw, turnTarget); break;
      case 'R': turnTarget = roundf(yaw / 90.0f) * 90.0f - 90; turning = true; turnStart = millis(); Serial.printf("turn RIGHT 90: yaw %.1f -> %.1f\n", yaw, turnTarget); break;
      case 'G':
        if (running) break;
        if (pitch < KICKSTAND_MIN || pitch > KICKSTAND_MAX) { Serial.printf("Not on the kickstand (pitch %.1f). Use g if you are holding it upright.\n", pitch); break; }
        rampMode = 0; lastFault = nullptr; hold = false; vcmd = 0; xpos = 0; aApplied = 0; Ix = 0; vt = wt = xt = vtr = 0; ffLean = 0; yaw = 0; turning = false;
        noInterrupts(); posR = posL = 0; interrupts();
        kickAngle = pitch; parkLockTime = 0;
        rampMode = 1; rampFrom = pitch; rampTo = trim; rampDur = 0.4f; rampStart = millis(); standGuard = true;
        digitalWrite(EN, LOW); running = true; runStart = millis();
        Serial.printf("STANDING UP from %.1f deg\n", pitch); break;
      case 'P':
        if (!running) break;
        vt = 0; wt = 0; turning = false;
        rampMode = 2; rampFrom = trimEff; rampTo = kickAngle + 1.0f; rampDur = 1.0f; rampStart = millis();
        Serial.println("PARKING on the kickstand"); break;
      case 'F': case 'B':
        if (!running || rampMode) break;
        moveTarget = xt + (c == 'F' ? MOVE_DIST : -MOVE_DIST); vt = (c == 'F' ? MOVE_V : -MOVE_V); wt = 0; turning = false;
        moving = 1; moveStart = millis(); headingTarget = roundf(yaw / 90.0f) * 90.0f;
        Serial.printf("move %s %.2f m: target %.3f\n", c == 'F' ? "forward" : "back", MOVE_DIST, moveTarget); break;
      case 'V': Serial.println("FW balance json-serial v1"); break;
      case 'T':                                    // wheel top-speed test: HOLD THE ROBOT UP, wheels off the ground
        if (running) break;
        Serial.println("SPIN TEST: wheels to 1.0 m/s and back (robot must be held up)");
        digitalWrite(EN, LOW); delay(50);
        for (int i = 0; i <= 100; i++) { setWheelSpeed(i * 0.01f, i * 0.01f); if (i % 20 == 0) Serial.printf("  %.1f m/s\n", i * 0.01f); delay(20); }
        delay(1000);
        for (int i = 100; i >= 0; i--) { setWheelSpeed(i * 0.01f, i * 0.01f); delay(20); }
        setWheelSpeed(0, 0); digitalWrite(EN, HIGH); Serial.println("SPIN TEST done"); break;
      case '>': MOVE_V = min(MOVE_V + 0.05f, 0.5f); Serial.printf("move speed %.2f m/s\n", MOVE_V); break;
      case '<': MOVE_V = max(MOVE_V - 0.05f, 0.1f); Serial.printf("move speed %.2f m/s\n", MOVE_V); break;
      case 'v': YAW_SIGN = -YAW_SIGN; Serial.printf("yaw sign now %+.0f\n", YAW_SIGN); break;   // vtr ramps to 0, xt follows it
      case 'k': if (!running) { hold = !hold; setWheelSpeed(0, 0); digitalWrite(EN, hold ? LOW : HIGH);
                  Serial.println(hold ? "WHEELS LOCKED (no balancing)" : "wheels released"); } break;
      case 'x': motorsOff("stop command"); break;
      case 'c': if (!running) calibrate(); break;
      case 'z': trim = pitch; Serial.printf("Trim set to %.2f\n", trim); break;
      case 'i': telem = !telem; break;
      case 'h': hlog = !hlog; if (hlog) Serial.println("t_ms,pitch,accRaw,gyro,v,x,xt,a,Iterm"); break;
      case 'N': FF_CREEP += 0.1f; printGains(); break;  case 'M': FF_CREEP = max(0.0f, FF_CREEP - 0.1f); printGains(); break;
      case 'n': FF_RR += 0.25f; printGains(); break;  case 'm': FF_RR = max(0.0f, FF_RR - 0.25f); printGains(); break;
      case 'u': KI *= 1.1f; printGains(); break;   case 'j': KI /= 1.1f; printGains(); break;
      case 'p': printGains(); break;
      case 'q': KT *= 1.1f; printGains(); break;   case 'a': KT /= 1.1f; printGains(); break;
      case 'w': KW *= 1.1f; printGains(); break;   case 's': KW /= 1.1f; printGains(); break;
      case 'e': KV *= 1.1f; printGains(); break;   case 'd': KV /= 1.1f; printGains(); break;
      case 'r': KX *= 1.1f; printGains(); break;   case 'f': KX /= 1.1f; printGains(); break;
      case 't': trim += 0.25f; printGains(); break; case 'y': trim -= 0.25f; printGains(); break;
      default: break;
    }
}

void handleJson(const char *js);
void handleSerial() {                 // '{...}' = JSON drive command (same as Wi-Fi), anything else = one-letter commands
  static char jbuf[160]; static int jlen = -1;
  while (Serial.available()) {
    char c = Serial.read();
    if (jlen >= 0) {
      if (jlen < (int)sizeof(jbuf) - 1) jbuf[jlen++] = c;
      if (c == '}') { jbuf[jlen] = 0; handleJson(jbuf); jlen = -1; }
      else if (c == '\n' || jlen >= (int)sizeof(jbuf) - 1) jlen = -1;   // broken packet: drop it
    } else if (c == '{') { jbuf[0] = c; jlen = 1; }
    else handleChar(c);
  }
}

float jsonNum(const char *js, const char *key, float dflt) {
  const char *p = strstr(js, key); if (!p) return dflt;
  p = strchr(p + strlen(key), ':'); if (!p) return dflt;
  return atof(p + 1);
}

void handleJson(const char *js) {
  const char *m = strstr(js, "\"mode\"");
  char mode[12] = "drive";
  if (m) { m = strchr(m + 6, '"'); if (m) { int i = 0; m++; while (*m && *m != '"' && i < 11) mode[i++] = *m++; mode[i] = 0; } }
  if (!strcmp(mode, "idle")) { motorsOff("idle command (Wi-Fi)"); return; }
  if (!running) return;                                  // arming is only by an explicit "g"
  if (!strcmp(mode, "balance")) { vt = 0; wt = 0; turning = false; netDriving = true; lastNetCmd = millis(); return; }
  if (!strcmp(mode, "drive")) {
    float v = constrain(jsonNum(js, "\"v\"", 0), -0.6f, 0.6f), w = constrain(jsonNum(js, "\"w\"", 0), -1.5f, 1.5f);
    if (fabsf(v) > 0.001f || fabsf(w) > 0.001f) { moving = 0; turning = false; vt = v; wt = w; }
    else if (!moving && !turning) { vt = 0; wt = 0; }
    netDriving = true; lastNetCmd = millis();
  }
}

void handleNet() {
  static uint32_t lastCheck = 0;
  if (!wifiUp && millis() - lastCheck > 500) {
    lastCheck = millis();
    if (WiFi.status() == WL_CONNECTED) {
      wifiUp = true; udp.begin(UDP_PORT); MDNS.begin("balancebot");
      Serial.printf("Wi-Fi up: %s  (balancebot.local), UDP port %u\n", WiFi.localIP().toString().c_str(), UDP_PORT);
    }
  }
  if (netDriving && millis() - lastNetCmd > 300) {      // watchdog: works for USB and Wi-Fi drive commands
    if (!moving && !turning) { vt = 0; wt = 0; }
    netDriving = false; Serial.println("drive commands stopped: holding position");
  }
  if (!wifiUp) return;
  int n = udp.parsePacket();
  if (n > 0) {
    char buf[160]; int len = udp.read(buf, sizeof(buf) - 1); if (len < 0) len = 0; buf[len] = 0;
    peerIP = udp.remoteIP(); peerPort = udp.remotePort(); havePeer = true;
    if (buf[0] == '{') handleJson(buf); else for (int i = 0; i < len; i++) handleChar(buf[i]);
  }
}

void sendTelemetry() {
  if (!wifiUp || !havePeer) return;
  char out[220];
  const char *state = !running ? "idle" : ((vt != 0 || wt != 0 || turning) ? "drive" : "balance");
  char fault[48]; if (lastFault) snprintf(fault, sizeof(fault), "\"%s\"", lastFault); else strcpy(fault, "null");
  snprintf(out, sizeof(out), "{\"t\":\"tel\",\"pitch\":%.2f,\"rate\":%.1f,\"vl\":%.3f,\"vr\":%.3f,\"batt\":null,\"state\":\"%s\",\"fault\":%s,\"x\":%.3f,\"yaw\":%.1f}",
           pitch, rate, vcmd - wt * HALF_TRACK, vcmd + wt * HALF_TRACK, state, fault, xpos, yaw);
  udp.beginPacket(peerIP, peerPort); udp.print(out); udp.endPacket();
}

void loop() {
  static uint32_t next = micros();
  handleSerial();
  handleNet();
  if ((int32_t)(micros() - next) < 0) return;
  next += (uint32_t)(DT * 1e6f);

  float ap, r;
  if (!readPitch(ap, r)) { motorsOff("IMU read failed"); return; }
  // Forward wheel acceleration makes the accelerometer read a backward lean of a/g rad, so add it back.
  float apc = ap + aApplied * (57.2958f / 9.81f);
  // Only let the accelerometer correct drift when it is believable: not standing up, not accelerating hard,
  // not rotating fast, and reading ~1 g (shaking or saturation make it wild). Otherwise gyro only.
  float wAcc = 0.01f;
  if (rampMode == 1 || fabsf(aApplied) > 1.5f || fabsf(r) > 30.0f || fabsf(accNormG - 1.0f) > 0.25f) wAcc = 0.0f;
  pitch = (1.0f - wAcc) * (pitch + r * DT) + wAcc * apc;   // complementary filter
  rate = r;
  lastAp = ap;
  float yawRate = YAW_SIGN * yawRateRaw;                // deg/s, left positive
  if (running) yaw += yawRate * DT;
  if (running && moving && !turning) wt = constrain(0.035f * (headingTarget - yaw), -0.5f, 0.5f);   // drive straight on the gyro
  if (running && turning) {                             // closed-loop 90 deg turns on the yaw gyro
    float e = turnTarget - yaw;
    float w = constrain(0.035f * e, -1.0f, 1.0f);         // rad/s
    if (fabsf(e) > 3 && fabsf(w) < 0.3f) w = (e > 0 ? 0.3f : -0.3f);
    wt = w;
    if (fabsf(e) < 1.0f && fabsf(yawRate) < 10) { turning = false; wt = 0; Serial.printf("turn done, yaw %.1f\n", yaw); }
    else if (millis() - turnStart > 8000) { turning = false; wt = 0; Serial.printf("turn TIMEOUT, yaw %.1f (wrong yaw sign? send v)\n", yaw); }
  }

  if (rampMode) {
    float f = min(1.0f, (millis() - rampStart) / (rampDur * 1000.0f));
    f = 0.5f - 0.5f * cosf(PI * f);
    trimEff = rampFrom + (rampTo - rampFrom) * f;
    if (rampMode == 1 && f >= 1.0f) { rampMode = 0; xt = xpos; Ix = 0; Serial.println("standing"); }   // hold where it ended up
    if (rampMode == 1 && pitch > kickAngle + 4.0f) { rampMode = 0; motorsOff("stand-up: tipping forward instead of lifting"); }
    if (rampMode == 1 && millis() - rampStart > 1200 && pitch > KICKSTAND_MIN) { rampMode = 0; motorsOff("stand-up failed (still on kickstand after 1.2 s)"); }
    if (rampMode == 2 && (pitch > kickAngle - 4.0f || fabsf(vcmd) > 0.25f || millis() - rampStart > 1500)) {
      // leaning well over (or picking up speed): lock the wheels so it can only tip onto the kickstand, no rolling away or bounce
      rampMode = 0; setWheelSpeed(0, 0); vcmd = 0; aApplied = 0; running = false; hold = true; parkLockTime = millis();
      Serial.println("parked: wheels locked");
    }
  } else trimEff = trim;
  // Stand-up safety net for the first 2.5 s (checked every loop, not just when the ramp ends):
  if (running && standGuard && millis() - rampStart < 2500 && (fabsf(vcmd) > 0.7f || pitch - trim < -12.0f || pitch > kickAngle + 4.0f)) {
    standGuard = false; motorsOff("stand-up recovery failed (too fast or too far over)");
  }
  if (standGuard && millis() - rampStart >= 2500) standGuard = false;
  if (parkLockTime && millis() - parkLockTime > 1500) {
    parkLockTime = 0; hold = false; digitalWrite(EN, HIGH); Serial.println("parked: motors released");
  }

  if (running) {
    float err = pitch - trimEff - ffLean;
    if (fabsf(pitch - trim) > 30) { motorsOff("fell over (tilt > 30 deg)"); }
    else if (millis() - runStart > RUN_MS) { motorsOff("run time limit reached"); }
    else {
      noInterrupts(); int32_t pR = posR, pL = posL; interrupts();
      xpos = 0.5f * (pR + pL) / STEPS_PER_M;
      float dv = constrain(vt - vtr, -VT_ACC * DT, VT_ACC * DT);
      vtr += dv;
      if (moving == 1 && fabsf(moveTarget - xt) <= vtr * vtr / (2 * VT_ACC) + 0.002f) { vt = 0; moving = 2; }   // start braking so xt lands on the target
      if (moving == 2 && vtr == 0) { if (xt != moveTarget) settleStart = millis(); xt = moveTarget; }
      if (moving == 2 && vtr == 0 && millis() - settleStart > 1500) { moving = 0; wt = 0; Serial.printf("move done (settle limit), error %+.3f m\n", xpos - moveTarget); }
      if (moving == 2 && vtr == 0 && fabsf(xpos - moveTarget) < 0.04f && fabsf(vcmd) < 0.05f) { moving = 0; wt = 0; Serial.printf("move done, error %+.3f m\n", xpos - moveTarget); }
      if (moving && millis() - moveStart > 8000) { moving = 0; vt = 0; wt = 0; Serial.printf("move TIMEOUT, error %+.3f m\n", xpos - moveTarget); }
      float ffTarget = atanf((dv / DT) / 9.81f) * 57.2958f + FF_RR * constrain(vtr / 0.05f, -1.0f, 1.0f);
      // Friction compensation while holding: >3 cm off target -> lean FF_RR toward it until within 1 cm
      // (otherwise it can sit in the rolling-resistance sticky zone, 'balanced' but short of the target).
      static bool creep = false;
      float pe = xt - xpos;
      bool holdingNow = (vt == 0 && fabsf(vtr) < 1e-4f && rampMode == 0 && !turning);
      if (!holdingNow) creep = false;
      else if (!creep && fabsf(pe) > 0.03f) creep = true;
      else if (creep && fabsf(pe) < 0.02f) creep = false;
      if (creep) ffTarget += (pe > 0 ? FF_CREEP : -FF_CREEP);
      ffLean += (ffTarget - ffLean) * (DT / 0.15f);      // smooth it (0.15 s)
      xt += vtr * DT;
      if (vt == 0 && fabsf(vtr) < 1e-4f && rampMode == 0)  // integrate only while holding still: not driving, braking, standing up or parking
        Ix = constrain(Ix + (xpos - xt) * DT, -I_LIM / KI, I_LIM / KI);
      float a = KX * (xpos - xt) + KV * (vcmd - vtr) + KT * err + KW * rate + KI * Ix;
      a = constrain(a, -AMAX, AMAX);   // (a 3 m/s^2 stand-up cap was tried Nov 14: too slow, it then hit the speed cap and fell)
      lastA = a;
      float vNew = constrain(vcmd + a * DT, -VMAX, VMAX);
      aApplied = (vNew - vcmd) / DT;
      vcmd = vNew;
      setWheelSpeed(vcmd + wt * HALF_TRACK, vcmd - wt * HALF_TRACK);   // left turn = right wheel faster
    }
  }

  static uint8_t tdiv = 0;
  if (++tdiv >= 10) { tdiv = 0; sendTelemetry(); }   // 20 Hz
  static uint8_t hdiv = 0;
  if (hlog && ++hdiv >= 4) {                           // 50 Hz
    hdiv = 0;
    Serial.printf("%lu,%.2f,%.2f,%.1f,%.3f,%.3f,%.3f,%.2f,%.2f,%.2f,%.1f\n", (unsigned long)millis(), pitch, lastAp, rate,
                  vcmd, xpos, xt, running ? lastA : 0.0f, running ? KI * Ix : 0.0f, ffLean, yaw);
  }
  static uint32_t lastT = 0;
  if (telem && !hlog && millis() - lastT > 100) {
    lastT = millis();
    Serial.printf("%s pitch %6.2f (err %6.2f) rate %7.1f  v %5.2f  x %5.2f  vt %4.1f wt %4.1f\n",
                  running ? "RUN" : "off", pitch, pitch - trim, rate, vcmd, xpos, vt, wt);
  }
}
