#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include "bluetooth.h"
#include "SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h"

BLEServer *pServer = NULL;
BLECharacteristic *pTxCharacteristic;
int payload = 0;
float tt = 0.0;
String thing; 
int sendbuffer = 0;
bool deviceConnected = false;
bool oldDeviceConnected = false;
uint8_t txValue = 0;
int32_t zero = 0; //This is the zero offset, we cannot set this as a constant because it fluctuates slightly whenver the scale is used
float   cf = 0.04; //Calibration factor - we found that it was consistently 0.04, so we initialized it to facilitate data collection
NAU7802 myScale;
String data = "";

int32_t averageRaw() { //take the average of 32 samples
  int32_t sum = 0;
  for (int i = 0; i < 32; i++) {
    while (!myScale.available()) delayMicroseconds(100);
    sum += myScale.getReading();
  }
  return sum / 32;
}

#define SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" // UART service UUID
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

class MyServerCallbacks : public BLEServerCallbacks
{
    void onConnect(BLEServer *pServer)
    {
        deviceConnected = true;
    };
    void onDisconnect(BLEServer *pServer)
    {
        deviceConnected = false;
    }
};

class MyCallbacks : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *pCharacteristic)
    {
        std::string rxValue = pCharacteristic->getValue();
        char myArray[rxValue.size() + 1]; // as 1 char space for null is also required
        strcpy(myArray, rxValue.c_str());
        if (rxValue.length() > 0)
        {
            messageHandler(rxValue.c_str());
        }
    }
};

boolean setupBluetooth()
{
    // Create the BLE Device
    BLEDevice::init("TIP 1");

    // Create the BLE Server
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new MyServerCallbacks());

    // Create the BLE Service
    BLEService *pService = pServer->createService(SERVICE_UUID);

    // Create a BLE Characteristic
    pTxCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID_TX,
        BLECharacteristic::PROPERTY_NOTIFY);

    pTxCharacteristic->addDescriptor(new BLE2902());

    BLECharacteristic *pRxCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID_RX,
        BLECharacteristic::PROPERTY_WRITE);

    pRxCharacteristic->setCallbacks(new MyCallbacks());

    // Start the service
    pService->start();

    // Start advertising
    pServer->getAdvertising()->start();
    Serial.println("Waiting a client connection to notify...");

    return true;
}

void loopBluetooth()
{
    if (deviceConnected)
    {
        // case: device connected
        std::string value = std::to_string(txValue);
       // Serial.println(value.c_str());
       // pTxCharacteristic->setValue(value.c_str());
       // pTxCharacteristic->notify(); 
       // txValue++;
        delay(10); // bluetooth stack will go into congestion, if too many packets are sent
       // Serial.println("conn");
    }
    // disconnecting
    if (!deviceConnected && oldDeviceConnected)
    {
        // case: device disconnected
        delay(500);                  // give the bluetooth stack the chance to get things ready
        pServer->startAdvertising(); // restart advertising
        Serial.println("start advertising");
        oldDeviceConnected = deviceConnected;
    }
    // connecting
    if (deviceConnected && !oldDeviceConnected)
    {
        // do stuff here on first connect
        oldDeviceConnected = deviceConnected;
    }
    //delay(1000);
}

void sendMessage(String message)
{
    pTxCharacteristic->setValue(message.c_str());
    pTxCharacteristic->notify();
}

void messageHandler(String message)
{
    // ADD YOUR CODE HERE

    Serial.println(message);
    if (message == "stop") {
      sendbuffer = 1;
}
else if (message == "dumb") {
      sendbuffer = 0;
}
else if (message == "start") {
      sendbuffer = 2;
}
else if (message == "zero") {
      sendbuffer = 3;
}

}

char decToChar(byte i) {
  if (i < 10) return i + '0';
  if ((i >= 10) && (i < 36)) return i + 'a' - 10;
  if ((i >= 36) && (i <= 62))
    return i + 'A' - 36;
  else
    return i;
}


void setup() {
  // put your setup code here, to run once:
//Wire.setPins(4, 5);
Wire.begin();
  pinMode(2, INPUT);
  Serial.begin(115200);
  analogReadResolution(10); 
    if (myScale.begin() == false)
  {
    Serial.println("Scale not detected. Please check wiring.");
   while (1);
  }
  

  Serial.println("Scale detected!");

  myScale.setSampleRate(NAU7802_SPS_80);
  myScale.setGain(NAU7802_GAIN_128);
  myScale.calibrateAFE();
  
setupBluetooth();
  //delay(200);

   delay(500);
 

}



void loop() {

   float voltage = (analogRead(2));

 
  loopBluetooth();
if (sendbuffer == 1) {
             delay(500);
//             sendMessage(data);
       }

      else if (sendbuffer ==2) {
      //delay(100);
      data = "";
      float tt = 0.0;
      float start = millis(); //gets current time in milliseconds
      int32_t rawW;
    //  dataType = "getdata";
    int size = 0;
      while(1)
      {
        while (!myScale.available()) delayMicroseconds(10);
        
      rawW=(myScale.getReading() - zero)*cf;
      tt = (millis()-start)/1000; //find how much time has passed and convert into seconds
      data = String(tt, 1) + "," + String(rawW);
sendMessage(data);
      //delay(100);
      Serial.println("reading");
      if (sendbuffer !=2)
      { //Stop recording if any key is pressed
        sendbuffer = 0;
        Serial.println("stop");
        break;
      }
      }
  
        Serial.println(data);
      sendbuffer =0; //reset buffer
    }
        else if (sendbuffer == 3) {
        zero = averageRaw(); //Hold device in the air with tip pointed towards the ground, make sure tip is not touching anything
        Serial.println(zero);
      sendbuffer = 0; //reset buffer
    }
}











