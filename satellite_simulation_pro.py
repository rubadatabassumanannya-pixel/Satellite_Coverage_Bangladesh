"""
===============================================================
 ADVANCED SATELLITE CONSTELLATION SIMULATION
===============================================================
Features:
  - 3D Earth globe visualization
  - Real TLE data from Celestrak (Starlink / ISS)
  - Inter-Satellite Links (mesh network)
  - Handover simulation (which sat serves Bangladesh)
  - Coverage heatmap over time
  - Latency & signal strength estimator
  - Export coverage report to CSV/Excel
  - Real-time clock sync (actual current positions)
  - Interactive GUI (Tkinter + Matplotlib)

Dependencies:
    pip install numpy matplotlib scipy pandas openpyxl requests sgp4 Pillow
===============================================================
"""

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.colors import Normalize
from matplotlib import cm
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pandas as pd
from datetime import datetime, timezone
import threading
import os

# sgp4 for real TLE propagation
try:
    from sgp4.api import Satrec, jday
    SGP4_AVAILABLE = True
except ImportError:
    SGP4_AVAILABLE = False
    print("[WARN] sgp4 not installed. Falling back to Keplerian approximation.")

# Cartopy optional
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    CARTOPY_AVAILABLE = True
except ImportError:
    CARTOPY_AVAILABLE = False

# ==============================================================
# CONSTANTS
# ==============================================================
EARTH_RADIUS    = 6371.0        # km
MU              = 398600.4418   # km³/s²
C_LIGHT         = 299792.458    # km/s
TARGET_LAT      = 23.685
TARGET_LON      = 90.356
TARGET_NAME     = "Bangladesh"
FREQ_GHZ        = 12.0          # Ku-band downlink
TX_POWER_DBW    = 30.0          # dBW
ANTENNA_GAIN_DB = 35.0          # dBi
HEATMAP_GRID    = 36            # heatmap resolution (36x18)
HEATMAP_ROWS    = 18

# ==============================================================
# TLE FETCHER
# ==============================================================
TLE_SOURCES = {
    "Starlink": "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle",
    "ISS":      "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle",
    "OneWeb":   "https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=tle",
}

def fetch_tle(source_name="Starlink", max_sats=12):
    """Fetch TLE data from Celestrak. Returns list of (name, line1, line2)."""
    url = TLE_SOURCES.get(source_name, TLE_SOURCES["Starlink"])
    print(f"[INFO] Fetching TLE data for {source_name} from Celestrak...")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
        tles = []
        for i in range(0, min(len(lines)-2, max_sats*3), 3):
            tles.append((lines[i], lines[i+1], lines[i+2]))
        print(f"[INFO] Loaded {len(tles)} satellites from {source_name}.")
        return tles
    except Exception as e:
        print(f"[WARN] TLE fetch failed: {e}. Using fallback Keplerian model.")
        return []

# ==============================================================
# SATELLITE PROPAGATION
# ==============================================================

def current_jday():
    """Current Julian date (UTC)."""
    now = datetime.now(timezone.utc)
    jd, fr = jday(now.year, now.month, now.day,
                  now.hour, now.minute, now.second + now.microsecond/1e6)
    return jd, fr

def propagate_tle(satrec_obj, jd, fr):
    """Return (lat_deg, lon_deg, alt_km) for a sgp4 satellite object."""
    e, r, v = satrec_obj.sgp4(jd, fr)
    if e != 0:
        return None
    x, y, z = r  # ECI km
    # ECI → geodetic
    lon = np.degrees(np.arctan2(y, x))
    lat = np.degrees(np.arctan2(z, np.sqrt(x**2 + y**2)))
    alt = np.sqrt(x**2 + y**2 + z**2) - EARTH_RADIUS
    # Approximate GMST correction for longitude
    now = datetime.now(timezone.utc)
    jd_j2000 = 2451545.0
    T = ((jd + fr) - jd_j2000) / 36525.0
    gmst_deg = (280.46061837 + 360.98564736629 * ((jd + fr) - 2451545.0)
                + 0.000387933*T**2) % 360
    lon = (lon - gmst_deg + 180) % 360 - 180
    return lat, lon, alt

def keplerian_position(base_lon, inclination_deg, altitude_km, time_frac):
    """Fallback: simple Keplerian circular orbit position."""
    angle = 2 * np.pi * time_frac
    inc   = np.radians(inclination_deg)
    y_orb = np.sin(angle)
    x_orb = np.cos(angle)
    lat   = np.degrees(np.arcsin(np.sin(inc) * y_orb))
    lon_off = np.degrees(np.arctan2(np.cos(inc) * y_orb, x_orb))
    lon = (base_lon + lon_off + 180) % 360 - 180
    return lat, lon, altitude_km

def orbital_period_min(altitude_km):
    r = EARTH_RADIUS + altitude_km
    return 2 * np.pi * np.sqrt(r**3 / MU) / 60.0

# ==============================================================
# GEOMETRY HELPERS
# ==============================================================

def haversine_km(lat1, lon1, lat2, lon2):
    R = EARTH_RADIUS
    la1,lo1,la2,lo2 = map(np.radians,[lat1,lon1,lat2,lon2])
    dlat = la2-la1; dlon = lo2-lo1
    a = np.sin(dlat/2)**2 + np.cos(la1)*np.cos(la2)*np.sin(dlon/2)**2
    return 2*R*np.arcsin(np.sqrt(a))

def slant_range_km(sat_lat, sat_lon, sat_alt, tgt_lat, tgt_lon):
    """3D slant range from satellite to target on Earth's surface."""
    gs_dist = haversine_km(sat_lat, sat_lon, tgt_lat, tgt_lon)
    return np.sqrt(gs_dist**2 + sat_alt**2)

def coverage_radius_km(altitude_km, fov_deg):
    theta = np.radians(fov_deg / 2)
    return (EARTH_RADIUS + altitude_km) * np.sin(theta)

def coverage_circle(center_lon, center_lat, radius_km, n=90):
    lat0 = np.radians(center_lat); lon0 = np.radians(center_lon)
    d = radius_km / EARTH_RADIUS
    angles = np.linspace(0, 2*np.pi, n)
    lats = np.degrees(np.arcsin(np.sin(lat0)*np.cos(d)+np.cos(lat0)*np.sin(d)*np.cos(angles)))
    lons = np.degrees(lon0 + np.arctan2(np.sin(angles)*np.sin(d)*np.cos(lat0),
                                         np.cos(d)-np.sin(lat0)*np.sin(np.radians(lats))))
    return lons, lats

def point_covered(sat_lat, sat_lon, radius_km, tgt_lat, tgt_lon):
    return haversine_km(sat_lat, sat_lon, tgt_lat, tgt_lon) <= radius_km

# ==============================================================
# SIGNAL / LATENCY
# ==============================================================

def free_space_path_loss_db(slant_km, freq_ghz):
    """FSPL in dB."""
    slant_m = slant_km * 1000
    wavelength = C_LIGHT*1000 / (freq_ghz * 1e9)
    fspl = 20*np.log10(4*np.pi*slant_m/wavelength)
    return fspl

def received_power_dbw(slant_km, freq_ghz=FREQ_GHZ):
    fspl = free_space_path_loss_db(slant_km, freq_ghz)
    return TX_POWER_DBW + ANTENNA_GAIN_DB - fspl

def latency_ms(slant_km):
    return 2 * slant_km / C_LIGHT * 1000  # round-trip ms

def signal_quality(rx_power_dbw):
    """Map dBW to quality string."""
    if rx_power_dbw > -100: return "Excellent", "#22bb44"
    if rx_power_dbw > -110: return "Good",      "#88cc22"
    if rx_power_dbw > -120: return "Fair",      "#ffaa00"
    return "Weak", "#cc3333"

# ==============================================================
# HEATMAP
# ==============================================================
heatmap_counts  = np.zeros((HEATMAP_ROWS, HEATMAP_GRID))
heatmap_total   = 0

def update_heatmap(sats_latlonalt, fov_deg=30):
    global heatmap_total
    heatmap_total += 1
    lats = np.linspace(-90,  90,  HEATMAP_ROWS)
    lons = np.linspace(-180, 180, HEATMAP_GRID)
    for ri, glat in enumerate(lats):
        for ci, glon in enumerate(lons):
            for (slat, slon, salt) in sats_latlonalt:
                r_km = coverage_radius_km(salt, fov_deg)
                if point_covered(slat, slon, r_km, glat, glon):
                    heatmap_counts[ri, ci] += 1
                    break

# ==============================================================
# EXPORT
# ==============================================================
coverage_records = []   # list of dicts

def export_report():
    if not coverage_records:
        messagebox.showinfo("Export", "No data yet — run the simulation first.")
        return
    df = pd.DataFrame(coverage_records)
    fname = f"coverage_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(fname, index=False)
    messagebox.showinfo("Export", f"Report saved to:\n{os.path.abspath(fname)}")

# ==============================================================
# MAIN APP CLASS
# ==============================================================
class SatSimApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Satellite Constellation Simulator")
        self.root.configure(bg="#1a1a2e")

        # State
        self.running       = False
        self.frame         = 0
        self.total_frames  = 300
        self.speed         = 1
        self.show_isl      = tk.BooleanVar(value=True)
        self.show_heatmap  = tk.BooleanVar(value=False)
        self.show_coverage = tk.BooleanVar(value=True)
        self.tle_source    = tk.StringVar(value="Starlink")
        self.max_sats      = tk.IntVar(value=10)
        self.use_realtime  = tk.BooleanVar(value=True)

        # Satellites data: list of dicts with keys lat,lon,alt,name
        self.satellites = []
        self.satrecs    = []
        self.tles       = []

        # Coverage log
        self.cov_log     = []
        self.handover_log = []   # which sat index is serving at each frame

        self._build_gui()
        self._load_tles()

    # ----------------------------------------------------------
    def _build_gui(self):
        root = self.root

        # ---- TOP CONTROL BAR ----
        ctrl = tk.Frame(root, bg="#16213e", pady=4)
        ctrl.pack(side=tk.TOP, fill=tk.X)

        tk.Label(ctrl, text="🛰  CONSTELLATION SIM", bg="#16213e",
                 fg="#00d4ff", font=("Consolas",13,"bold")).pack(side=tk.LEFT, padx=12)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, padx=6, fill=tk.Y)

        tk.Label(ctrl, text="Source:", bg="#16213e", fg="white",
                 font=("Consolas",9)).pack(side=tk.LEFT)
        src_cb = ttk.Combobox(ctrl, textvariable=self.tle_source,
                              values=list(TLE_SOURCES.keys()), width=10, state="readonly")
        src_cb.pack(side=tk.LEFT, padx=4)

        tk.Label(ctrl, text="Max Sats:", bg="#16213e", fg="white",
                 font=("Consolas",9)).pack(side=tk.LEFT)
        tk.Spinbox(ctrl, from_=3, to=40, textvariable=self.max_sats,
                   width=4, bg="#0f3460", fg="white").pack(side=tk.LEFT, padx=4)

        ttk.Button(ctrl, text="🔄 Reload TLEs", command=self._load_tles).pack(side=tk.LEFT, padx=6)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, padx=6, fill=tk.Y)

        tk.Label(ctrl, text="Speed:", bg="#16213e", fg="white",
                 font=("Consolas",9)).pack(side=tk.LEFT)
        self.speed_scale = tk.Scale(ctrl, from_=1, to=10, orient=tk.HORIZONTAL,
                                    bg="#16213e", fg="white", length=100,
                                    command=lambda v: setattr(self,"speed",int(v)))
        self.speed_scale.set(1)
        self.speed_scale.pack(side=tk.LEFT)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self.btn_start = ttk.Button(ctrl, text="▶ Start", command=self._toggle_sim)
        self.btn_start.pack(side=tk.LEFT, padx=4)

        ttk.Button(ctrl, text="⏹ Reset", command=self._reset).pack(side=tk.LEFT, padx=2)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, padx=6, fill=tk.Y)

        tk.Checkbutton(ctrl, text="ISL Links",    variable=self.show_isl,
                       bg="#16213e", fg="white", selectcolor="#0f3460",
                       activebackground="#16213e").pack(side=tk.LEFT)
        tk.Checkbutton(ctrl, text="Heatmap",      variable=self.show_heatmap,
                       bg="#16213e", fg="white", selectcolor="#0f3460",
                       activebackground="#16213e").pack(side=tk.LEFT)
        tk.Checkbutton(ctrl, text="Coverage",     variable=self.show_coverage,
                       bg="#16213e", fg="white", selectcolor="#0f3460",
                       activebackground="#16213e").pack(side=tk.LEFT)
        tk.Checkbutton(ctrl, text="Real-time",    variable=self.use_realtime,
                       bg="#16213e", fg="white", selectcolor="#0f3460",
                       activebackground="#16213e").pack(side=tk.LEFT)

        ttk.Separator(ctrl, orient="vertical").pack(side=tk.LEFT, padx=6, fill=tk.Y)
        ttk.Button(ctrl, text="📊 Export Excel", command=export_report).pack(side=tk.LEFT, padx=4)

        # ---- NOTEBOOK (tabs) ----
        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Tab 1: 3D Globe
        tab3d = tk.Frame(nb, bg="#000010")
        nb.add(tab3d, text="🌍 3D Globe")

        # Tab 2: 2D Map
        tab2d = tk.Frame(nb, bg="#000010")
        nb.add(tab2d, text="🗺 2D Map")

        # Tab 3: Analytics
        tab_an = tk.Frame(nb, bg="#0a0a1a")
        nb.add(tab_an, text="📈 Analytics")

        # Tab 4: Heatmap
        tab_hm = tk.Frame(nb, bg="#0a0a1a")
        nb.add(tab_hm, text="🔥 Heatmap")

        self.nb = nb
        self._build_tab_3d(tab3d)
        self._build_tab_2d(tab2d)
        self._build_tab_analytics(tab_an)
        self._build_tab_heatmap(tab_hm)

        # ---- BOTTOM STATUS BAR ----
        self.status_var = tk.StringVar(value="Ready. Load TLEs and press Start.")
        tk.Label(root, textvariable=self.status_var, bg="#0f3460", fg="#00d4ff",
                 font=("Consolas",9), anchor="w").pack(side=tk.BOTTOM, fill=tk.X, padx=4)

    # ----------------------------------------------------------
    def _build_tab_3d(self, parent):
        self.fig3d = plt.Figure(figsize=(10,6), facecolor="#000010")
        self.ax3d  = self.fig3d.add_subplot(111, projection='3d',
                                             facecolor="#000010")
        self.ax3d.set_facecolor("#000010")
        self._draw_earth_3d()
        canvas = FigureCanvasTkAgg(self.fig3d, master=parent)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(canvas, parent).pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas3d = canvas

    def _draw_earth_3d(self):
        ax = self.ax3d
        ax.clear()
        ax.set_facecolor("#000010")
        # Earth sphere
        u = np.linspace(0, 2*np.pi, 60)
        v = np.linspace(0, np.pi,   30)
        xs = np.outer(np.cos(u), np.sin(v))
        ys = np.outer(np.sin(u), np.sin(v))
        zs = np.outer(np.ones_like(u), np.cos(v))
        ax.plot_surface(xs, ys, zs, color="#1a6b3c", alpha=0.55, linewidth=0)
        # Equator & prime meridian grid
        theta = np.linspace(0, 2*np.pi, 200)
        ax.plot(np.cos(theta), np.sin(theta), np.zeros_like(theta),
                'c-', linewidth=0.5, alpha=0.4)
        ax.plot(np.cos(theta), np.zeros_like(theta), np.sin(theta),
                'c-', linewidth=0.5, alpha=0.4)
        # Bangladesh marker
        la = np.radians(TARGET_LAT); lo = np.radians(TARGET_LON)
        ax.scatter([np.cos(la)*np.cos(lo)], [np.cos(la)*np.sin(lo)], [np.sin(la)],
                   color='cyan', s=60, zorder=10)
        ax.set_axis_off()
        ax.set_title("3D Earth Globe", color="white", pad=2, fontsize=10)
        self.fig3d.tight_layout()

    # ----------------------------------------------------------
    def _build_tab_2d(self, parent):
        if CARTOPY_AVAILABLE:
            self.fig2d = plt.Figure(figsize=(12,6), facecolor="#000020")
            self.ax2d  = self.fig2d.add_subplot(111, projection=ccrs.PlateCarree(),
                                                 facecolor="#000020")
            self.ax2d.set_global()
            self.ax2d.coastlines(linewidth=0.5, color='#aaaaaa')
            self.ax2d.add_feature(cfeature.LAND,  facecolor="#1a2a1a")
            self.ax2d.add_feature(cfeature.OCEAN, facecolor="#001040")
            self.ax2d.add_feature(cfeature.BORDERS, linewidth=0.3, edgecolor='#555555')
            self.ax2d.gridlines(draw_labels=True, linewidth=0.2, color='gray')
            self.TRANSFORM2D = ccrs.PlateCarree()
        else:
            self.fig2d = plt.Figure(figsize=(12,6), facecolor="#000020")
            self.ax2d  = self.fig2d.add_subplot(111, facecolor="#001040")
            self.ax2d.set_xlim(-180,180); self.ax2d.set_ylim(-90,90)
            self.ax2d.set_aspect('equal')
            self.ax2d.grid(linewidth=0.2, color='gray')
            self.TRANSFORM2D = None

        # Bangladesh marker (static)
        kw = dict(transform=self.TRANSFORM2D) if self.TRANSFORM2D else {}
        self.ax2d.plot(TARGET_LON, TARGET_LAT, 'c*', markersize=14, zorder=15, **kw)
        self.ax2d.text(TARGET_LON+2, TARGET_LAT+2, TARGET_NAME,
                       color='cyan', fontsize=8, fontweight='bold',
                       **(dict(transform=self.TRANSFORM2D) if self.TRANSFORM2D else {}))

        canvas = FigureCanvasTkAgg(self.fig2d, master=parent)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(canvas, parent).pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas2d = canvas
        self.dynamic2d = []

    # ----------------------------------------------------------
    def _build_tab_analytics(self, parent):
        self.fig_an = plt.Figure(figsize=(12,5), facecolor="#0a0a1a")
        self.fig_an.subplots_adjust(wspace=0.35)

        # Coverage timeline
        self.ax_cov  = self.fig_an.add_subplot(131, facecolor="#0a0a1a")
        self.ax_cov.set_title("Coverage Timeline", color='white', fontsize=9)
        self.ax_cov.set_xlabel("Frame", color='white', fontsize=8)
        self.ax_cov.tick_params(colors='white', labelsize=7)
        for sp in self.ax_cov.spines.values(): sp.set_color('#444')

        # Latency
        self.ax_lat  = self.fig_an.add_subplot(132, facecolor="#0a0a1a")
        self.ax_lat.set_title("Round-trip Latency (ms)", color='white', fontsize=9)
        self.ax_lat.set_xlabel("Frame", color='white', fontsize=8)
        self.ax_lat.tick_params(colors='white', labelsize=7)
        for sp in self.ax_lat.spines.values(): sp.set_color('#444')

        # Signal strength
        self.ax_sig  = self.fig_an.add_subplot(133, facecolor="#0a0a1a")
        self.ax_sig.set_title("Rx Power (dBW)", color='white', fontsize=9)
        self.ax_sig.set_xlabel("Frame", color='white', fontsize=8)
        self.ax_sig.tick_params(colors='white', labelsize=7)
        for sp in self.ax_sig.spines.values(): sp.set_color('#444')

        canvas = FigureCanvasTkAgg(self.fig_an, master=parent)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas_an = canvas

        # Info panel
        self.info_var = tk.StringVar(value="Simulation not started.")
        tk.Label(parent, textvariable=self.info_var,
                 bg="#0a0a1a", fg="#00d4ff",
                 font=("Consolas", 10), justify=tk.LEFT,
                 anchor="w").pack(fill=tk.X, padx=8, pady=4)

        self.lat_hist = []
        self.sig_hist = []
        self.cov_hist = []

    # ----------------------------------------------------------
    def _build_tab_heatmap(self, parent):
        self.fig_hm = plt.Figure(figsize=(12,5), facecolor="#0a0a1a")
        self.ax_hm  = self.fig_hm.add_subplot(111, facecolor="#0a0a1a")
        self.ax_hm.set_title("Coverage Heatmap (fraction of time covered)",
                              color='white', fontsize=10)
        self.ax_hm.tick_params(colors='white')
        self.hm_img = self.ax_hm.imshow(
            np.zeros((HEATMAP_ROWS, HEATMAP_GRID)),
            extent=[-180,180,-90,90], origin='lower',
            cmap='hot', vmin=0, vmax=1, aspect='auto'
        )
        self.fig_hm.colorbar(self.hm_img, ax=self.ax_hm, label="Coverage fraction")
        # Bangladesh dot
        self.ax_hm.plot(TARGET_LON, TARGET_LAT, 'c*', markersize=12)
        canvas = FigureCanvasTkAgg(self.fig_hm, master=parent)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas_hm = canvas

    # ----------------------------------------------------------
    def _load_tles(self):
        self.status_var.set("Fetching TLE data…")
        self.root.update()

        def _fetch():
            src  = self.tle_source.get()
            maxs = self.max_sats.get()
            tles = fetch_tle(src, maxs)
            self.tles = tles
            self.satrecs = []
            if SGP4_AVAILABLE and tles:
                for (name, l1, l2) in tles:
                    try:
                        sat = Satrec.twoline2rv(l1, l2)
                        self.satrecs.append((name, sat))
                    except Exception:
                        pass

            n = len(self.satrecs) if SGP4_AVAILABLE and self.satrecs else len(tles) or 10
            self.status_var.set(
                f"Loaded {n} satellites from {src}. "
                f"{'SGP4 active ✔' if SGP4_AVAILABLE else 'Keplerian fallback'}"
            )

        threading.Thread(target=_fetch, daemon=True).start()

    # ----------------------------------------------------------
    def _toggle_sim(self):
        if not self.running:
            self.running = True
            self.btn_start.config(text="⏸ Pause")
            self._tick()
        else:
            self.running = False
            self.btn_start.config(text="▶ Start")

    def _reset(self):
        self.running = False
        self.frame   = 0
        self.btn_start.config(text="▶ Start")
        self.cov_log.clear()
        self.handover_log.clear()
        self.lat_hist.clear()
        self.sig_hist.clear()
        self.cov_hist.clear()
        global heatmap_counts, heatmap_total
        heatmap_counts = np.zeros((HEATMAP_ROWS, HEATMAP_GRID))
        heatmap_total  = 0
        coverage_records.clear()
        self.status_var.set("Reset. Press Start to begin.")

    # ----------------------------------------------------------
    def _get_sat_positions(self):
        """Return list of (lat, lon, alt, name) for current frame/time."""
        positions = []

        if SGP4_AVAILABLE and self.satrecs and self.use_realtime.get():
            jd, fr = current_jday()
            # Offset by frame if not strictly realtime
            fr_offset = self.frame * 30.0 / 86400.0   # 30 sec per frame
            for (name, sat) in self.satrecs:
                result = propagate_tle(sat, jd, fr + fr_offset)
                if result:
                    lat, lon, alt = result
                    positions.append((lat, lon, max(alt, 100), name))
        else:
            # Keplerian fallback with multiple shells
            shells = [
                {"alt":550,  "inc":53,   "n":5, "color":"red"},
                {"alt":1200, "inc":70,   "n":4, "color":"lime"},
                {"alt":2000, "inc":86.4, "n":3, "color":"orange"},
            ]
            for si, sh in enumerate(shells):
                base_lons = np.linspace(-180,180,sh["n"],endpoint=False)
                for bi, bl in enumerate(base_lons):
                    tf = ((self.frame/self.total_frames) + bl/360.0) % 1.0
                    la, lo, alt = keplerian_position(bl, sh["inc"], sh["alt"], tf)
                    positions.append((la, lo, alt, f"SAT-{si}-{bi}"))

        return positions

    # ----------------------------------------------------------
    def _tick(self):
        if not self.running:
            return

        for _ in range(self.speed):
            self.frame += 1

        positions = self._get_sat_positions()
        if not positions:
            self.root.after(100, self._tick)
            return

        # ------ Find serving satellite (handover) ------
        best_idx   = -1
        best_range = 1e9
        for i, (slat, slon, salt, sname) in enumerate(positions):
            sr = slant_range_km(slat, slon, salt, TARGET_LAT, TARGET_LON)
            r_km = coverage_radius_km(salt, 30)
            if point_covered(slat, slon, r_km, TARGET_LAT, TARGET_LON):
                if sr < best_range:
                    best_range = sr
                    best_idx   = i

        covered  = best_idx >= 0
        lat_ms   = latency_ms(best_range)   if covered else None
        rx_dbw   = received_power_dbw(best_range) if covered else None
        sig_q, sig_col = signal_quality(rx_dbw) if covered else ("N/A","#888888")

        self.cov_log.append(covered)
        self.handover_log.append(best_idx)
        if lat_ms: self.lat_hist.append(lat_ms)
        if rx_dbw: self.sig_hist.append(rx_dbw)
        self.cov_hist.append(1 if covered else 0)

        # Record
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        serving = positions[best_idx][3] if covered else "None"
        coverage_records.append({
            "Frame":        self.frame,
            "UTC_Time":     now_str,
            "Covered":      covered,
            "Serving_Sat":  serving,
            "Latency_ms":   round(lat_ms, 2)   if lat_ms else None,
            "RxPower_dBW":  round(rx_dbw, 2)   if rx_dbw else None,
            "Signal_Quality": sig_q,
        })

        # ------ Heatmap update (every 5 frames) ------
        if self.frame % 5 == 0:
            update_heatmap(positions)

        # ------ Update status bar ------
        cov_pct = 100*sum(self.cov_log)/len(self.cov_log)
        srv_txt = f"Serving: {serving}" if covered else "No coverage"
        self.status_var.set(
            f"Frame {self.frame}  |  {srv_txt}  |  "
            f"{'Latency: '+str(round(lat_ms,1))+' ms' if lat_ms else ''}  |  "
            f"{'Rx: '+str(round(rx_dbw,1))+' dBW  '+sig_q if rx_dbw else ''}  |  "
            f"Coverage: {cov_pct:.1f}%"
        )

        # ------ Render active tab ------
        active_tab = self.nb.index(self.nb.select())
        if active_tab == 0:
            self._render_3d(positions, best_idx)
        elif active_tab == 1:
            self._render_2d(positions, best_idx)
        elif active_tab == 2:
            self._render_analytics(covered, lat_ms, rx_dbw, sig_q, serving)
        elif active_tab == 3:
            self._render_heatmap()

        self.root.after(max(20, 80 - self.speed*5), self._tick)

    # ----------------------------------------------------------
    def _render_3d(self, positions, best_idx):
        ax = self.ax3d
        self._draw_earth_3d()

        R = EARTH_RADIUS
        colors = plt.cm.plasma(np.linspace(0.2, 0.9, len(positions)))

        sat_xyz = []
        for i, (slat, slon, salt, sname) in enumerate(positions):
            r  = (R + salt) / R   # normalized
            la = np.radians(slat); lo = np.radians(slon)
            x  = r * np.cos(la)*np.cos(lo)
            y  = r * np.cos(la)*np.sin(lo)
            z  = r * np.sin(la)
            sat_xyz.append((x,y,z))
            col  = 'lime' if i == best_idx else colors[i]
            size = 80   if i == best_idx else 30
            ax.scatter([x],[y],[z], color=col, s=size, zorder=10)
            # Nadir line
            ax.plot([0, x],[0, y],[0, z], color=col, alpha=0.2, linewidth=0.5)

        # ISL: connect nearest neighbors
        if self.show_isl.get() and len(sat_xyz) > 1:
            n = len(sat_xyz)
            for i in range(n):
                dists = []
                for j in range(n):
                    if i == j: continue
                    dx = sat_xyz[i][0]-sat_xyz[j][0]
                    dy = sat_xyz[i][1]-sat_xyz[j][1]
                    dz = sat_xyz[i][2]-sat_xyz[j][2]
                    dists.append((np.sqrt(dx**2+dy**2+dz**2), j))
                dists.sort()
                for _, j in dists[:2]:   # connect 2 nearest
                    xs = [sat_xyz[i][0], sat_xyz[j][0]]
                    ys = [sat_xyz[i][1], sat_xyz[j][1]]
                    zs = [sat_xyz[i][2], sat_xyz[j][2]]
                    ax.plot(xs, ys, zs, 'c-', linewidth=0.5, alpha=0.35)

        ax.set_title(
            f"3D Globe  |  Frame {self.frame}  |  "
            f"{'✔ COVERED' if best_idx>=0 else '✘ NOT COVERED'}",
            color='lime' if best_idx>=0 else 'red', fontsize=9
        )
        self.canvas3d.draw_idle()

    # ----------------------------------------------------------
    def _render_2d(self, positions, best_idx):
        # Remove old artists
        for art in self.dynamic2d:
            try: art.remove()
            except: pass
        self.dynamic2d.clear()

        kw = dict(transform=self.TRANSFORM2D) if self.TRANSFORM2D else {}
        ax = self.ax2d
        colors = plt.cm.plasma(np.linspace(0.2, 0.9, len(positions)))

        for i, (slat, slon, salt, sname) in enumerate(positions):
            col   = 'lime' if i == best_idx else colors[i]
            alpha = 0.45   if i == best_idx else 0.2
            mk    = 10     if i == best_idx else 5

            if self.show_coverage.get():
                r_km = coverage_radius_km(salt, 30)
                lons_c, lats_c = coverage_circle(slon, slat, r_km)
                f, = ax.fill(lons_c, lats_c, color=col, alpha=alpha, zorder=2, **kw)
                e, = ax.plot(lons_c, lats_c, color=col, linewidth=0.6, zorder=3, **kw)
                self.dynamic2d.extend([f, e])

            d, = ax.plot(slon, slat, '^', color=col, markersize=mk,
                         markeredgecolor='white', markeredgewidth=0.4,
                         zorder=6, **kw)
            self.dynamic2d.append(d)

        # ISL links on 2D map
        if self.show_isl.get() and len(positions) > 1:
            for i, (slat_i, slon_i, salt_i, _) in enumerate(positions):
                dists = []
                for j, (slat_j, slon_j, salt_j, _) in enumerate(positions):
                    if i == j: continue
                    dists.append((haversine_km(slat_i,slon_i,slat_j,slon_j), j))
                dists.sort()
                for _, j in dists[:2]:
                    slat_j, slon_j = positions[j][0], positions[j][1]
                    ln, = ax.plot([slon_i, slon_j],[slat_i, slat_j],
                                  'c-', linewidth=0.6, alpha=0.4, zorder=4, **kw)
                    self.dynamic2d.append(ln)

        # Serving satellite line to Bangladesh
        if best_idx >= 0:
            bslat, bslon = positions[best_idx][0], positions[best_idx][1]
            ln2, = ax.plot([bslon, TARGET_LON],[bslat, TARGET_LAT],
                           'y--', linewidth=1.5, alpha=0.8, zorder=7, **kw)
            self.dynamic2d.append(ln2)

        ax.set_title(
            f"2D Map  |  Frame {self.frame}  |  "
            f"{'✔ Covered by: '+positions[best_idx][3] if best_idx>=0 else '✘ No Coverage'}",
            color='lime' if best_idx>=0 else 'red', fontsize=9
        )
        self.canvas2d.draw_idle()

    # ----------------------------------------------------------
    def _render_analytics(self, covered, lat_ms, rx_dbw, sig_q, serving):
        W = 200  # window

        # Coverage timeline
        ax = self.ax_cov
        ax.clear(); ax.set_facecolor("#0a0a1a")
        ax.set_title("Coverage Timeline", color='white', fontsize=8)
        ax.tick_params(colors='white', labelsize=6)
        hist = self.cov_hist[-W:]
        xs   = np.arange(len(hist))
        ax.bar(xs, hist, color=['#22bb44' if v else '#cc3333' for v in hist],
               width=1.0)
        ax.set_ylim(0,1.3); ax.set_yticks([0,1])
        ax.set_yticklabels(["No","Yes"], color='white', fontsize=7)
        for sp in ax.spines.values(): sp.set_color('#444')

        # Latency
        ax = self.ax_lat
        ax.clear(); ax.set_facecolor("#0a0a1a")
        ax.set_title("Latency (ms)", color='white', fontsize=8)
        ax.tick_params(colors='white', labelsize=6)
        if self.lat_hist:
            ax.plot(self.lat_hist[-W:], color='#00d4ff', linewidth=1.2)
            ax.axhline(np.mean(self.lat_hist[-W:]), color='yellow',
                       linestyle='--', linewidth=0.8)
        for sp in ax.spines.values(): sp.set_color('#444')

        # Signal strength
        ax = self.ax_sig
        ax.clear(); ax.set_facecolor("#0a0a1a")
        ax.set_title("Rx Power (dBW)", color='white', fontsize=8)
        ax.tick_params(colors='white', labelsize=6)
        if self.sig_hist:
            sig_col = ['#22bb44' if v > -100 else '#ffaa00' if v > -110 else '#cc3333'
                       for v in self.sig_hist[-W:]]
            ax.bar(np.arange(len(self.sig_hist[-W:])), self.sig_hist[-W:],
                   color=sig_col, width=1.0)
        for sp in ax.spines.values(): sp.set_color('#444')

        self.canvas_an.draw_idle()

        # Info panel
        cov_pct = 100*sum(self.cov_hist)/len(self.cov_hist) if self.cov_hist else 0
        avg_lat = np.mean(self.lat_hist) if self.lat_hist else 0
        avg_sig = np.mean(self.sig_hist) if self.sig_hist else 0
        self.info_var.set(
            f"  Frame: {self.frame}   |   Coverage: {cov_pct:.1f}%   |   "
            f"Avg Latency: {avg_lat:.1f} ms   |   Avg Rx: {avg_sig:.1f} dBW   |   "
            f"Serving: {serving}   |   Signal: {sig_q}"
        )

    # ----------------------------------------------------------
    def _render_heatmap(self):
        if heatmap_total > 0:
            norm = heatmap_counts / heatmap_total
            self.hm_img.set_data(norm)
            self.hm_img.set_clim(0, max(norm.max(), 0.01))
            self.ax_hm.set_title(
                f"Coverage Heatmap  (frames sampled: {heatmap_total})",
                color='white', fontsize=9
            )
            self.canvas_hm.draw_idle()


# ==============================================================
# ENTRY POINT
# ==============================================================
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1300x820")
    root.configure(bg="#1a1a2e")

    style = ttk.Style()
    try:
        style.theme_use('clam')
    except:
        pass
    style.configure("TButton",  background="#0f3460", foreground="white",
                    font=("Consolas",9))
    style.configure("TCombobox", fieldbackground="#0f3460", foreground="white")
    style.configure("TNotebook", background="#16213e")
    style.configure("TNotebook.Tab", background="#0f3460", foreground="white",
                    font=("Consolas",9,"bold"), padding=[8,4])

    app = SatSimApp(root)
    root.mainloop()