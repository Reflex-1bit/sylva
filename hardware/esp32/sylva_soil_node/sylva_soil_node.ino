/*
 * Sylva Soil Node — ESP32 prototype firmware
 *
 * Reads capacitive soil moisture + DS18B20 temperature, buffers samples,
 * and POSTs JSON batches to Sylva when WiFi is available.
 *
 * Board: ESP32 / ESP32-S3
 * Libs:  ArduinoJson, OneWire, DallasTemperature, HTTPClient (built-in)
 *
 * Setup:
 *   1. Copy secrets.h.example → secrets.h
 *   2. Set WIFI_SSID, WIFI_PASS, INGEST_URL, DEVICE_ID
 *   3. Wire:
 *        Moisture AOUT → GPIO34 (ADC1)
 *        DS18B20 data  → GPIO4  (+ 4.7k pull-up to 3V3)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include "secrets.h"

// ── Pins / timing ────────────────────────────────────────────────────────────
static const int PIN_MOISTURE = 34;
static const int PIN_ONEWIRE  = 4;
static const int PIN_BATTERY  = 35;   // optional voltage divider; set ENABLE_BATTERY 0 to skip
#ifndef ENABLE_BATTERY
#define ENABLE_BATTERY 1
#endif

#ifndef SAMPLE_INTERVAL_S
#define SAMPLE_INTERVAL_S 1800
#endif

static const int MOISTURE_AIR  = 3200;  // calibrate dry
static const int MOISTURE_WATER = 1400; // calibrate wet

OneWire oneWire(PIN_ONEWIRE);
DallasTemperature sensors(&oneWire);
Preferences prefs;

struct Sample {
  uint32_t ts;
  int moisture_raw;
  float moisture_pct;
  float temp_c;
  float battery_v;
  int rssi;
};

static const int MAX_BUFFER = 48;
Sample buffer[MAX_BUFFER];
int buffer_len = 0;

float readBattery() {
#if !ENABLE_BATTERY
  return -1.0f;
#else
  // Assume 2:1 divider → ADC reads ~Vbatt/2; 3.3V ref, 12-bit
  int raw = analogRead(PIN_BATTERY);
  return (raw / 4095.0f) * 3.3f * 2.0f;
#endif
}

int median3(int a, int b, int c) {
  if (a > b) { int t = a; a = b; b = t; }
  if (b > c) { int t = b; b = c; c = t; }
  if (a > b) { int t = a; a = b; b = t; }
  return b;
}

float moisturePct(int raw) {
  float pct = 100.0f * float(MOISTURE_AIR - raw) / float(MOISTURE_AIR - MOISTURE_WATER);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

Sample takeSample() {
  int a = analogRead(PIN_MOISTURE);
  delay(20);
  int b = analogRead(PIN_MOISTURE);
  delay(20);
  int c = analogRead(PIN_MOISTURE);
  int raw = median3(a, b, c);

  sensors.requestTemperatures();
  float temp = sensors.getTempCByIndex(0);
  if (temp < -40 || temp > 85) temp = NAN;

  Sample s;
  s.ts = (uint32_t)(time(nullptr) > 100000 ? time(nullptr) : millis() / 1000);
  s.moisture_raw = raw;
  s.moisture_pct = moisturePct(raw);
  s.temp_c = temp;
  s.battery_v = readBattery();
  s.rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  return s;
}

void pushSample(const Sample& s) {
  if (buffer_len < MAX_BUFFER) {
    buffer[buffer_len++] = s;
  } else {
    // drop oldest
    for (int i = 1; i < MAX_BUFFER; i++) buffer[i - 1] = buffer[i];
    buffer[MAX_BUFFER - 1] = s;
  }
}

bool connectWifi(uint32_t timeout_ms = 15000) {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeout_ms) {
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

bool syncBatch() {
  if (buffer_len == 0) return true;
  if (!connectWifi()) return false;

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["firmware"] = "0.1.0";
  JsonArray arr = doc["samples"].to<JsonArray>();
  for (int i = 0; i < buffer_len; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["ts_unix"] = buffer[i].ts;
    o["moisture_raw"] = buffer[i].moisture_raw;
    o["moisture_pct"] = buffer[i].moisture_pct;
    o["temp_c"] = buffer[i].temp_c;
    o["battery_v"] = buffer[i].battery_v;
    o["rssi"] = buffer[i].rssi;
    if (DEVICE_LAT != 0 || DEVICE_LON != 0) {
      o["lat"] = DEVICE_LAT;
      o["lon"] = DEVICE_LON;
    }
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(INGEST_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int code = http.POST(body);
  http.end();

  Serial.printf("[sylva] POST %s → %d (%d samples)\n", INGEST_URL, code, buffer_len);
  if (code >= 200 && code < 300) {
    buffer_len = 0;
    return true;
  }
  return false;
}

void printSample(const Sample& s) {
  Serial.printf(
    "{\"device_id\":\"%s\",\"ts\":%u,\"moisture_raw\":%d,\"moisture_pct\":%.1f,\"temp_c\":%.2f,\"battery_v\":%.2f}\n",
    DEVICE_ID, s.ts, s.moisture_raw, s.moisture_pct, s.temp_c, s.battery_v
  );
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("[sylva] soil node boot");

  analogReadResolution(12);
  sensors.begin();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");

  Sample s = takeSample();
  pushSample(s);
  printSample(s);
  syncBatch();

  Serial.printf("[sylva] sleeping %d s\n", SAMPLE_INTERVAL_S);
  esp_sleep_enable_timer_wakeup((uint64_t)SAMPLE_INTERVAL_S * 1000000ULL);
  esp_deep_sleep_start();
}

void loop() {
  // never reached — deep sleep restarts setup()
}
