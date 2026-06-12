# aviation-cli

CLI weather tool for pilots and aviation nerds. Pulls live METAR/TAF data and renders a readable terminal dashboard — think wttr.in but aviation-focused.

Default station: MMML (General Rodolfo Sánchez Taboada, Mexicali)

---

## Data source

**aviationweather.gov** — free, public, no auth required.

```
METAR:   https://aviationweather.gov/api/data/metar?ids=MMML&format=json
TAF:     https://aviationweather.gov/api/data/taf?ids=MMML&format=json
History: same endpoint with &hoursBeforeNow=X
```

---

## Layout concept

```
METAR MMML · General Rodolfo Sánchez Taboada   12 Jun 07:40 LT · 34m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ▓ VFR ▓   ⛅ 29°C    ↙ 4kt    10 mi    None    29.77 inHg
 No warn   Scattered  140° SE  Visib.   Ceiling  ☽19:49 (11h35)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 20k │
 15k │
 12k │  ☁ ☁ ☁  SCT
  5k │
  0  └──────────────
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 METAR MMML 121440Z 14004KT 10SM SCT120 29/17 A2977
 RMK SLP081 5//// 910 8/080
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Temp  ▁▁▁▂▄▆█   Wind ▂▁▁▂▁▃   QNH ▂▃▃▄▃▄▄▅
```

---

## Sections

### Header
- ICAO + full airport name
- Local time + report age

### Stat cards (top row)
- **Flight rules** — color-coded: VFR (green), MVFR (blue), IFR (red), LIFR (purple)
- **Weather** — unicode symbol + temp °C
- **Wind** — unicode direction arrow + speed in kt + heading
- **Wind rose** — 9-cell compass grid, active direction arrow highlighted (colored), rest dimmed:
  ```
    ↖  N  ↗
    W  +  E
    ↙  S  ↘
  ```
  Degrees → one of 8 arrows lit up via `rich` color. Compact, readable, arrow-based.
- **Visibility** — SM or km
- **Ceiling** — lowest BKN/OVC layer or "None"
- **QNH** — inHg + local sunset time

### Cloud layer chart
- Vertical ASCII bar, altitude on Y axis (0–20,000 ft)
- Cloud symbols (☁) placed at layer altitude with coverage label (FEW/SCT/BKN/OVC)

### Raw METAR
- Monospace block, full string including remarks

### Sparkline history (last 6–12h)
- Temp, wind speed, QNH — unicode sparklines (▁▂▃▄▅▆▇█)

---

## Stack

- **Python 3** + `rich` for layout, color, panels
- `requests` for API calls
- No external aviation libs — parse the JSON ourselves, it's clean

---

## CLI usage

```bash
metar               # default to MMML
metar KJFK          # any ICAO
metar MMML KTUS     # multi-station
metar --taf         # include TAF
metar --raw         # raw string only, no render
```

---

## Phases

1. **MVP** ✅ — stat cards, raw METAR, flight rules color, wind rose, cloud layer chart
2. **v1** ✅ — sparkline history via Iowa State ASOS (hoursBeforeNow=6, temp/wind/QNH)
3. **v2** — TAF block, multi-station, configurable default ICAO

> Note: aviationweather.gov API always returns 1 record regardless of hoursBeforeNow.
> History uses mesonet.agron.iastate.edu/cgi-bin/request/asos.py instead — free, no auth, works for MMML.

---

## Notes

- Inspired by metar-taf.com dashboard (MMML view, Jun 2026)
- Wind rose: 9-cell grid, one arrow lit per direction (Option 2 — chosen for readability + arrow clarity)
- wttr.in as layout inspiration for terminal density
