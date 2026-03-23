"""
╔══════════════════════════════════════════════════════════════════╗
║     SATELLITE CONSTELLATION PRO SIMULATOR v3.0  (FIXED)         ║
║  • 3D Earth globe  • Orbit trails  • Day/Night terminator        ║
║  • Keep-out spheres  • Atmospheric drag  • Conjunction analysis  ║
║  • Eclipse detection  • Doppler shift  • RF Link budget          ║
║  • Constellation optimizer  • 8 Ground stations                  ║
║  • WebSocket live browser dashboard  • Tkinter GUI               ║
╚══════════════════════════════════════════════════════════════════╝

Install (all optional except numpy/matplotlib/tkinter):
    pip install numpy matplotlib pandas openpyxl requests sgp4 websockets cartopy

Run:
    python satellite_sim_pro_v3.py
    Then open dashboard.html in your browser for the live web dashboard.
"""

# ── stdlib ──────────────────────────────────────────────────────
import os
import math
import json
import threading
import asyncio
from collections import deque
from datetime import datetime, timezone

# ── third-party ─────────────────────────────────────────────────
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import pandas as pd

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from sgp4.api import Satrec, jday
    SGP4_AVAILABLE = True
except ImportError:
    SGP4_AVAILABLE = False

try:
    import websockets
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    CARTOPY_AVAILABLE = True
except ImportError:
    CARTOPY_AVAILABLE = False

# ════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════
EARTH_R     = 6371.0
MU          = 398600.4418
C_LIGHT     = 299792.458
ATM_H0      = 200.0
ATM_RHO0    = 2.53e-10
ATM_H_SCALE = 50.0
CD          = 2.2
SAT_AREA    = 10.0
SAT_MASS    = 260.0
FREQ_GHZ    = 12.0
TX_PWR_DBW  = 30.0
TX_GAIN_DB  = 35.0
RX_GAIN_DB  = 30.0
NOISE_T_K   = 290.0
BOLTZMANN   = 1.380649e-23
CONJ_THRESH = 50.0
KEEPOUT_KM  = 30.0
TRAIL_LEN   = 30

TARGET = dict(name="Bangladesh", lat=23.685, lon=90.356)

GROUND_STATIONS = [
    dict(name="Dhaka",     lat=23.685,  lon=90.356,  color="#00d4ff"),
    dict(name="Tokyo",     lat=35.690,  lon=139.692, color="#ff6b6b"),
    dict(name="London",    lat=51.507,  lon=-0.127,  color="#ffd93d"),
    dict(name="New York",  lat=40.712,  lon=-74.005, color="#6bcb77"),
    dict(name="Sydney",    lat=-33.86,  lon=151.209, color="#ff9f43"),
    dict(name="Cape Town", lat=-33.92,  lon=18.424,  color="#a29bfe"),
    dict(name="Sao Paulo", lat=-23.55,  lon=-46.633, color="#fd79a8"),
    dict(name="Mumbai",    lat=19.076,  lon=72.877,  color="#00cec9"),
]

SHELLS_FALLBACK = [
    dict(alt=550,  inc=53.0, n=6, name="LEO-A"),
    dict(alt=1200, inc=70.0, n=5, name="LEO-B"),
    dict(alt=2000, inc=86.4, n=4, name="MEO"),
]

TLE_URLS = {
    "Starlink": "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle",
    "ISS":      "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle",
    "OneWeb":   "https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=tle",
}

# ════════════════════════════════════════════════════════════════
# PHYSICS HELPERS
# ════════════════════════════════════════════════════════════════

def haversine(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return 2 * EARTH_R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def slant_range(slat, slon, salt, tlat, tlon):
    gd = haversine(slat, slon, tlat, tlon)
    return math.sqrt(gd**2 + salt**2)


def gmst_degrees(jd, fr):
    T = ((jd + fr) - 2451545.0) / 36525.0
    return (280.46061837 + 360.98564736629*((jd+fr)-2451545.0) + 0.000387933*T**2) % 360


def drag_decay_km_per_day(alt_km):
    if alt_km > 1000:
        return 0.0
    rho = ATM_RHO0 * math.exp(-(alt_km - ATM_H0) / ATM_H_SCALE)
    r   = (EARTH_R + alt_km) * 1e3
    v   = math.sqrt(MU * 1e9 / r)
    F_d = 0.5 * CD * (SAT_AREA / SAT_MASS) * rho * v**2
    a   = EARTH_R + alt_km
    da  = 2 * a**2 * F_d * 86400 / (MU * 1e3)
    return da


def in_eclipse(sat_lat, sat_lon, sat_alt, sun_lon_deg):
    r_sat        = EARTH_R + sat_alt
    anti_sun_lon = (sun_lon_deg + 180) % 360 - 180
    dlon         = math.radians(sat_lon - anti_sun_lon)
    dlat         = math.radians(sat_lat)
    ang          = math.acos(max(-1.0, min(1.0, math.cos(dlat)*math.cos(dlon))))
    shadow_ang   = math.asin(min(1.0, EARTH_R / r_sat))
    return ang < shadow_ang


def sun_longitude(jd, fr):
    D = (jd + fr) - 2451545.0
    g = math.radians(357.529 + 0.98560028 * D)
    return (280.459 + 0.98564736*D + 1.915*math.sin(g) + 0.020*math.sin(2*g)) % 360


def doppler_hz(freq_ghz, slat, slon, salt, plat, plon, palt):
    r1  = slant_range(slat, slon, salt, TARGET["lat"], TARGET["lon"])
    r2  = slant_range(plat, plon, palt, TARGET["lat"], TARGET["lon"])
    v_r = r1 - r2
    f   = freq_ghz * 1e9
    return -f * v_r / C_LIGHT


def link_budget(slant_km, freq_ghz=FREQ_GHZ):
    wavelength_m = (C_LIGHT * 1e3) / (freq_ghz * 1e9)
    slant_m      = slant_km * 1e3
    fspl         = 20 * math.log10(4 * math.pi * slant_m / wavelength_m)
    eirp         = TX_PWR_DBW + TX_GAIN_DB
    rx_pwr       = eirp - fspl + RX_GAIN_DB
    noise_dbw    = 10 * math.log10(BOLTZMANN * NOISE_T_K * 1e6)
    snr          = rx_pwr - noise_dbw
    margin       = snr - 10.0
    snr_linear   = max(1e-9, 10 ** (snr / 10))
    bw_hz        = min(500e6, snr_linear * BOLTZMANN * NOISE_T_K)
    cap_mb       = max(0.0, bw_hz * math.log2(1 + snr_linear) / 1e6)
    return dict(fspl_db=round(fspl, 1), eirp_dbw=round(eirp, 1),
                rx_dbw=round(rx_pwr, 1), snr_db=round(snr, 1),
                margin_db=round(margin, 1), capacity_mbps=round(cap_mb, 2))


def check_conjunctions(positions):
    warnings = []
    n = len(positions)
    for i in range(n):
        for j in range(i+1, n):
            d    = haversine(positions[i][0], positions[i][1],
                             positions[j][0], positions[j][1])
            dalt = abs(positions[i][2] - positions[j][2])
            dist = math.sqrt(d**2 + dalt**2)
            if dist < CONJ_THRESH:
                warnings.append((i, j, round(dist, 1)))
    return warnings


def optimize_constellation(n_sats=6, altitude=550, fov_deg=30, n_trials=50):
    best_inc   = 53.0
    best_score = 0.0
    test_grid  = [(lat, lon)
                  for lat in range(-80, 81, 20)
                  for lon in range(-180, 181, 30)]
    n_frames   = 60
    r_cov      = (EARTH_R + altitude) * math.sin(math.radians(fov_deg / 2))

    for _ in range(n_trials):
        inc_try   = np.random.uniform(0, 90)
        base_lons = np.linspace(-180, 180, n_sats, endpoint=False)
        covered   = total = 0
        for f in range(n_frames):
            tf      = f / n_frames
            sat_pos = []
            for bl in base_lons:
                angle   = 2*math.pi * ((tf + bl/360) % 1)
                inc     = math.radians(inc_try)
                lat     = math.degrees(math.asin(
                              max(-1.0, min(1.0, math.sin(inc)*math.sin(angle)))))
                lon_off = math.degrees(math.atan2(
                              math.cos(inc)*math.sin(angle), math.cos(angle)))
                lon     = (bl + lon_off + 180) % 360 - 180
                sat_pos.append((lat, lon))
            for (glat, glon) in test_grid:
                total += 1
                for (slat, slon) in sat_pos:
                    if haversine(slat, slon, glat, glon) <= r_cov:
                        covered += 1
                        break
        score = covered / total
        if score > best_score:
            best_score = score
            best_inc   = inc_try

    return dict(best_inclination=round(best_inc, 2),
                coverage_fraction=round(best_score, 4),
                n_sats=n_sats, altitude=altitude, fov_deg=fov_deg)

# ════════════════════════════════════════════════════════════════
# TLE / PROPAGATION
# ════════════════════════════════════════════════════════════════

def fetch_tles(source="Starlink", max_sats=12):
    if not REQUESTS_AVAILABLE:
        print("[TLE] requests not installed")
        return []
    url = TLE_URLS.get(source, TLE_URLS["Starlink"])
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        lines = [l.strip() for l in r.text.splitlines() if l.strip()]
        out = []
        for i in range(0, min(len(lines)-2, max_sats*3), 3):
            out.append((lines[i], lines[i+1], lines[i+2]))
        return out
    except Exception as e:
        print(f"[TLE] fetch failed: {e}")
        return []


def keplerian_pos(base_lon, inc_deg, alt_km, time_frac):
    angle   = 2 * math.pi * time_frac
    inc     = math.radians(inc_deg)
    lat     = math.degrees(math.asin(
                  max(-1.0, min(1.0, math.sin(inc)*math.sin(angle)))))
    lon_off = math.degrees(math.atan2(
                  math.cos(inc)*math.sin(angle), math.cos(angle)))
    lon     = (base_lon + lon_off + 180) % 360 - 180
    return lat, lon, alt_km

# ════════════════════════════════════════════════════════════════
# WEBSOCKET  (module-level — not inside class)
# ════════════════════════════════════════════════════════════════
ws_clients = set()
ws_data    = {}
ws_loop    = None


async def _dummy_coro():
    pass


async def _ws_handler(websocket):
    ws_clients.add(websocket)
    try:
        async for _ in websocket:
            pass
    finally:
        ws_clients.discard(websocket)


async def _ws_broadcast():
    while True:
        if ws_clients and ws_data:
            msg  = json.dumps(ws_data)
            dead = set()
            for ws in list(ws_clients):
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            ws_clients -= dead
        await asyncio.sleep(0.5)


async def _ws_main():
    try:
        server = await websockets.serve(_ws_handler, "localhost", 8765)
    except Exception as e:
        print(f"[WS] Could not start: {e}")
        return
    asyncio.ensure_future(_ws_broadcast())
    await server.wait_closed()


def _start_ws_thread():
    global ws_loop
    ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_loop)
    try:
        ws_loop.run_until_complete(_ws_main())
    except Exception as e:
        print(f"[WS] error: {e}")

# ════════════════════════════════════════════════════════════════
# DASHBOARD HTML
# ════════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Satellite Sim Live Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');
  :root{--bg:#030712;--panel:#0d1b2a;--border:#1e3a5f;--accent:#00d4ff;--green:#22c55e;--red:#ef4444;--yellow:#f59e0b;--text:#e2e8f0;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Share Tech Mono',monospace;min-height:100vh;}
  header{background:linear-gradient(90deg,#030712,#0d1b2a,#030712);border-bottom:1px solid var(--border);padding:12px 24px;display:flex;align-items:center;gap:16px;}
  header h1{font-family:'Orbitron',sans-serif;font-size:1.1rem;color:var(--accent);letter-spacing:3px;}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 1.5s infinite;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;padding:16px;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;position:relative;overflow:hidden;}
  .card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent),transparent);}
  .card h2{font-family:'Orbitron',sans-serif;font-size:.65rem;letter-spacing:2px;color:var(--accent);margin-bottom:12px;text-transform:uppercase;}
  .big{font-size:2rem;font-weight:700;color:var(--accent);}
  .label{font-size:.7rem;color:#64748b;margin-top:2px;}
  .row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #0f2035;}
  .row:last-child{border:none;}
  .tag{padding:2px 8px;border-radius:4px;font-size:.65rem;}
  .tag.ok{background:#052e16;color:var(--green);border:1px solid var(--green);}
  .tag.err{background:#2d0a0a;color:var(--red);border:1px solid var(--red);}
  .bar-wrap{height:8px;background:#0f2035;border-radius:4px;overflow:hidden;margin-top:6px;}
  .bar{height:100%;border-radius:4px;transition:width .4s;}
  #cov-timeline{display:flex;gap:2px;height:40px;align-items:flex-end;}
  .tb{flex:1;min-width:3px;border-radius:2px 2px 0 0;}
  table{width:100%;font-size:.7rem;border-collapse:collapse;}
  td,th{padding:4px 6px;border-bottom:1px solid #0f2035;text-align:left;}
  th{color:var(--accent);font-size:.6rem;}
  .cw{color:var(--red);}
  footer{text-align:center;padding:12px;color:#1e3a5f;font-size:.65rem;}
  #ws-status{margin-left:auto;color:#64748b;font-size:.75rem;}
</style>
</head>
<body>
<header>
  <div class="dot"></div>
  <h1>SATELLITE CONSTELLATION LIVE DASHBOARD</h1>
  <span id="ws-status">Connecting...</span>
</header>
<div class="grid">
  <div class="card">
    <h2>Coverage Status</h2>
    <div class="big" id="cov-pct">--</div>
    <div class="label">Bangladesh coverage %</div>
    <div style="margin-top:10px" id="cov-tag"></div>
    <div class="bar-wrap"><div class="bar" id="cov-bar" style="background:var(--green);width:0%"></div></div>
  </div>
  <div class="card">
    <h2>Serving Satellite</h2>
    <div class="big" style="font-size:1rem" id="srv-sat">--</div>
    <div style="margin-top:8px">
      <div class="row"><span>Latency</span><span id="latency">--</span></div>
      <div class="row"><span>Rx Power</span><span id="rxpwr">--</span></div>
      <div class="row"><span>SNR</span><span id="snr">--</span></div>
      <div class="row"><span>Capacity</span><span id="cap">--</span></div>
      <div class="row"><span>Doppler</span><span id="doppler">--</span></div>
    </div>
  </div>
  <div class="card">
    <h2>Eclipse and Drag</h2>
    <div class="row"><span>Eclipse</span><span id="eclipse">--</span></div>
    <div class="row"><span>Orbit Decay</span><span id="decay">--</span></div>
    <div class="row"><span>Serving Alt</span><span id="alt-srv">--</span></div>
    <div class="row"><span>Shadow Frac</span><span id="shad-frac">--</span></div>
  </div>
  <div class="card">
    <h2>Conjunction Alerts</h2>
    <div id="conj-list"><span style="color:#64748b">No warnings</span></div>
  </div>
  <div class="card" style="grid-column:span 2">
    <h2>Coverage Timeline</h2>
    <div id="cov-timeline"></div>
  </div>
  <div class="card">
    <h2>Ground Stations</h2>
    <table><thead><tr><th>Station</th><th>Cov</th><th>Latency</th></tr></thead>
    <tbody id="gs-table"></tbody></table>
  </div>
  <div class="card">
    <h2>Link Budget</h2>
    <table><thead><tr><th>Param</th><th>Value</th></tr></thead>
    <tbody id="lb-table"></tbody></table>
  </div>
</div>
<footer>WebSocket: ws://localhost:8765 | Updates every 500ms</footer>
<script>
const hist=[];
function connect(){
  const ws=new WebSocket("ws://localhost:8765");
  ws.onopen=()=>{ document.getElementById('ws-status').textContent='Connected'; };
  ws.onclose=()=>{ document.getElementById('ws-status').textContent='Reconnecting...'; setTimeout(connect,2000); };
  ws.onerror=()=>{ document.getElementById('ws-status').textContent='Error'; };
  ws.onmessage=e=>{
    const d=JSON.parse(e.data);
    const pct=d.cov_pct||0;
    document.getElementById('cov-pct').textContent=pct.toFixed(1)+'%';
    document.getElementById('cov-bar').style.width=pct+'%';
    document.getElementById('cov-tag').innerHTML=d.covered?'<span class="tag ok">COVERED</span>':'<span class="tag err">NOT COVERED</span>';
    document.getElementById('srv-sat').textContent=d.serving||'None';
    document.getElementById('latency').textContent=d.latency?d.latency.toFixed(1)+' ms':'--';
    document.getElementById('rxpwr').textContent=d.rx_dbw!=null?d.rx_dbw+' dBW':'--';
    document.getElementById('snr').textContent=d.snr_db!=null?d.snr_db+' dB':'--';
    document.getElementById('cap').textContent=d.capacity_mbps!=null?d.capacity_mbps+' Mbps':'--';
    document.getElementById('doppler').textContent=d.doppler_hz!=null?d.doppler_hz.toFixed(0)+' Hz':'--';
    document.getElementById('eclipse').innerHTML=d.eclipse?'<span class="tag err">IN SHADOW</span>':'<span class="tag ok">SUNLIT</span>';
    document.getElementById('decay').textContent=d.drag_km_day!=null?d.drag_km_day.toFixed(5)+' km/day':'--';
    document.getElementById('alt-srv').textContent=d.serving_alt?d.serving_alt.toFixed(1)+' km':'--';
    document.getElementById('shad-frac').textContent=d.shadow_frac!=null?(d.shadow_frac*100).toFixed(1)+'%':'--';
    const cl=document.getElementById('conj-list');
    cl.innerHTML=(d.conjunctions&&d.conjunctions.length)
      ?d.conjunctions.map(c=>`<div class="row cw">SAT-${c[0]} and SAT-${c[1]}: ${c[2]} km</div>`).join('')
      :'<span style="color:#64748b">No warnings</span>';
    hist.push(d.covered?1:0);
    if(hist.length>80)hist.shift();
    document.getElementById('cov-timeline').innerHTML=hist.map(v=>
      `<div class="tb" style="height:${v?100:20}%;background:${v?'var(--green)':'var(--red)'}"></div>`).join('');
    if(d.ground_stations)
      document.getElementById('gs-table').innerHTML=d.ground_stations.map(g=>
        `<tr><td>${g.name}</td><td>${g.covered?'<span class="tag ok">Y</span>':'<span class="tag err">N</span>'}</td><td>${g.latency?g.latency.toFixed(0)+' ms':'--'}</td></tr>`).join('');
    if(d.link_budget)
      document.getElementById('lb-table').innerHTML=Object.entries(d.link_budget).map(([k,v])=>
        `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  };
}
connect();
</script>
</body>
</html>"""

# ════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ════════════════════════════════════════════════════════════════
class SatSimProV3:
    def __init__(self, root):
        self.root = root
        self.root.title("Satellite Constellation Pro v3.0")
        self.root.configure(bg="#030712")

        self.running       = False
        self.frame         = 0
        self.speed         = tk.IntVar(value=1)
        self.tle_source    = tk.StringVar(value="Starlink")
        self.max_sats      = tk.IntVar(value=10)
        self.show_isl      = tk.BooleanVar(value=True)
        self.show_trails   = tk.BooleanVar(value=True)
        self.show_terminator = tk.BooleanVar(value=True)
        self.show_keepout  = tk.BooleanVar(value=True)
        self.show_gs       = tk.BooleanVar(value=True)
        self.use_realtime  = tk.BooleanVar(value=True)

        self.satrecs       = []
        self.positions     = []
        self.trails        = {}
        self.drag_alts     = {}
        self.prev_pos      = {}
        self.cov_log       = []
        self.lat_hist      = []
        self.sig_hist      = []
        self.drag_hist     = []
        self.dop_hist      = []
        self.ecl_hist      = []
        self.shadow_count  = 0
        self.export_records = []
        self.dyn2d         = []

        self._write_dashboard()
        self._build_gui()
        self._start_ws()

    def _write_dashboard(self):
        try:
            with open("dashboard.html", "w", encoding="utf-8") as f:
                f.write(DASHBOARD_HTML)
            print("[INFO] dashboard.html written")
        except Exception as e:
            print(f"[WARN] dashboard write failed: {e}")

    def _start_ws(self):
        if WS_AVAILABLE:
            threading.Thread(target=_start_ws_thread, daemon=True).start()
        else:
            print("[WS] websockets not installed — pip install websockets")

    def _push_ws(self, data):
        global ws_data
        ws_data = data
        if ws_loop and not ws_loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(_dummy_coro(), ws_loop)
            except Exception:
                pass

    # ── GUI ──────────────────────────────────────────────────────
    def _build_gui(self):
        r = self.root

        bar = tk.Frame(r, bg="#0d1b2a", pady=5)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="SAT-SIM PRO v3.0", bg="#0d1b2a",
                 fg="#00d4ff", font=("Courier", 12, "bold")).pack(side=tk.LEFT, padx=10)

        def lbl(t):
            return tk.Label(bar, text=t, bg="#0d1b2a", fg="#94a3b8", font=("Courier", 8))
        def sep():
            ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, padx=5, fill=tk.Y)

        sep()
        lbl("Source:").pack(side=tk.LEFT)
        ttk.Combobox(bar, textvariable=self.tle_source,
                     values=list(TLE_URLS.keys()), width=9, state="readonly").pack(side=tk.LEFT, padx=2)
        lbl("Sats:").pack(side=tk.LEFT, padx=(4,0))
        tk.Spinbox(bar, from_=3, to=40, textvariable=self.max_sats,
                   width=3, bg="#0f2035", fg="white").pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Reload TLEs", command=self._load_tles).pack(side=tk.LEFT, padx=4)

        sep()
        lbl("Speed:").pack(side=tk.LEFT)
        tk.Scale(bar, from_=1, to=10, orient=tk.HORIZONTAL, variable=self.speed,
                 bg="#0d1b2a", fg="white", length=80, showvalue=True).pack(side=tk.LEFT)

        sep()
        self.btn = ttk.Button(bar, text="Start", command=self._toggle)
        self.btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Reset",     command=self._reset).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Optimize",  command=self._run_optimizer).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Export",    command=self._export).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Dashboard", command=self._open_dashboard).pack(side=tk.LEFT, padx=2)

        sep()
        for text, var in [("Trails",     self.show_trails),
                           ("Terminator", self.show_terminator),
                           ("ISL",        self.show_isl),
                           ("Keep-out",   self.show_keepout),
                           ("Stations",   self.show_gs),
                           ("Realtime",   self.use_realtime)]:
            tk.Checkbutton(bar, text=text, variable=var, bg="#0d1b2a", fg="white",
                           selectcolor="#0f2035", activebackground="#0d1b2a",
                           font=("Courier", 8)).pack(side=tk.LEFT)

        nb = ttk.Notebook(r)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self.nb = nb

        self.tabs = {}
        for name in ["3D Globe","2D Map","Link Budget","Conjunctions",
                     "Analytics","Optimizer","Log"]:
            f = tk.Frame(nb, bg="#030712")
            nb.add(f, text=name)
            self.tabs[name] = f

        self._build_tab_3d(self.tabs["3D Globe"])
        self._build_tab_2d(self.tabs["2D Map"])
        self._build_tab_linkbudget(self.tabs["Link Budget"])
        self._build_tab_conjunctions(self.tabs["Conjunctions"])
        self._build_tab_analytics(self.tabs["Analytics"])
        self._build_tab_optimizer(self.tabs["Optimizer"])
        self._build_tab_log(self.tabs["Log"])

        self.status_var = tk.StringVar(value="Ready — press Reload TLEs then Start")
        tk.Label(r, textvariable=self.status_var, bg="#0d1b2a", fg="#00d4ff",
                 font=("Courier", 8), anchor="w").pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=2)

    # ── Tab: 3D Globe ─────────────────────────────────────────────
    def _build_tab_3d(self, parent):
        self.fig3d = plt.Figure(figsize=(10, 6), facecolor="#000010")
        self.ax3d  = self.fig3d.add_subplot(111, projection='3d')
        self.ax3d.set_facecolor("#000010")
        self._draw_earth_base()
        c = FigureCanvasTkAgg(self.fig3d, parent)
        c.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(c, parent).pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas3d = c

    def _draw_earth_base(self):
        ax = self.ax3d
        ax.clear()
        ax.set_facecolor("#000010")
        ax.set_axis_off()
        u  = np.linspace(0, 2*np.pi, 60)
        v  = np.linspace(0, np.pi,   30)
        xs = np.outer(np.cos(u), np.sin(v))
        ys = np.outer(np.sin(u), np.sin(v))
        zs = np.outer(np.ones_like(u), np.cos(v))
        ax.plot_surface(xs, ys, zs, color="#1a5c2a", alpha=0.55, linewidth=0)
        for ld in range(-60, 61, 30):
            la = math.radians(ld)
            t  = np.linspace(0, 2*np.pi, 100)
            ax.plot(np.cos(la)*np.cos(t), np.cos(la)*np.sin(t),
                    np.sin(la)*np.ones_like(t), color="#1e3a5f", lw=0.3, alpha=0.5)
        for ld in range(0, 360, 30):
            lo = math.radians(ld)
            t  = np.linspace(0, np.pi, 50)
            ax.plot(np.cos(t)*np.cos(lo), np.cos(t)*np.sin(lo),
                    np.sin(t), color="#1e3a5f", lw=0.3, alpha=0.5)

    # ── Tab: 2D Map ───────────────────────────────────────────────
    def _build_tab_2d(self, parent):
        self.fig2d = plt.Figure(figsize=(12, 6), facecolor="#030712")
        if CARTOPY_AVAILABLE:
            self.ax2d = self.fig2d.add_subplot(111, projection=ccrs.PlateCarree())
            self.ax2d.set_facecolor("#001428")
            self.ax2d.set_global()
            self.ax2d.coastlines(lw=0.5, color="#334155")
            self.ax2d.add_feature(cfeature.LAND,    facecolor="#0f2722")
            self.ax2d.add_feature(cfeature.OCEAN,   facecolor="#001428")
            self.ax2d.add_feature(cfeature.BORDERS, lw=0.3, edgecolor="#1e3a5f")
            self.ax2d.gridlines(lw=0.2, color="#1e3a5f", draw_labels=True)
            self.T2 = ccrs.PlateCarree()
        else:
            self.ax2d = self.fig2d.add_subplot(111)
            self.ax2d.set_facecolor("#001428")
            self.ax2d.set_xlim(-180, 180)
            self.ax2d.set_ylim(-90, 90)
            self.ax2d.set_aspect("equal")
            self.ax2d.grid(lw=0.2, color="#1e3a5f")
            self.T2 = None
        self.fig2d.tight_layout()
        c = FigureCanvasTkAgg(self.fig2d, parent)
        c.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(c, parent).pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas2d = c

    # ── Tab: Link Budget ─────────────────────────────────────────
    def _build_tab_linkbudget(self, parent):
        f = tk.Frame(parent, bg="#030712")
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(f, text="RF LINK BUDGET CALCULATOR", bg="#030712", fg="#00d4ff",
                 font=("Courier", 11, "bold")).pack(pady=8)
        grid = tk.Frame(f, bg="#030712")
        grid.pack()
        params = [("Frequency (GHz)",      FREQ_GHZ),
                  ("Tx Power (dBW)",        TX_PWR_DBW),
                  ("Tx Antenna Gain (dBi)", TX_GAIN_DB),
                  ("Rx Antenna Gain (dBi)", RX_GAIN_DB),
                  ("Noise Temp (K)",        NOISE_T_K)]
        self.lb_vars = {}
        for i, (lbl_text, val) in enumerate(params):
            tk.Label(grid, text=lbl_text, bg="#030712", fg="#94a3b8",
                     font=("Courier", 9), width=25, anchor="e").grid(row=i, column=0, padx=6, pady=3)
            v = tk.DoubleVar(value=val)
            self.lb_vars[lbl_text] = v
            tk.Entry(grid, textvariable=v, bg="#0d1b2a", fg="white",
                     font=("Courier", 9), width=10).grid(row=i, column=1, padx=6, pady=3)
        ttk.Button(f, text="Calculate", command=self._calc_linkbudget).pack(pady=8)
        self.lb_out = scrolledtext.ScrolledText(f, bg="#0d1b2a", fg="#00d4ff",
                                                font=("Courier", 9), height=14)
        self.lb_out.pack(fill=tk.BOTH, expand=True, padx=4)

    def _calc_linkbudget(self):
        slant = 800.0
        if self.positions:
            bi = self._best_sat_idx()
            if bi >= 0:
                s     = self.positions[bi]
                slant = slant_range(s[0], s[1], s[2], TARGET["lat"], TARGET["lon"])
        freq = self.lb_vars.get("Frequency (GHz)", tk.DoubleVar(value=FREQ_GHZ)).get()
        lb   = link_budget(slant, freq)
        self.lb_out.delete("1.0", tk.END)
        lines = [
            "=" * 42, "  RF LINK BUDGET RESULTS", "=" * 42,
            f"  Slant Range          : {slant:.1f} km",
            f"  Free Space Path Loss : {lb['fspl_db']} dB",
            f"  EIRP                 : {lb['eirp_dbw']} dBW",
            f"  Received Power       : {lb['rx_dbw']} dBW",
            f"  SNR                  : {lb['snr_db']} dB",
            f"  Link Margin          : {lb['margin_db']} dB  "
            f"{'  OK' if lb['margin_db'] > 0 else '  FAIL'}",
            f"  Max Throughput       : {lb['capacity_mbps']} Mbps",
            "=" * 42,
        ]
        self.lb_out.insert(tk.END, "\n".join(lines))

    # ── Tab: Conjunctions ────────────────────────────────────────
    def _build_tab_conjunctions(self, parent):
        f = tk.Frame(parent, bg="#030712")
        f.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Label(f, text="CONJUNCTION ANALYSIS  (close-approach < 50 km)",
                 bg="#030712", fg="#f59e0b", font=("Courier", 10, "bold")).pack(pady=6)
        self.conj_text = scrolledtext.ScrolledText(
            f, bg="#0d1b2a", fg="#f59e0b", font=("Courier", 9))
        self.conj_text.pack(fill=tk.BOTH, expand=True)

    # ── Tab: Analytics ───────────────────────────────────────────
    def _build_tab_analytics(self, parent):
        self.fig_an = plt.Figure(figsize=(12, 5), facecolor="#030712")
        self.fig_an.subplots_adjust(wspace=0.35, hspace=0.45)
        self.ax_cov  = self.fig_an.add_subplot(231, facecolor="#0a0f1a")
        self.ax_lat  = self.fig_an.add_subplot(232, facecolor="#0a0f1a")
        self.ax_sig  = self.fig_an.add_subplot(233, facecolor="#0a0f1a")
        self.ax_drag = self.fig_an.add_subplot(234, facecolor="#0a0f1a")
        self.ax_dop  = self.fig_an.add_subplot(235, facecolor="#0a0f1a")
        self.ax_ecl  = self.fig_an.add_subplot(236, facecolor="#0a0f1a")
        for ax, title in [(self.ax_cov,  "Coverage"),
                           (self.ax_lat,  "Latency (ms)"),
                           (self.ax_sig,  "Rx Power (dBW)"),
                           (self.ax_drag, "Drag Decay (km/day)"),
                           (self.ax_dop,  "Doppler (Hz)"),
                           (self.ax_ecl,  "Eclipse History")]:
            ax.set_title(title, color="#00d4ff", fontsize=8)
            ax.tick_params(colors="#64748b", labelsize=6)
            for sp in ax.spines.values():
                sp.set_color("#1e3a5f")
        c = FigureCanvasTkAgg(self.fig_an, parent)
        c.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas_an = c

    # ── Tab: Optimizer ───────────────────────────────────────────
    def _build_tab_optimizer(self, parent):
        f = tk.Frame(parent, bg="#030712")
        f.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        tk.Label(f, text="CONSTELLATION COVERAGE OPTIMIZER",
                 bg="#030712", fg="#00d4ff", font=("Courier", 11, "bold")).pack(pady=8)
        grid = tk.Frame(f, bg="#030712")
        grid.pack()
        self.opt_vars = {}
        for i, (lbl_text, val) in enumerate([("Num Satellites", 6),
                                              ("Altitude (km)",  550),
                                              ("FOV (deg)",      30),
                                              ("MC Trials",      50)]):
            tk.Label(grid, text=lbl_text, bg="#030712", fg="#94a3b8",
                     font=("Courier", 9), width=20, anchor="e").grid(row=i, column=0, padx=6, pady=4)
            v = tk.IntVar(value=val)
            self.opt_vars[lbl_text] = v
            tk.Entry(grid, textvariable=v, bg="#0d1b2a", fg="white",
                     font=("Courier", 9), width=10).grid(row=i, column=1, padx=6, pady=4)
        ttk.Button(f, text="Run Optimizer  (may take ~30s)",
                   command=self._run_optimizer).pack(pady=8)
        self.opt_out = scrolledtext.ScrolledText(f, bg="#0d1b2a", fg="#22c55e",
                                                  font=("Courier", 9), height=16)
        self.opt_out.pack(fill=tk.BOTH, expand=True)

    # ── Tab: Log ─────────────────────────────────────────────────
    def _build_tab_log(self, parent):
        f = tk.Frame(parent, bg="#030712")
        f.pack(fill=tk.BOTH, expand=True)
        tk.Label(f, text="SIMULATION EVENT LOG", bg="#030712", fg="#00d4ff",
                 font=("Courier", 9, "bold")).pack(pady=4)
        self.log_text = scrolledtext.ScrolledText(f, bg="#030712", fg="#94a3b8",
                                                   font=("Courier", 8))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _log(self, msg):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)

    # ── TLE loading ──────────────────────────────────────────────
    def _load_tles(self):
        self.status_var.set("Fetching TLE data from Celestrak...")
        def _do():
            tles = fetch_tles(self.tle_source.get(), self.max_sats.get())
            self.satrecs = []
            if SGP4_AVAILABLE and tles:
                for (nm, l1, l2) in tles:
                    try:
                        self.satrecs.append((nm, Satrec.twoline2rv(l1, l2)))
                    except Exception:
                        pass
            n = len(self.satrecs) if self.satrecs else "Keplerian fallback active"
            self.status_var.set(
                f"Ready | {n} satellites | "
                f"SGP4: {'YES' if SGP4_AVAILABLE and self.satrecs else 'NO (Keplerian)'}"
            )
            self._log(f"Loaded {n} satellites from {self.tle_source.get()}")
        threading.Thread(target=_do, daemon=True).start()

    # ── Control ──────────────────────────────────────────────────
    def _toggle(self):
        self.running = not self.running
        self.btn.config(text="Pause" if self.running else "Start")
        if self.running:
            self._tick()

    def _reset(self):
        self.running = False
        self.frame   = 0
        self.btn.config(text="Start")
        for lst in [self.cov_log, self.lat_hist, self.sig_hist,
                    self.drag_hist, self.dop_hist, self.ecl_hist,
                    self.export_records]:
            lst.clear()
        self.trails.clear()
        self.drag_alts.clear()
        self.prev_pos.clear()
        self.shadow_count = 0
        self.status_var.set("Reset. Press Start.")

    # ── Positions ────────────────────────────────────────────────
    def _get_positions(self):
        out = []
        if SGP4_AVAILABLE and self.satrecs and self.use_realtime.get():
            now = datetime.now(timezone.utc)
            jd, fr = jday(now.year, now.month, now.day,
                          now.hour, now.minute,
                          now.second + now.microsecond / 1e6)
            fr  += self.frame * 30 / 86400
            gst  = gmst_degrees(jd, fr)
            for nm, sat in self.satrecs:
                try:
                    e, r, v = sat.sgp4(jd, fr)
                    if e:
                        continue
                    x, y, z = r
                    lat = math.degrees(math.atan2(z, math.sqrt(x**2 + y**2)))
                    lon = (math.degrees(math.atan2(y, x)) - gst + 180) % 360 - 180
                    alt = math.sqrt(x**2 + y**2 + z**2) - EARTH_R
                    if alt > 100:
                        out.append((lat, lon, alt, nm))
                except Exception:
                    pass
        else:
            for sh in SHELLS_FALLBACK:
                for bi, bl in enumerate(np.linspace(-180, 180, sh["n"], endpoint=False)):
                    tf = ((self.frame / 300) + (bl / 360)) % 1.0
                    la, lo, alt = keplerian_pos(bl, sh["inc"], sh["alt"], tf)
                    out.append((la, lo, alt, f"{sh['name']}-{bi}"))
        return out

    def _best_sat_idx(self):
        best_idx = -1
        best_r   = 1e9
        for i, (slat, slon, salt, _) in enumerate(self.positions):
            r_cov = (EARTH_R + salt) * math.sin(math.radians(30 / 2))
            if haversine(slat, slon, TARGET["lat"], TARGET["lon"]) <= r_cov:
                sr = slant_range(slat, slon, salt, TARGET["lat"], TARGET["lon"])
                if sr < best_r:
                    best_r   = sr
                    best_idx = i
        return best_idx

    # ── Tick ─────────────────────────────────────────────────────
    def _tick(self):
        if not self.running:
            return

        for _ in range(self.speed.get()):
            self.frame += 1

        self.positions = self._get_positions()
        if not self.positions:
            self.root.after(100, self._tick)
            return

        n   = len(self.positions)
        now = datetime.now(timezone.utc)
        jd_now = (2451545.0 +
                  (now - datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
                  .total_seconds() / 86400)
        sun_lon = sun_longitude(jd_now, 0)

        # Drag
        for i, (_, _, salt, _) in enumerate(self.positions):
            if i not in self.drag_alts:
                self.drag_alts[i] = salt
            decay = drag_decay_km_per_day(self.drag_alts[i])
            self.drag_alts[i] = max(200.0, self.drag_alts[i] - decay / 86400 * 30)

        # Trails
        for i, (slat, slon, _, _) in enumerate(self.positions):
            if i not in self.trails:
                self.trails[i] = deque(maxlen=TRAIL_LEN)
            self.trails[i].append((slat, slon))

        # Best satellite
        bi       = self._best_sat_idx()
        covered  = bi >= 0
        srv_name = self.positions[bi][3] if covered else "None"
        srv_alt  = self.positions[bi][2] if covered else 0.0

        # Metrics
        lat_ms = rx_dbw = snr = cap = dop = None
        lb = {}
        if covered:
            s      = self.positions[bi]
            sr     = slant_range(s[0], s[1], s[2], TARGET["lat"], TARGET["lon"])
            lat_ms = 2 * sr / C_LIGHT * 1000
            lb     = link_budget(sr)
            rx_dbw = lb["rx_dbw"]
            snr    = lb["snr_db"]
            cap    = lb["capacity_mbps"]
            if bi in self.prev_pos:
                pp  = self.prev_pos[bi]
                dop = doppler_hz(FREQ_GHZ, s[0], s[1], s[2], pp[0], pp[1], pp[2])
            self.prev_pos[bi] = (s[0], s[1], s[2])
            self.lat_hist.append(lat_ms)
            self.sig_hist.append(rx_dbw)
            if dop is not None:
                self.dop_hist.append(dop)

        # Eclipse
        ecl = False
        if covered:
            ecl = in_eclipse(self.positions[bi][0], self.positions[bi][1],
                              self.positions[bi][2], sun_lon)
        if covered and ecl:
            self.shadow_count += 1
        ecl_frac = self.shadow_count / max(1, self.frame)
        self.ecl_hist.append(1 if ecl else 0)

        # Drag analytics
        avg_decay = float(np.mean([
            drag_decay_km_per_day(self.drag_alts.get(i, 550)) for i in range(n)]))
        self.drag_hist.append(avg_decay)

        # Conjunctions
        conj = check_conjunctions(self.positions)

        # Ground stations
        gs_status = []
        for gs in GROUND_STATIONS:
            gs_cov = False
            gs_lat = None
            for slat, slon, salt, _ in self.positions:
                r_cov = (EARTH_R + salt) * math.sin(math.radians(30 / 2))
                if haversine(slat, slon, gs["lat"], gs["lon"]) <= r_cov:
                    gs_cov = True
                    gs_lat = (2 * slant_range(slat, slon, salt,
                                              gs["lat"], gs["lon"]) / C_LIGHT * 1000)
                    break
            gs_status.append(dict(name=gs["name"], covered=gs_cov, latency=gs_lat))

        self.cov_log.append(covered)
        cov_pct = 100 * sum(self.cov_log) / len(self.cov_log)
        sig_q   = ("Excellent" if rx_dbw and rx_dbw > -100 else
                   "Good"      if rx_dbw and rx_dbw > -110 else
                   "Fair"      if rx_dbw else "N/A")

        # Export record
        self.export_records.append({
            "Frame": self.frame,
            "UTC":   now.strftime("%Y-%m-%d %H:%M:%S"),
            "Covered": covered, "Serving": srv_name,
            "Latency_ms":    round(lat_ms, 2)   if lat_ms  else None,
            "RxPower_dBW":   rx_dbw,
            "SNR_dB":        snr,
            "Capacity_Mbps": cap,
            "Doppler_Hz":    round(dop, 1)       if dop     else None,
            "Eclipse":       ecl,
            "AvgDrag_km_day": round(avg_decay, 6),
            "Conjunctions":  len(conj),
        })

        # WS push
        self._push_ws(dict(
            frame=self.frame, covered=covered, cov_pct=round(cov_pct, 1),
            serving=srv_name, serving_alt=round(srv_alt, 1),
            latency=round(lat_ms, 2)  if lat_ms  else None,
            rx_dbw=rx_dbw, snr_db=snr, capacity_mbps=cap,
            doppler_hz=round(dop, 1)  if dop     else None,
            signal_quality=sig_q, eclipse=ecl,
            drag_km_day=round(avg_decay, 6),
            shadow_frac=round(ecl_frac, 4),
            conjunctions=[[c[0], c[1], c[2]] for c in conj],
            ground_stations=gs_status, link_budget=lb,
        ))

        # Status bar
        self.status_var.set(
            f"Frame {self.frame} | Sats:{n} | "
            f"{'Covered: '+srv_name if covered else 'No coverage'} | "
            f"{'Lat:'+str(round(lat_ms,0))+'ms' if lat_ms else ''} | "
            f"{'ECLIPSE' if ecl else 'Sunlit'} | "
            f"{'CONJ:'+str(len(conj)) if conj else ''} | "
            f"Cov:{cov_pct:.1f}%"
        )

        for (i, j, d) in conj:
            self._log(f"CONJUNCTION: SAT-{i} <-> SAT-{j}  dist={d} km")

        # Render only active tab
        tab = self.nb.index(self.nb.select())
        if   tab == 0: self._render_3d(bi, sun_lon, conj)
        elif tab == 1: self._render_2d(bi, sun_lon, conj)
        elif tab == 2: self._calc_linkbudget()
        elif tab == 3: self._render_conjunctions(conj)
        elif tab == 4: self._render_analytics()

        self.root.after(max(16, 80 - self.speed.get()*6), self._tick)

    # ── 3D render ────────────────────────────────────────────────
    def _render_3d(self, best_idx, sun_lon, conj):
        self._draw_earth_base()
        ax       = self.ax3d
        R        = EARTH_R
        colors   = plt.cm.plasma(np.linspace(0.2, 0.9, max(1, len(self.positions))))
        conj_set = {i for trio in conj for i in trio[:2]}
        sat_xyz  = []

        if self.show_terminator.get():
            t  = np.linspace(0, 2*np.pi, 200)
            sl = math.radians(sun_lon)
            ax.plot(np.sin(t)*math.cos(sl + math.pi/2),
                    np.sin(t)*math.sin(sl + math.pi/2),
                    np.cos(t), color='yellow', lw=1.0, alpha=0.6)

        for i, (slat, slon, salt, nm) in enumerate(self.positions):
            r  = (R + salt) / R
            la = math.radians(slat)
            lo = math.radians(slon)
            x  = r * math.cos(la) * math.cos(lo)
            y  = r * math.cos(la) * math.sin(lo)
            z  = r * math.sin(la)
            sat_xyz.append((x, y, z))
            col = ('lime' if i == best_idx else
                   'red'  if i in conj_set else colors[i])
            sz  = 100 if i == best_idx else (60 if i in conj_set else 25)
            ax.scatter([x], [y], [z], color=col, s=sz, zorder=10, depthshade=False)
            ax.plot([0, x], [0, y], [0, z], color=col, alpha=0.12, lw=0.5)

            if self.show_trails.get() and i in self.trails:
                tr  = list(self.trails[i])
                if len(tr) > 1:
                    tla = [math.radians(p[0]) for p in tr]
                    tlo = [math.radians(p[1]) for p in tr]
                    tx  = [math.cos(tla[k])*math.cos(tlo[k]) for k in range(len(tr))]
                    ty  = [math.cos(tla[k])*math.sin(tlo[k]) for k in range(len(tr))]
                    tz  = [math.sin(tla[k])                  for k in range(len(tr))]
                    for k in range(len(tr)-1):
                        alpha = 0.05 + 0.35 * k / len(tr)
                        ax.plot(tx[k:k+2], ty[k:k+2], tz[k:k+2],
                                color=col, lw=0.6, alpha=alpha)

            if self.show_keepout.get() and i in conj_set:
                ks = KEEPOUT_KM / R
                uf = np.linspace(0, 2*np.pi, 15)
                vf = np.linspace(0, np.pi,    8)
                xk = x + ks * np.outer(np.cos(uf), np.sin(vf))
                yk = y + ks * np.outer(np.sin(uf), np.sin(vf))
                zk = z + ks * np.outer(np.ones_like(uf), np.cos(vf))
                ax.plot_surface(xk, yk, zk, color='red', alpha=0.12)

        if self.show_isl.get() and len(sat_xyz) > 1:
            for i, (xi, yi, zi) in enumerate(sat_xyz):
                dists = sorted(
                    [(math.sqrt((xi-xj)**2+(yi-yj)**2+(zi-zj)**2), j)
                     for j, (xj, yj, zj) in enumerate(sat_xyz) if j != i])
                for _, j in dists[:2]:
                    xj, yj, zj = sat_xyz[j]
                    ax.plot([xi,xj],[yi,yj],[zi,zj], color='cyan', lw=0.4, alpha=0.3)

        la = math.radians(TARGET["lat"])
        lo = math.radians(TARGET["lon"])
        ax.scatter([math.cos(la)*math.cos(lo)],
                   [math.cos(la)*math.sin(lo)],
                   [math.sin(la)],
                   color='cyan', s=80, zorder=15, marker='*', depthshade=False)

        if self.show_gs.get():
            for gs in GROUND_STATIONS:
                la = math.radians(gs["lat"])
                lo = math.radians(gs["lon"])
                ax.scatter([math.cos(la)*math.cos(lo)],
                           [math.cos(la)*math.sin(lo)],
                           [math.sin(la)],
                           color=gs["color"], s=25, zorder=12,
                           marker='s', depthshade=False)

        ax.set_title(
            f"3D Globe | Frame {self.frame} | "
            f"{'COVERED' if best_idx >= 0 else 'NO COVERAGE'} | "
            f"{'ECLIPSE' if self.ecl_hist and self.ecl_hist[-1] else 'SUNLIT'}",
            color='lime' if best_idx >= 0 else 'red', fontsize=9)
        self.canvas3d.draw_idle()

    # ── 2D render ────────────────────────────────────────────────
    def _render_2d(self, best_idx, sun_lon, conj):
        for art in self.dyn2d:
            try:
                art.remove()
            except Exception:
                pass
        self.dyn2d.clear()

        ax       = self.ax2d
        kw       = dict(transform=self.T2) if self.T2 else {}
        colors   = plt.cm.plasma(np.linspace(0.2, 0.9, max(1, len(self.positions))))
        conj_set = {i for trio in conj for i in trio[:2]}

        # Terminator line
        if self.show_terminator.get():
            t_lons = [(sun_lon + 90 + a + 180) % 360 - 180 for a in range(0, 181, 5)]
            t_lats = [90 * math.cos(math.radians(a))        for a in range(0, 181, 5)]
            ln, = ax.plot(t_lons, t_lats, color='yellow', lw=0.9,
                          linestyle='--', alpha=0.7, **kw)
            self.dyn2d.append(ln)

        for i, (slat, slon, salt, nm) in enumerate(self.positions):
            col   = ('lime' if i == best_idx else
                     'red'  if i in conj_set else colors[i])
            alpha = 0.45 if i == best_idx else 0.2
            mk    = 9    if i == best_idx else 4
            r_cov = (EARTH_R + salt) * math.sin(math.radians(30 / 2))
            lons_c = [slon + r_cov/111 * math.cos(a)
                      for a in np.linspace(0, 2*math.pi, 60)]
            lats_c = [slat + r_cov/111 * math.sin(a)
                      for a in np.linspace(0, 2*math.pi, 60)]
            fi, = ax.fill(lons_c, lats_c, color=col, alpha=alpha, zorder=2, **kw)
            ei, = ax.plot(lons_c, lats_c, color=col, lw=0.5, zorder=3, **kw)
            self.dyn2d.extend([fi, ei])

            if self.show_keepout.get() and i in conj_set:
                lons_k = [slon + KEEPOUT_KM/111 * math.cos(a)
                          for a in np.linspace(0, 2*math.pi, 40)]
                lats_k = [slat + KEEPOUT_KM/111 * math.sin(a)
                          for a in np.linspace(0, 2*math.pi, 40)]
                ko, = ax.fill(lons_k, lats_k, color='red', alpha=0.25, zorder=4, **kw)
                self.dyn2d.append(ko)

            d, = ax.plot(slon, slat, '^', color=col, ms=mk,
                         markeredgecolor='white', markeredgewidth=0.4, zorder=6, **kw)
            self.dyn2d.append(d)

            if self.show_trails.get() and i in self.trails:
                tr = list(self.trails[i])
                if len(tr) > 1:
                    tlon = [p[1] for p in tr]
                    tlat = [p[0] for p in tr]
                    ln,  = ax.plot(tlon, tlat, color=col, lw=0.7, alpha=0.4, zorder=2, **kw)
                    self.dyn2d.append(ln)

        if self.show_isl.get():
            for i, (si_lat, si_lon, _, _) in enumerate(self.positions):
                dists = sorted(
                    [(haversine(si_lat, si_lon,
                                self.positions[j][0], self.positions[j][1]), j)
                     for j in range(len(self.positions)) if j != i])
                for _, j in dists[:2]:
                    ln, = ax.plot([si_lon, self.positions[j][1]],
                                  [si_lat, self.positions[j][0]],
                                  color='cyan', lw=0.5, alpha=0.3, zorder=4, **kw)
                    self.dyn2d.append(ln)

        if best_idx >= 0:
            ln2, = ax.plot([self.positions[best_idx][1], TARGET["lon"]],
                           [self.positions[best_idx][0], TARGET["lat"]],
                           color='yellow', linestyle='--', lw=1.5, alpha=0.85,
                           zorder=7, **kw)
            self.dyn2d.append(ln2)

        if self.show_gs.get():
            for gs in GROUND_STATIONS:
                d, = ax.plot(gs["lon"], gs["lat"], 's', color=gs["color"],
                             ms=6, zorder=12, **kw)
                t  = ax.text(gs["lon"]+1, gs["lat"]+1, gs["name"],
                             color=gs["color"], fontsize=6,
                             **(dict(transform=self.T2) if self.T2 else {}))
                self.dyn2d.extend([d, t])

        td, = ax.plot(TARGET["lon"], TARGET["lat"], '*', color='cyan',
                      ms=14, zorder=15, **kw)
        self.dyn2d.append(td)

        ax.set_title(
            f"2D Map | Frame {self.frame} | "
            f"{'Covered: '+self.positions[best_idx][3] if best_idx>=0 else 'No Coverage'}",
            color='lime' if best_idx >= 0 else 'red', fontsize=9)
        self.canvas2d.draw_idle()

    # ── Conjunctions render ──────────────────────────────────────
    def _render_conjunctions(self, conj):
        self.conj_text.delete("1.0", tk.END)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.conj_text.insert(tk.END, f"=== Conjunction Report  {ts} ===\n\n")
        if not conj:
            self.conj_text.insert(tk.END, "  No conjunctions detected.\n")
        else:
            for i, j, d in conj:
                nm_i = self.positions[i][3]
                nm_j = self.positions[j][3]
                self.conj_text.insert(
                    tk.END,
                    f"  WARNING: {nm_i}  <->  {nm_j}\n"
                    f"     Distance  : {d} km  (threshold: {CONJ_THRESH} km)\n"
                    f"     Altitudes : {self.positions[i][2]:.0f} km  /  "
                    f"{self.positions[j][2]:.0f} km\n\n")

    # ── Analytics render ─────────────────────────────────────────
    def _render_analytics(self):
        W = 150

        def prep(ax, title):
            ax.clear()
            ax.set_facecolor("#0a0f1a")
            ax.set_title(title, color="#00d4ff", fontsize=8)
            ax.tick_params(colors="#64748b", labelsize=6)
            for sp in ax.spines.values():
                sp.set_color("#1e3a5f")

        prep(self.ax_cov, "Coverage")
        ch = self.cov_log[-W:]
        if ch:
            self.ax_cov.bar(range(len(ch)), ch,
                            color=['#22c55e' if v else '#ef4444' for v in ch], width=1.0)
        self.ax_cov.set_ylim(0, 1.3)

        prep(self.ax_lat, "Latency (ms)")
        if self.lat_hist:
            lh = self.lat_hist[-W:]
            self.ax_lat.plot(lh, color='#00d4ff', lw=1.2)
            # FIX: use keyword argument for color in axhline
            self.ax_lat.axhline(y=float(np.mean(lh)), color='yellow',
                                lw=0.8, linestyle='--')

        prep(self.ax_sig, "Rx Power (dBW)")
        if self.sig_hist:
            sh = self.sig_hist[-W:]
            self.ax_sig.bar(range(len(sh)), sh,
                            color=['#22c55e' if v > -100 else
                                   '#f59e0b' if v > -110 else '#ef4444'
                                   for v in sh], width=1.0)

        prep(self.ax_drag, "Drag Decay (km/day)")
        if self.drag_hist:
            self.ax_drag.plot(self.drag_hist[-W:], color='#f59e0b', lw=1.2)

        prep(self.ax_dop, "Doppler Shift (Hz)")
        if self.dop_hist:
            self.ax_dop.plot(self.dop_hist[-W:], color='#a78bfa', lw=1.2)
            self.ax_dop.axhline(y=0, color='gray', lw=0.5, linestyle='--')

        prep(self.ax_ecl, "Eclipse History")
        eh = self.ecl_hist[-W:]
        if eh:
            self.ax_ecl.bar(range(len(eh)), eh,
                            color=['#1e3a5f' if v else '#fbbf24' for v in eh], width=1.0)
        self.ax_ecl.set_ylim(0, 1.3)

        self.canvas_an.draw_idle()

    # ── Optimizer ────────────────────────────────────────────────
    def _run_optimizer(self):
        self.opt_out.delete("1.0", tk.END)
        self.opt_out.insert(tk.END, "Running optimizer... (~30 s)\n")
        self.root.update()
        def _do():
            n_s = self.opt_vars["Num Satellites"].get()
            alt = self.opt_vars["Altitude (km)"].get()
            fov = self.opt_vars["FOV (deg)"].get()
            trl = self.opt_vars["MC Trials"].get()
            res = optimize_constellation(n_s, alt, fov, trl)
            lines = [
                "=" * 44, "  CONSTELLATION OPTIMIZER RESULTS", "=" * 44,
                f"  Satellites        : {res['n_sats']}",
                f"  Altitude          : {res['altitude']} km",
                f"  Best Inclination  : {res['best_inclination']} degrees",
                f"  Global Coverage   : {res['coverage_fraction']*100:.2f} %",
                f"  FOV               : {res['fov_deg']} degrees",
                "=" * 44, "",
                "  Use this inclination in your shell config",
                "  for maximum global Earth coverage!",
            ]
            self.opt_out.delete("1.0", tk.END)
            self.opt_out.insert(tk.END, "\n".join(lines))
            self._log(f"Optimizer: inc={res['best_inclination']} deg  "
                      f"cov={res['coverage_fraction']*100:.1f}%")
        threading.Thread(target=_do, daemon=True).start()

    # ── Export ───────────────────────────────────────────────────
    def _export(self):
        if not self.export_records:
            messagebox.showinfo("Export", "No data yet.")
            return
        df    = pd.DataFrame(self.export_records)
        fname = f"sat_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        try:
            df.to_excel(fname, index=False)
            messagebox.showinfo("Export", f"Saved:\n{os.path.abspath(fname)}")
            self._log(f"Exported {len(self.export_records)} rows to {fname}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _open_dashboard(self):
        import webbrowser
        webbrowser.open(f"file://{os.path.abspath('dashboard.html')}")
        if not WS_AVAILABLE:
            messagebox.showwarning("WebSocket",
                "Install websockets for live updates:\n  pip install websockets")


# ════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1400x860")
    root.configure(bg="#030712")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TButton",       background="#0d1b2a", foreground="#00d4ff",
                    font=("Courier", 8), borderwidth=1)
    style.configure("TNotebook",     background="#0d1b2a")
    style.configure("TNotebook.Tab", background="#0d1b2a", foreground="#94a3b8",
                    font=("Courier", 8, "bold"), padding=[8, 4])
    style.map("TNotebook.Tab",
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", "#00d4ff")])

    app = SatSimProV3(root)
    root.mainloop()