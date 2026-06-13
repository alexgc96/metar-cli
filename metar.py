#!/usr/bin/env python3
"""aviation-cli — METAR + TAF terminal dashboard"""

import argparse
import sys
import requests
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

console = Console()
DEFAULT_ICAO = "MMML"
METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL   = "https://aviationweather.gov/api/data/taf"
ASOS_URL  = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

FR_STYLES = {
    "VFR":  ("green",   "bold white on green"),
    "MVFR": ("blue",    "bold white on blue"),
    "IFR":  ("red",     "bold white on red"),
    "LIFR": ("magenta", "bold white on magenta"),
}

ROSE_GRID = [
    ["↖", "↑", "↗"],
    ["←", "·", "→"],
    ["↙", "↓", "↘"],
]
ROSE_POS = {
    "N":  (0, 1), "NE": (0, 2), "E":  (1, 2), "SE": (2, 2),
    "S":  (2, 1), "SW": (2, 0), "W":  (1, 0), "NW": (0, 0),
}

CHANGE_STYLES = {
    "FM":     "bold cyan",
    "BECMG":  "bold yellow",
    "TEMPO":  "bold magenta",
    "PROB30": "dim magenta",
    "PROB40": "dim magenta",
}


def deg_to_cardinal(deg):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(float(deg) / 45) % 8]


def render_rose(wdir, wspd, color):
    active = ROSE_POS[deg_to_cardinal(wdir)] if wdir and wspd > 0 else None
    t = Text()
    for r in range(3):
        for c in range(3):
            ch = ROSE_GRID[r][c]
            style = f"bold {color}" if active and (r, c) == active else "dim"
            t.append(ch, style=style)
            t.append(" ")
        if r < 2:
            t.append("\n")
    return t


SPARKS = "▁▂▃▄▅▆▇█"


def sparkline(values):
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return "─" * len(values)
    lo, hi = min(clean), max(clean)
    if lo == hi:
        return SPARKS[3] * len(values)
    return "".join(
        SPARKS[round((v - lo) / (hi - lo) * 7)] if v is not None else " "
        for v in values
    )


def fetch_metar(icao):
    resp = requests.get(METAR_URL, params={"ids": icao, "format": "json"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        console.print(f"[red]No METAR data for {icao}[/red]")
        sys.exit(1)
    return data[0]


def fetch_taf(icao):
    resp = requests.get(TAF_URL, params={"ids": icao, "format": "json"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


def fetch_history(icao, hours=6):
    now   = datetime.now(tz=timezone.utc)
    start = now - timedelta(hours=hours)
    resp  = requests.get(ASOS_URL, params={
        "station": icao, "data": "tmpf,drct,sknt,alti",
        "year1": start.year, "month1": start.month, "day1": start.day, "hour1": start.hour,
        "year2": now.year,   "month2": now.month,   "day2": now.day,   "hour2": now.hour,
        "tz": "UTC", "format": "onlycomma", "latlon": "no", "missing": "null",
    }, timeout=10)
    records = []
    for line in resp.text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            tmpf = float(parts[2]) if parts[2] != "null" else None
            wspd = float(parts[4]) if parts[4] != "null" else None
            alti = float(parts[5]) if parts[5] != "null" else None
            records.append({
                "temp": (tmpf - 32) * 5 / 9 if tmpf is not None else None,
                "wspd": wspd,
                "inhg": alti,
            })
        except (ValueError, IndexError):
            continue
    return records


def age_str(obs_time):
    try:
        dt = datetime.fromtimestamp(int(obs_time), tz=timezone.utc)
        mins = int((datetime.now(tz=timezone.utc) - dt).total_seconds() / 60)
        return f"{mins}m ago"
    except Exception:
        return ""


def fmt_time(ts):
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%d/%Hz")
    except Exception:
        return "??Z"


def get_ceiling(clouds):
    for layer in (clouds or []):
        if layer.get("cover") in ("BKN", "OVC"):
            return f"{layer['base']:,} ft"
    return "None"


def hpa_to_inhg(hpa):
    return f"{float(hpa) * 0.02953:.2f}"


def render_history(history):
    if len(history) < 2:
        return None
    temps = [r.get("temp") for r in history]
    winds = [r.get("wspd") for r in history]
    inhgs = [r.get("inhg") for r in history]

    def cell(label, vals, spark_style, fmt, unit):
        clean = [v for v in vals if v is not None]
        t = Text()
        t.append(f"{label}  ", style="dim")
        t.append(sparkline(vals), style=f"bold {spark_style}")
        if clean:
            t.append(f"  {fmt.format(min(clean))}→{fmt.format(max(clean))} {unit}", style=f"dim {spark_style}")
        return t

    tbl = Table(box=None, show_header=False, padding=(0, 3), expand=False)
    tbl.add_column()
    tbl.add_column()
    tbl.add_column()
    tbl.add_row(
        cell("temp", temps, "yellow", "{:.0f}", "°C"),
        cell("wind", winds, "cyan",   "{:.0f}", "kt"),
        cell("QNH",  inhgs, "white",  "{:.2f}", "inHg"),
    )
    return tbl


def parse_iso(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        mins = int((datetime.now(tz=timezone.utc) - dt).total_seconds() / 60)
        return f"{mins}m ago"
    except Exception:
        return ""


def render_taf(taf):
    if not taf:
        return

    valid_from = fmt_time(taf.get("validTimeFrom", 0))
    valid_to   = fmt_time(taf.get("validTimeTo", 0))
    issued     = parse_iso(taf.get("issueTime", ""))

    t = Text()
    t.append(f"valid {valid_from} → {valid_to}", style="dim white")
    t.append(f"   issued {issued}\n\n", style="dim cyan")

    for period in taf.get("fcsts", []):
        change = period.get("fcstChange") or "BASE"
        time_from = fmt_time(period.get("timeFrom", 0))
        time_to   = fmt_time(period.get("timeTo", 0))

        label_style = CHANGE_STYLES.get(change, "bold white")

        t.append(f"{change:<6} ", style=label_style)
        t.append(f"{time_from}→{time_to}  ", style="dim")

        wdir = period.get("wdir")
        wspd = period.get("wspd") or 0
        wgst = period.get("wgst")
        if wspd == 0 or wspd is None:
            t.append("Calm  ", style="cyan")
        else:
            t.append(f"{int(wspd)}", style="bold cyan")
            if wgst:
                t.append(f"G{int(wgst)}", style="bold red")
            t.append("kt", style="cyan")
            if wdir is not None:
                card = deg_to_cardinal(wdir)
                t.append(f" {int(wdir)}°{card}", style="dim cyan")
            t.append("  ")

        vis = period.get("visib")
        if vis is not None:
            t.append(f"{vis}SM  ", style="white")

        clouds = period.get("clouds") or []
        for c in clouds:
            cover = c.get("cover", "")
            base  = c.get("base")
            if cover == "SKC" or cover == "CLR":
                t.append("SKC  ", style="dim")
            elif base is not None:
                t.append(f"{cover} {base:,}ft  ", style="dim white")

        wx = period.get("wxString")
        if wx:
            t.append(wx, style="bold yellow")

        t.append("\n")

    raw = taf.get("rawTAF", "")
    if raw:
        t.append("\n")
        t.append(raw, style="dim white")

    console.print(Panel(t, title="[dim]TAF[/dim]", border_style="dim"))


def show_station(icao, show_taf=False, raw_only=False):
    m       = fetch_metar(icao)
    history = fetch_history(icao)

    fr     = m.get("flightCategory", "VFR")
    temp   = m.get("temp")
    dewp   = m.get("dewp")
    wdir   = m.get("wdir")
    wspd   = m.get("wspd", 0)
    wgst   = m.get("wgst")
    visib  = m.get("visib", "—")
    altim  = m.get("altim")
    clouds = m.get("clouds", [])
    wx     = m.get("wxString") or ""
    raw    = m.get("rawOb", "")
    name   = m.get("name", "")
    obs    = m.get("obsTime", 0)

    if raw_only:
        console.print(raw)
        return

    fr_color, fr_style = FR_STYLES.get(fr, ("white", "bold white"))

    # ── Header ──────────────────────────────────────────────────────────
    hdr = Text()
    hdr.append(f"METAR {icao}", style="bold white")
    if name:
        hdr.append(f"  ·  {name}", style="dim white")
    hdr.append(f"   {age_str(obs)}", style="dim cyan")
    console.print(hdr)
    console.rule(style="dim white")

    # ── Stat cards ───────────────────────────────────────────────────────
    stats = Table(box=None, show_header=False, padding=(0, 2), expand=False)
    for _ in range(6):
        stats.add_column(justify="center")

    fr_cell = Text(f" {fr} ", style=fr_style)

    temp_cell = Text()
    if temp is not None:
        temp_cell.append(f"{int(temp)}°C", style="bold yellow")
        if dewp is not None:
            temp_cell.append(f" / {int(dewp)}°", style="dim yellow")

    wind_val = Text()
    wind_sub = Text("")
    if not wspd or wspd == 0:
        wind_val.append("Calm", style="bold cyan")
    else:
        wind_val.append(f"{int(wspd)}", style="bold cyan")
        if wgst:
            wind_val.append(f"G{int(wgst)}", style="bold red")
        wind_val.append("kt", style="cyan")
        wind_val.append(f"  {int(wdir)}°", style="dim cyan")
        wind_sub = Text(deg_to_cardinal(wdir), style="dim")

    vis_cell  = Text(f"{visib} mi", style="bold white")
    ceil_cell = Text(get_ceiling(clouds), style="bold white")
    qnh_cell  = Text(f"{hpa_to_inhg(altim)} inHg" if altim else "—", style="bold white")

    stats.add_row(fr_cell, temp_cell, wind_val, vis_cell, ceil_cell, qnh_cell)
    stats.add_row(
        Text(""),
        Text(wx or "Clear", style="dim"),
        wind_sub if wspd else Text(""),
        Text("Visibility", style="dim"),
        Text("Ceiling", style="dim"),
        Text("QNH", style="dim"),
    )

    console.print(stats)
    console.rule(style="dim white")

    # ── Wind rose + cloud layers side by side ────────────────────────────
    rose_text = render_rose(wdir, wspd, fr_color)
    rose_panel = Panel(rose_text, title="[dim]wind[/dim]", width=13, border_style="dim")

    clouds_text = Text()
    altitudes = [20000, 15000, 12000, 9000, 6000, 3000, 0]
    cloud_map = {int(c["base"]): c["cover"] for c in (clouds or [])}
    for alt in altitudes:
        label = f"{alt//1000:>2}k" if alt > 0 else " 0 "
        clouds_text.append(f"{label} │ ", style="dim")
        match = next((cov for base, cov in cloud_map.items() if abs(base - alt) < 1500), None)
        if match:
            clouds_text.append(f"☁ {match}", style="bold white")
        clouds_text.append("\n")
    clouds_text.append("    └" + "─" * 12, style="dim")

    clouds_panel = Panel(clouds_text, title="[dim]clouds[/dim]", width=22, border_style="dim")
    console.print(Columns([rose_panel, clouds_panel]))
    console.rule(style="dim white")

    # ── Sparkline history ────────────────────────────────────────────────
    hist_text = render_history(history)
    if hist_text:
        console.print(Panel(hist_text, title="[dim]history (6h)[/dim]", border_style="dim"))
        console.rule(style="dim white")

    # ── Raw METAR ────────────────────────────────────────────────────────
    console.print(Panel(Text(raw, style="dim white"), title="[dim]raw[/dim]", border_style="dim"))

    # ── TAF ──────────────────────────────────────────────────────────────
    if show_taf:
        console.rule(style="dim white")
        taf = fetch_taf(icao)
        render_taf(taf)


def main():
    parser = argparse.ArgumentParser(
        prog="metar",
        description="Aviation weather dashboard — METAR + TAF",
    )
    parser.add_argument(
        "icao", nargs="*", default=[DEFAULT_ICAO],
        metavar="ICAO", help="One or more ICAO station codes (default: MMML)",
    )
    parser.add_argument("--taf", action="store_true", help="Include TAF forecast block")
    parser.add_argument("--raw", action="store_true", help="Print raw METAR string only")
    args = parser.parse_args()

    stations = [s.upper() for s in args.icao]
    for i, icao in enumerate(stations):
        if i > 0:
            console.print()
        show_station(icao, show_taf=args.taf, raw_only=args.raw)


if __name__ == "__main__":
    main()
