# Sylva Soil Node — ESP32 Prototype

Low-cost field verification hardware for the consulting product.
The node proves soil conditions are changing; the paid deliverable remains the
subsidy / transition plan.

## Why ESP32 (not Raspberry Pi) for v1

| | ESP32 node | Pi + local LLM |
|---|---|---|
| Cost / unit | ~$25–45 BOM | ~$80–150+ |
| Power | deep-sleep weeks on battery/solar | needs constant power |
| Field reliability | high (MCU, few moving parts) | SD wear, OS updates |
| Farmer Q&A | cloud / phone app | on-device LLM |
| Role | **sensor + sync** | overkill for MVP |

Local LLM on-device is a Phase-2 farm-office feature, not the field probe.
The field unit only needs: sense → buffer → sync → sleep.

## System map

```
┌─────────────────────────────────────────────────────────────┐
│  FARM                                                       │
│  ┌──────────────┐   I2C/1-Wire    ┌─────────────────────┐   │
│  │ Soil probes  │───────────────▶│ ESP32-S3 Soil Node  │   │
│  │ moisture     │                 │  - sample 15–60 min │   │
│  │ temp         │                 │  - store SPIFFS/NVS │   │
│  │ EC (opt)     │                 │  - WiFi / LTE-M     │   │
│  │ pH (opt*)    │                 └──────────┬──────────┘   │
│  └──────────────┘                            │ MQTT/HTTPS   │
└──────────────────────────────────────────────┼──────────────┘
                                               ▼
                                    ┌────────────────────┐
                                    │ Sylva cloud ingest │
                                    │ /api/v1/sensors/*  │
                                    └─────────┬──────────┘
                                              ▼
                         farm profile + compliance timeline
                         → matching → RAG transition plan
```

\* Cheap analog pH probes drift hard outdoors. For MVP treat lab pH /
SoilGrids as the hard filter; use the node for moisture + temp + EC trends.
Calibrated pH comes in v1.1 with lab cross-checks.

## BOM (prototype)

| Part | Notes | ~USD |
|---|---|---|
| ESP32-S3 DevKit (or WROOM-32) | WiFi + BLE | 6–10 |
| Capacitive soil moisture (v1.2 / SEN0193) | prefer capacitive over resistive | 3–5 |
| DS18B20 or SHT3x | soil/air temp (±humidity if SHT) | 2–4 |
| Gravity analog EC / TDS (optional) | salinity / fertigation proxy | 12–20 |
| 18650 + TP4056 + solar 6V 1–2W | off-grid | 8–15 |
| IP65 junction box + epoxy cable gland | field survival | 5–8 |
| **Total** | | **~$35–60** |

## Firmware behaviour

1. Wake → read sensors (3 samples, median)
2. Append JSON line to `/data/log.jsonl` on SPIFFS
3. If WiFi/LTE available → POST batch to Sylva ingest → clear sent rows
4. Deep sleep `SAMPLE_INTERVAL_S` (default 1800 = 30 min)

Offline-first: weeks of samples survive without connectivity.

## Payload schema

```json
{
  "device_id": "sylva-esp-001",
  "firmware": "0.1.0",
  "ts_unix": 1770000000,
  "lat": 37.9,
  "lon": -4.7,
  "moisture_raw": 1842,
  "moisture_pct": 34.2,
  "temp_c": 18.4,
  "ec_us_cm": 420,
  "battery_v": 3.91,
  "rssi": -67
}
```

## Build & flash

Arduino IDE / PlatformIO:

```bash
# PlatformIO
cd hardware/esp32
pio run -t upload -t monitor
```

Copy `secrets.h.example` → `secrets.h` and fill WiFi + ingest URL.

## Pilot placement (5–10 farms)

- One node per management zone (not per hectare)
- Probe at 15–20 cm depth in the crop alley, not under the drip emitter
- Pair with a single lab soil test at install for calibration offsets
- Goal: continuous moisture/EC curves that back eco-scheme / EQIP compliance packs

## Roadmap

| Phase | Hardware | Software |
|---|---|---|
| **0** (now) | Breadboard ESP32 + moisture + temp | sketch below, serial JSON |
| **1** | Weatherproof BOM, solar | HTTPS ingest endpoint + dashboard strip |
| **2** | EC + calibrated moisture | compliance report PDF generator |
| **3** | Optional farm-office Pi LLM | farmer Q&A over synced history |

## What this deliberately does NOT do

- Claim carbon / nitrogen stock from cheap sensors alone
- Replace agronomist judgement or lab tests
- Run a local LLM in the field

Those claims need lab partnerships + the consulting layer — which is the product.
