# Sylva Soil Node: A Low-Cost ESP32 Field Probe for Regenerative-Farm Verification

**Technical note (preprint draft)** · August 2026  
**Status:** Working paper for internal / arXiv / Zenodo deposit — not peer-reviewed.

---

## Abstract

Commercial soil-monitoring stations remain expensive (€1,500–2,500) relative to the decision value they provide for smallholders entering agroforestry or regenerative subsidy schemes. We describe **Sylva Soil Node**, an open, sub-$60 ESP32-based probe that samples capacitive soil moisture, temperature, and optional EC; buffers offline; and syncs over Wi-Fi when available. The node is designed as *field verification* for a consulting stack (soil profile → species match → transition plan), not as a full precision-agriculture replacement. We situate the design against recent low-cost IoT soil literature and outline a calibration + power budget that matches published ESP32 deep-sleep practice.

## 1. Motivation

Subsidy and transition plans for regenerative / agroforestry systems need evidence that soil conditions are moving in the claimed direction. Lab visits and commercial IoT stations are hard to justify at the scale of advisory pilots. Literature shows that **ESP32 + capacitive moisture + cloud ingest** is already a workable pattern for small-scale irrigation and horticulture, provided sensors are calibrated per soil type.

Sylva’s contribution is product framing, not a new radio PHY:

1. Pair a cheap verification node with **geospatial farm profiling** (SoilGrids, topo, optional NDVI) and **species / plan RAG**.
2. Optimize for **offline-first deep sleep** rather than always-on telemetry.
3. Keep BOM in the **$35–60** band so pilots can place multiple nodes per farm.

## 2. Related work (cheap soil nodes)

| Paper | What they built | Cost / notes | How Sylva relates |
|---|---|---|---|
| López et al., *Sensors* 2024 — [Soil water status with LoRa for woody crops](https://doi.org/10.3390/s24248104) | ESP32 nodes + LoRa gateway; temp, matric potential, water content in a Spanish vineyard | ~€300 vs €1.5–2.5k commercial | Same MCU family; Sylva v1 uses Wi-Fi sync, LoRa as optional rural upgrade |
| Froiz-Míguez et al., *Sensors* 2021 — [WSN deployment for PA irrigation](https://doi.org/10.3390/s21051693) / [PMC7957636](https://pmc.ncbi.nlm.nih.gov/articles/PMC7957636/) | ESP32 Wi-Fi soil nodes; on-/near-/above-ground placement; sleep when idle | Emphasizes foliage attenuation | Informs Sylva fence-post / above-ground antenna placement |
| Adamo et al., 2025 — [Capacitive SEN0193 calibration](https://pmc.ncbi.nlm.nih.gov/articles/PMC11768944/) | ESP32 + DFRobot SEN0193; gravimetric calibration in loamy silt | R² ≈ 0.85–0.87; RMSE ≈ 4.5–4.9% | Validates Sylva’s capacitive probe choice; **per-soil calibration required** |
| BIO Web Conf. 2024 — [Smart soil moisture ESP-32, coastal horticulture](https://doi.org/10.1051/bioconf/20249604001) | Capacitive + ESP32 ADC + solar + Node-RED / spreadsheet | Explicit low-cost modules | Same solar + capacitive pattern as Sylva BOM |
| JSSCT 2025 — [Real-time ESP32 soil moisture + Firebase](https://journal.usg.ac.id/index.php/jssct/en/article/view/418) | Moisture + irrigation + web UI; &lt;10% error; ~0.04 s cloud delay | Small-scale / household | Cloud ingest pattern mirrors Sylva `/api/v1/sensors/ingest` |
| Pascal / Devitara 2025 — [ESP32 irrigation + Blynk](https://jurnal.devitara.or.id/index.php/komputer/article/view/393) | Hysteresis irrigation (40–60%); −31.6% water vs manual | Greenhouse / pots | Control loop is optional; Sylva focuses on **verification logging** |
| Castro et al., 2025 — [I-Canopy](https://arroma.uiowa.edu/docs/publication/paper_pdf/2025/castro_et_al_2025.pdf) | ESP32 edge platform; solar; local buffer; sync when online | Resilient rural monitoring | Closest architectural cousin: **buffer → sync → sleep** |

**Takeaway:** Building a cheap ESP32 soil node is well-trodden. Sylva should cite this line of work and differentiate on *advisory integration* (profile + species + plan) and *offline verification*, not on inventing capacitive sensing.

## 3. System design (Sylva)

### 3.1 Hardware (target BOM ~$35–60)

- ESP32-WROOM / DevKit (Wi-Fi + BLE)
- Capacitive moisture (SEN0193-class)
- DS18B20 (1-Wire temperature)
- Optional analog EC
- 18650 + TP4056 + 1–2 W solar
- IP65 enclosure

Duty cycle: wake → median of 3 samples → append JSONL → POST if network → deep sleep (default 30 min).

### 3.2 Software

- Firmware: Arduino / PlatformIO soil node (`hardware/esp32/`)
- Ingest: `POST /api/v1/sensors/ingest`
- Product UI: farm profile, species match, RAG transition plan; hardware explainer at `/hardware`

### 3.3 Why not Raspberry Pi in the field

Pi-class boards raise BOM, continuous power, and failure modes (SD, OS). Published ESP32 agricultural nodes already demonstrate multi-week operation with deep sleep and solar assist (e.g. intermittent sensing down to tens of mA average in solar-node designs). Local LLM belongs in a farm-office Phase-2, not on the fence post.

## 4. Calibration & limits (from literature)

1. **Calibrate capacitive sensors per soil texture** — generalized factory curves are insufficient (Adamo et al.; López et al.).
2. **Cheap analog pH probes drift outdoors** — treat lab / SoilGrids pH as the hard filter for species matching; use the node for moisture / temp / EC *trends*.
3. **Wi-Fi range collapses under dense canopy** — place nodes / antennas above vegetation where possible (Froiz-Míguez et al.); plan LoRa for larger woody crops.
4. **Irrigation automation is optional** — Sylva’s primary KPI is trustworthy time series for advisors, not pump control.

## 5. Evaluation plan (to complete before formal submission)

- [ ] Gravimetric calibration curve for 2–3 regional soil types
- [ ] Deep-sleep current and projected 18650 + solar autonomy
- [ ] Offline buffer integrity across multi-day outages
- [ ] Side-by-side moisture vs a commercial reference probe
- [ ] Farmer / advisor pilot: does the node change plan compliance conversations?

## 6. How to publish this note

1. **Zenodo** (DOI in ~minutes): zip `hardware/esp32/` + this file → upload as “Software Documentation” / “Preprint”.
2. **arXiv**: category suggestions `cs.CY`, `eess.SP`, or `cs.NI`; need endorsement if first-time submitter.
3. **Workshop / short paper**: target IoT-in-agriculture tracks (e.g. MDPI *Sensors* “Low-Cost Sensors” special issues mirror López et al.).

Do **not** claim peer review until a venue accepts the work. This file is citation-ready related work + design rationale.

## References

1. López et al. (2024). Soil Water Status Monitoring System with Proximal Low-Cost Sensors and LoRa… *Sensors* 24(24), 8104. https://doi.org/10.3390/s24248104  
2. Froiz-Míguez et al. (2021). Deployment Strategies of Soil Monitoring WSN… *Sensors* 21(5), 1693. https://doi.org/10.3390/s21051693  
3. Adamo et al. (2025). Calibration of Low-Cost Capacitive Soil Moisture Sensors… https://pmc.ncbi.nlm.nih.gov/articles/PMC11768944/  
4. BIO Web of Conferences (2024). Smart Soil Moisture Control Based on IoT ESP-32… https://doi.org/10.1051/bioconf/20249604001  
5. JSSCT (2025). An IoT-Based Real-Time Soil Moisture Monitoring System… https://journal.usg.ac.id/index.php/jssct/en/article/view/418  
6. Pascal Journal (2025). Design and Implementation of IoT-Based Soil Moisture… https://jurnal.devitara.or.id/index.php/komputer/article/view/393  
7. Castro et al. (2025). I-Canopy: A resilient IoT platform… https://arroma.uiowa.edu/docs/publication/paper_pdf/2025/castro_et_al_2025.pdf  

---

*Correspondence: Sylva project repository — `hardware/esp32/`, `docs/sylva-soil-node-preprint.md`*
