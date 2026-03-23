# 🛰️ Satellite Constellation Simulation

> A Python-based satellite constellation simulator modelling real-world orbital mechanics, coverage analysis, and signal propagation — with an interactive GUI, 3D Earth globe, live TLE data from Celestrak, and a full analytics dashboard.

[![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Celestrak](https://img.shields.io/badge/TLE_Data-Celestrak-orange?style=flat-square)](https://celestrak.org)

---

## 🌍 Demo

### Basic Coverage Map
![Basic 2D satellite coverage map showing 6 satellites over a world map with Bangladesh marked](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/coverage_map.png)

### Advanced Animated Simulation
![Animated satellite constellation with tilted orbits, coverage circles, and Bangladesh coverage checker](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/advanced_sim.png)

---

## 🖥️ Pro GUI — Full Simulation

### 3D Earth Globe Tab
![3D Earth globe with satellites, inter-satellite links, and real-time orbit visualization](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/globe_3d.png)

### 2D Map Tab
![2D world map showing satellite coverage circles, ISL mesh, and handover line to Bangladesh](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/map_2d.png)

### Analytics Tab
![Analytics dashboard showing coverage timeline, round-trip latency chart, and received signal power](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/analytics.png)

### Coverage Heatmap Tab
![Global coverage heatmap showing fraction of time each region on Earth is covered](https://raw.githubusercontent.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh/main/images/heatmap.png)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🌍 3D Earth Globe | Rotating 3D sphere with satellites, ISL mesh, and nadir lines |
| 🛰️ Real TLE Data | Fetches live Starlink / ISS / OneWeb orbits from Celestrak via SGP4 |
| 🔗 Inter-Satellite Links | Each satellite connects to its 2 nearest neighbours in real-time |
| 🤝 Handover Simulation | Tracks which satellite serves Bangladesh at every frame |
| 🔥 Coverage Heatmap | Global grid showing fraction of time each region is covered |
| 📡 Latency & Signal | Round-trip latency (ms) and Rx power (dBW) via Free Space Path Loss |
| 📊 Export to Excel | One-click export of per-frame log with time, coverage, latency, signal quality |
| ⏱️ Real-time Clock Sync | UTC time + SGP4 propagation for true current satellite positions |
| 🖥️ Interactive GUI | Tkinter GUI with 4 tabbed panels, speed slider, toggles, source selector |

---

## 🗂️ Project Structure

```
Satellite_Coverage_Bangladesh/
│
├── satellite_sim_pro.py              # Full advanced simulation (main app)
├── satellite_simulation_advanced.py  # Intermediate: animation + 4 features
├── satellite_coverage.py             # Basic: static 2D coverage map
│
├── images/                           # Screenshots for README
│   ├── coverage_map.png
│   ├── advanced_sim.png
│   ├── globe_3d.png
│   ├── map_2d.png
│   ├── analytics.png
│   └── heatmap.png
│
├── requirements.txt
├── .gitignore
├── setup_github.py
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/rubadatabassumanannya-pixel/Satellite_Coverage_Bangladesh.git
cd Satellite_Coverage_Bangladesh
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the simulation

```bash
# Full advanced GUI (recommended)
python satellite_sim_pro.py

# Intermediate animated version
python satellite_simulation_advanced.py

# Basic static coverage map
python satellite_coverage.py
```

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `numpy` | Orbital math, vector operations |
| `matplotlib` | 2D/3D plotting, animation |
| `sgp4` | Real TLE propagation (SGP4/SDP4 model) |
| `requests` | Fetching live TLE data from Celestrak |
| `pandas` | Coverage data processing |
| `openpyxl` | Excel export |
| `cartopy` | Geopolitical map rendering (optional) |
| `Pillow` | Image utilities |

> `cartopy` and `sgp4` are optional — the simulation falls back gracefully without them.

---

## 🖥️ GUI Controls

| Control | Function |
|---|---|
| Source dropdown | Switch between Starlink, ISS, OneWeb |
| Max Sats spinner | Limit number of satellites loaded |
| Speed slider | 1× to 10× simulation speed |
| ▶ Start / ⏸ Pause | Run or pause the animation |
| ⏹ Reset | Clear all logs and restart |
| ISL Links toggle | Show/hide inter-satellite links |
| Heatmap toggle | Enable heatmap accumulation |
| Coverage toggle | Show/hide coverage circles |
| Real-time toggle | Use actual UTC clock vs relative time |
| 📊 Export Excel | Save full frame log to `.xlsx` |

---

## 🔭 Physics & Models

### Orbital Propagation
- **SGP4** via the `sgp4` library when TLE data is available
- **Keplerian circular orbit** as fallback for multi-shell constellation

### Coverage
```
R_coverage = (R_earth + altitude) × sin(FOV / 2)
```

### Signal Model
```
FSPL (dB)  = 20 × log10(4π × d / λ)
Rx (dBW)   = Tx_power + Antenna_gain − FSPL
RTT (ms)   = 2 × slant_range / speed_of_light × 1000
```

### Multi-Shell Constellation (fallback)

| Shell | Altitude | Inclination | Satellites |
|---|---|---|---|
| Shell 1 | 550 km | 53° | 5 |
| Shell 2 | 1200 km | 70° | 4 |
| Shell 3 | 2000 km | 86.4° | 3 |

---

## 📊 Excel Export Format

| Column | Description |
|---|---|
| Frame | Simulation frame number |
| UTC_Time | Timestamp (UTC) |
| Covered | True/False — is Bangladesh covered? |
| Serving_Sat | Name of the serving satellite |
| Latency_ms | Round-trip latency in milliseconds |
| RxPower_dBW | Received signal power in dBW |
| Signal_Quality | Excellent / Good / Fair / Weak |

---

## 🌐 Data Source

Live TLE data is fetched from [Celestrak](https://celestrak.org):

- **Starlink:** `https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle`
- **ISS:** `https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle`
- **OneWeb:** `https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=tle`

---

## 🧭 Roadmap

- [ ] 3D textured Earth (NASA Blue Marble)
- [ ] Satellite orbit trail paths
- [ ] Day/Night terminator line
- [ ] Doppler shift calculator
- [ ] Eclipse detection (satellite in Earth's shadow)
- [ ] Atmospheric drag / orbit decay model
- [ ] Ground station network (multiple cities)
- [ ] Link budget calculator (full RF chain)
- [ ] WebSocket live dashboard (browser-based)
- [ ] Save animation as MP4/GIF

---

## 🤝 Contributing

Pull requests are welcome. For major changes, open an issue first.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

## 👤 Author

**rubadatabassumanannya-pixel**

Built with Python, orbital mechanics, and curiosity about space.

> 🎯 Target location: Bangladesh (23.685°N, 90.356°E)
