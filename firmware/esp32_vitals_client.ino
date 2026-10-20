/*
  firmware/esp32_vitals_client.ino
  ---------------------------------
  Example firmware for an ESP32 (or any WiFi-capable board: e.g. an
  Arduino with an ESP8266/ESP32 WiFi shield) acting as the LIVE vitals
  source for the Smart Health Monitor dashboard.

  Sensors assumed (swap for whatever you actually have wired up):
    - MAX30102          -> heart rate (HR) + blood oxygen (SpO2)
    - DS18B20 / MLX90614 -> body temperature
    - MPU6050 (accelerometer) -> movement magnitude, 0.0-1.0

  What this sketch does, every READ_INTERVAL_MS:
    1. Reads the three sensors (replace the placeholder read*() functions
       with your actual sensor library calls).
    2. POSTs a JSON payload to the Flask backend's /api/vitals endpoint,
       tagged source="live_device" with this board's DEVICE_ID.
    3. As soon as the backend receives this POST, the Streamlit dashboard
       (which polls /api/live_status) will automatically switch from the
       default clinical-dataset demo view to this board's LIVE feed.
    4. If this board stops sending for LIVE_TIMEOUT_SECONDS (20s by default;
       an env var on the backend), the dashboard reverts to the demo view on its
       own -- no action needed here.

  Wiring / library notes are intentionally left as comments since exact
  pins depend on your board revision.
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// -- Configure for your network and backend server --------------------------
const char* WIFI_SSID      = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD  = "YOUR_WIFI_PASSWORD";
// Local backend on your LAN:   "http://192.168.1.50:5000/api/vitals"
// Deployed (cloud) backend:     "https://your-backend.onrender.com/api/vitals"
const char* BACKEND_URL    = "http://192.168.1.50:5000/api/vitals";
// Must match the backend's API_KEY environment variable. Leave "" if the
// backend has no API_KEY set (local development).
const char* API_KEY        = "";
const int   PATIENT_ID     = 1;              // must already exist -- see /api/patient
const char* DEVICE_ID      = "ESP32-WARD3-01";
const unsigned long READ_INTERVAL_MS = 3000;  // send a reading every 3s

unsigned long lastRead = 0;

void setup() {
  Serial.begin(115200);

  // -- Sensor init (replace with real library calls) --------------------------
  // max30102.begin();
  // tempSensor.begin();
  // mpu6050.begin();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println("\nConnected. IP: " + WiFi.localIP().toString());
}

// -- Replace these with real sensor reads ------------------------------------
float readHeartRate()   { return 78.0 + random(-30, 300) / 10.0; }   // bpm, placeholder
float readSpO2()        { return 97.0 + random(-30, 30) / 10.0;  }   // %, placeholder
float readTemperature() { return 36.9 + random(-10, 40) / 100.0; }   // degC, placeholder
float readMovement()    { return random(0, 100) / 100.0;         }   // 0.0-1.0, placeholder

void sendReading(float hr, float spo2, float temp, float movement) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected, skipping this reading.");
    return;
  }

  HTTPClient http;
  WiFiClient plainClient;
  WiFiClientSecure tlsClient;
  if (strncmp(BACKEND_URL, "https://", 8) == 0) {
    // Encrypts traffic but skips certificate verification -- fine for a
    // prototype. For production, use tlsClient.setCACert(<root CA PEM>).
    tlsClient.setInsecure();
    http.begin(tlsClient, BACKEND_URL);
  } else {
    http.begin(plainClient, BACKEND_URL);
  }
  http.setTimeout(15000);   // free cloud tiers can be slow to wake up
  http.addHeader("Content-Type", "application/json");
  if (strlen(API_KEY) > 0) {
    http.addHeader("X-API-Key", API_KEY);
  }

  String payload = String("{") +
    "\"patient_id\":" + PATIENT_ID + "," +
    "\"hr\":" + String(hr, 1) + "," +
    "\"spo2\":" + String(spo2, 1) + "," +
    "\"temperature\":" + String(temp, 2) + "," +
    "\"movement\":" + String(movement, 3) + "," +
    "\"source\":\"live_device\"," +
    "\"device_id\":\"" + DEVICE_ID + "\"" +
  "}";

  int statusCode = http.POST(payload);
  if (statusCode > 0) {
    Serial.println("Sent -> " + payload);
    Serial.println("Response: " + http.getString());
  } else {
    Serial.println("POST failed, error: " + http.errorToString(statusCode));
  }
  http.end();
}

void loop() {
  unsigned long now = millis();
  if (now - lastRead >= READ_INTERVAL_MS) {
    lastRead = now;

    float hr       = readHeartRate();
    float spo2     = readSpO2();
    float temp     = readTemperature();
    float movement = readMovement();

    sendReading(hr, spo2, temp, movement);
  }
}
