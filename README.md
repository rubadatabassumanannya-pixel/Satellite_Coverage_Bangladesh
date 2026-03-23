# 🛰️ Satellite Constellation Simulation

A Python-based satellite constellation simulator that models real-world orbital mechanics, coverage analysis, and signal propagation — with an interactive GUI, 3D Earth globe, live TLE data from Celestrak, and analytics dashboard.

---

## 📸 Features at a Glance

| Feature | Description |
|---|---|
| 🌍 3D Earth Globe | Rotating 3D sphere with satellites, ISL mesh, and nadir lines |
| 🛰️ Real TLE Data | Fetches live Starlink / ISS / OneWeb orbits from Celestrak via SGP4 |
| 🔗 Inter-Satellite Links | Each satellite connects to its 2 nearest neighbours in real-time |
| 🤝 Handover Simulation | Tracks which satellite serves Bangladesh at every frame |
| 🔥 Coverage Heatmap | Global grid showing what fraction of time each region is covered |
| 📡 Latency & Signal | Round-trip latency (ms) and Rx power (dBW) via Free Space Path Loss |
| 📊 Export to Excel | One-click export of per-frame log: time, coverage, latency, signal quality |
| ⏱️ Real-time Clock Sync | UTC time + SGP4 propagation for true current satellite positions |
| 🖥️ Interactive GUI | Tkinter GUI with 4 tabbed panels, speed slider, toggles, source selector |

---

## 🗂️ Project Structure

```
satellite-constellation-sim/
│
├── satellite_sim_pro.py              # Full advanced simulation (main app)
├── satellite_simulation_advanced.py  # Intermediate: animation + 4 features
├── satellite_coverage.py             # Basic: static 2D coverage map
│
├── requirements.txt                  # All Python dependencies
├── .gitignore                        # Excludes cache, outputs, venv
└── README.md                         # This file
```

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/satellite-constellation-sim.git
cd satellite-constellation-sim
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

> **Note:** `cartopy` is optional. The simulation falls back to a plain matplotlib map if it is not installed. `sgp4` is optional too — a Keplerian fallback runs automatically.

---

## 🖥️ GUI Overview

The main app (`satellite_sim_pro.py`) has four tabs:

- **🌍 3D Globe** — Satellites orbit a 3D Earth sphere. ISL links connect nearest neighbours. The serving satellite for Bangladesh is highlighted in green.
- **🗺️ 2D Map** — Cartopy (or plain matplotlib) map with coverage circles, ISL lines, and a dashed handover line to Bangladesh.
- **📈 Analytics** — Live charts for coverage timeline, round-trip latency, and received signal power.
- **🔥 Heatmap** — Accumulates coverage over time across a global lat/lon grid.

### Controls

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
- **SGP4** (Simplified General Perturbations) via the `sgp4` library when TLE data is available
- **Keplerian circular orbit** as fallback for multi-shell constellation

### Coverage
- Ground coverage radius calculated from satellite altitude and field-of-view half-angle:

```
R_coverage = (R_earth + altitude) × sin(FOV/2)
```

### Signal Model
- **Free Space Path Loss (FSPL):**

```
FSPL (dB) = 20 × log10(4π × d / λ)
```

- **Received power:**

```
Rx (dBW) = Tx_power + Antenna_gain − FSPL
```

- **Round-trip latency:**

```
RTT (ms) = 2 × slant_range / speed_of_light × 1000
```

### Multi-Shell Constellation (fallback)
Three orbital shells modelled when TLE is unavailable:

| Shell | Altitude | Inclination | Satellites |
|---|---|---|---|
| Shell 1 | 550 km | 53° | 5 |
| Shell 2 | 1200 km | 70° | 4 |
| Shell 3 | 2000 km | 86.4° | 3 |

---

## 📊 Excel Export Format

Each row in the exported `.xlsx` file contains:

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

Planned future upgrades:

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

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see below.

```
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 👤 Author

Built with Python, orbital mechanics, and a lot of curiosity about space.

> Target location: Bangladesh (23.685°N, 90.356°E)
