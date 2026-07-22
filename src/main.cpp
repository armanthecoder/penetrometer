#include <Arduino.h>

#define LED_PIN 2   // change to 48 if GPIO2 doesn't blink

void setup() {
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_PIN, HIGH);
  delay(500);
  digitalWrite(LED_PIN, LOW);
  delay(500);
}
