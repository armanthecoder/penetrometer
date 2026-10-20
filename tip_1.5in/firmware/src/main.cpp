#include <Arduino.h>
#include <Wire.h>
#include <SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h>

#define AVG_SAMPLES 2

NAU7802 myScale;
bool    streaming = false;
float   calibrationFactor = -0.000929f;
int32_t zeroOffset        = -4399203;

int32_t averageRaw() {
  int32_t sum = 0;
  for (int i = 0; i < 32; i++) {
    while (!myScale.available()) delayMicroseconds(100);
    sum += myScale.getReading();
  }
  return sum / 32;
}

float readFloat() {
  char buf[16]; int idx = 0;
  memset(buf, 0, sizeof(buf));
  while (true) {
    if (Serial.available()) {
      char c = Serial.read();
      if ((c == '\n' || c == '\r') && idx > 0) { Serial.println(); break; }
      else if (idx < 15 && c != '\n' && c != '\r') { buf[idx++] = c; Serial.print(c); }
    }
    delay(1);
  }
  return atof(buf);
}

void setup() {
  Serial.begin(115200);
  delay(2000);                          // wait for USB serial to connect
  Serial.println("SETUP START");

  Wire.begin();
  Serial.println("I2C OK");

  if (!myScale.begin()) {
    Serial.println("ERROR: NAU7802 not found. Check wiring.");
    while (true) delay(100);
  }
  Serial.println("NAU7802 OK");

  myScale.setSampleRate(NAU7802_SPS_80);
  myScale.setGain(NAU7802_GAIN_128);
  myScale.calibrateAFE();

  for (int i = 0; i < 16; i++) {
    while (!myScale.available()) delay(1);
    myScale.getReading();
  }

  // Auto-tare on every boot so baseline is always 0
  zeroOffset = averageRaw();
  Serial.println("READY");
  Serial.println("C=calibrate  R=stream  X=stop");
}

void loop() {
  if (Serial.available()) {
    char cmd = toupper(Serial.read());

    if (cmd == 'C') {
      streaming = false;
      delay(100); while (Serial.available()) Serial.read();

      Serial.println("STEP 1: Remove all weight. Press Enter.");
      while (!Serial.available()) delay(10);
      while (Serial.available()) Serial.read();
      int32_t zero = averageRaw();
      myScale.setZeroOffset(zero);
      Serial.print("ZERO:"); Serial.println(zero);

      delay(100); while (Serial.available()) Serial.read();
      Serial.println("STEP 2: Place known weight. Press Enter.");
      while (!Serial.available()) delay(10);
      while (Serial.available()) Serial.read();

      Serial.print("Weight in kg: ");
      float kg  = readFloat();
      int32_t rawW = averageRaw();
      int32_t net  = rawW - zero;
      float   cf   = kg / (float)net;   // kg/count — Python applies this directly

      Serial.print("ZERO:"); Serial.println(zero);
      Serial.print("CAL_FACTOR:"); Serial.println(cf, 6);
      Serial.println("Done. R=stream  S=save");
    }

    else if (cmd == 'R') { streaming = true;  Serial.println("STREAMING"); }
    else if (cmd == 'X') { streaming = false; Serial.println("STOPPED"); }
  }

  if (!streaming) return;

  int32_t sum = 0;
  for (int i = 0; i < AVG_SAMPLES; i++) {
    while (!myScale.available()) delayMicroseconds(100);
    sum += myScale.getReading();
  }
  int32_t raw = sum / AVG_SAMPLES;

  // Send raw ADC — Python applies calibration
  Serial.print(millis());
  Serial.print(",");
  Serial.println(raw);

  delay(5);
}