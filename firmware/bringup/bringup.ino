// Robot bring-up test: IMU + both motors, driven from the Serial Monitor (115200, newline).
// Written at HackPrinceton, Nov 14 2026. No libraries needed.
//
// FRONT = the BATTERY side (changed Nov 14). Wiring:
//   Right wheel: driver board A  STEP=IO4  DIR=IO5   (forward = DIR HIGH, tested)
//   Left wheel:  driver board B  STEP=IO6  DIR=IO7   (forward = DIR LOW, tested)
//   IMU: pitch = tiltY, leaning toward the front = POSITIVE
//   EN=IO15 to both drivers (LOW = motors on)
//   MPU-6050: SDA=IO8  SCL=IO9  (I2C address 0x68)
//
// Commands (type the letter, press Enter):
//   i        IMU printout on/off (pitch, roll, gyro)
//   l / L    left wheel: 1 turn forward / backward
//   r / R    right wheel: 1 turn forward / backward
//   b / B    both wheels: 1 turn forward / backward
//   f / F    faster / slower (steps per second)
//   ?        help
// Motors are switched on only while they move, then switched off again.

#include <Wire.h>

const int STEP_R = 4, DIR_R = 5, STEP_L = 6, DIR_L = 7, EN = 15;
const int SDA_PIN = 8, SCL_PIN = 9;
const uint8_t MPU = 0x68;
const long STEPS_PER_REV = 200L * 16;   // 1/16 microstepping

long stepsPerSec = 1600;                // half a turn per second to start
bool imuOn = false;
bool imuOk = false;

void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU); Wire.write(reg); Wire.write(val); Wire.endTransmission();
}

bool mpuRead(uint8_t reg, uint8_t *buf, int n) {
  Wire.beginTransmission(MPU); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU, n) != n) return false;
  for (int i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

void help() {
  Serial.println();
  Serial.println("Commands: i = IMU on/off | l L r R b B = spin 1 turn | f F = faster/slower | ? = help");
  Serial.printf("Speed: %ld steps/s (%.2f turns/s)\n", stepsPerSec, stepsPerSec / (float)STEPS_PER_REV);
}

void spin(bool left, bool right, bool forward) {
  Serial.printf("Spinning %s%s%s %s...\n", left ? "LEFT" : "", (left && right) ? " + " : "",
                right ? "RIGHT" : "", forward ? "forward" : "backward");
  // Motors face outward, so "forward" is opposite DIR levels on the two sides.
  digitalWrite(DIR_R, forward ? HIGH : LOW);
  digitalWrite(DIR_L, forward ? LOW : HIGH);
  digitalWrite(EN, LOW);                 // motors on
  delay(20);
  long halfPeriod = 500000L / stepsPerSec;
  for (long i = 0; i < STEPS_PER_REV; i++) {
    if (left)  digitalWrite(STEP_L, HIGH);
    if (right) digitalWrite(STEP_R, HIGH);
    delayMicroseconds(halfPeriod);
    digitalWrite(STEP_L, LOW);
    digitalWrite(STEP_R, LOW);
    delayMicroseconds(halfPeriod);
  }
  delay(100);
  digitalWrite(EN, HIGH);                // motors off
  Serial.println("Done. Motors off.");
}

void setup() {
  pinMode(EN, OUTPUT); digitalWrite(EN, HIGH);   // motors OFF first thing
  pinMode(STEP_L, OUTPUT); pinMode(DIR_L, OUTPUT);
  pinMode(STEP_R, OUTPUT); pinMode(DIR_R, OUTPUT);
  digitalWrite(STEP_L, LOW); digitalWrite(STEP_R, LOW);

  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== Robot bring-up test ===");

  Wire.begin(SDA_PIN, SCL_PIN, 400000);
  uint8_t who = 0;
  imuOk = mpuRead(0x75, &who, 1);
  if (imuOk) {
    mpuWrite(0x6B, 0x00);   // wake up
    mpuWrite(0x1B, 0x08);   // gyro +-500 deg/s
    mpuWrite(0x1C, 0x00);   // accel +-2 g
    mpuWrite(0x1A, 0x03);   // ~44 Hz low-pass
    Serial.printf("IMU found. WHO_AM_I = 0x%02X (0x68 is a genuine MPU-6050; clones may differ, that's OK)\n", who);
  } else {
    Serial.println("IMU NOT FOUND. Check VCC->3.3V, GND->GND, SDA->IO8, SCL->IO9.");
  }
  help();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    switch (c) {
      case 'i': imuOn = !imuOn; Serial.printf("IMU printout %s\n", imuOn ? "ON" : "OFF"); break;
      case 'l': spin(true, false, true); break;
      case 'L': spin(true, false, false); break;
      case 'r': spin(false, true, true); break;
      case 'R': spin(false, true, false); break;
      case 'b': spin(true, true, true); break;
      case 'B': spin(true, true, false); break;
      case 'f': stepsPerSec = min(stepsPerSec * 2, 12800L); help(); break;
      case 'F': stepsPerSec = max(stepsPerSec / 2, 200L); help(); break;
      case '?': help(); break;
      default: break;   // ignore Enter and anything else
    }
  }

  static uint32_t last = 0;
  if (imuOn && millis() - last > 200) {
    last = millis();
    uint8_t b[14];
    if (!mpuRead(0x3B, b, 14)) { Serial.println("IMU read failed"); return; }
    int16_t ax = (b[0] << 8) | b[1], ay = (b[2] << 8) | b[3], az = (b[4] << 8) | b[5];
    int16_t gx = (b[8] << 8) | b[9], gy = (b[10] << 8) | b[11], gz = (b[12] << 8) | b[13];
    float angX = atan2f(ay, az) * 57.2958f;                       // tilt around the board's X axis
    float angY = atan2f(-ax, sqrtf((float)ay * ay + (float)az * az)) * 57.2958f;  // tilt around Y
    Serial.printf("tiltX %6.1f deg  tiltY %6.1f deg  | gyro x %6.1f  y %6.1f  z %6.1f deg/s\n",
                  angX, angY, gx / 65.5f, gy / 65.5f, gz / 65.5f);
  }
}
