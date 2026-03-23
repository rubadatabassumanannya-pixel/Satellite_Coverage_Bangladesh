import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

# Try importing cartopy
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    CARTOPY_AVAILABLE = True
except ImportError:
    CARTOPY_AVAILABLE = False

# ==============================================================
# PARAMETERS
# ==============================================================
earth_radius = 6371  # km

# --- Multi-altitude constellation shells (Starlink-style) ---
SHELLS = [
    {"name": "Shell 1 (LEO-Low)",  "altitude": 550,  "num_sats": 6,  "inclination": 53.0, "color": "red",    "fov_deg": 30},
    {"name": "Shell 2 (LEO-Mid)",  "altitude": 1200, "num_sats": 5,  "inclination": 70.0, "color": "green",  "fov_deg": 35},
    {"name": "Shell 3 (LEO-High)", "altitude": 2000, "num_sats": 4,  "inclination": 86.4, "color": "orange", "fov_deg": 40},
]

# Bangladesh target
TARGET_LAT = 23.685
TARGET_LON = 90.356
TARGET_NAME = "Bangladesh"

# Animation
TOTAL_FRAMES = 200
INTERVAL_MS  = 60  # ms between frames

# ==============================================================
# HELPER FUNCTIONS
# ==============================================================

def coverage_radius_km(altitude_km, fov_deg):
    """Ground coverage radius (km) for a satellite at given altitude and FOV."""
    theta = np.radians(fov_deg / 2)
    return (earth_radius + altitude_km) * np.sin(theta)


def orbital_period_minutes(altitude_km):
    """Approximate orbital period in minutes using Kepler's third law."""
    mu = 398600.4418  # km^3/s^2
    r = earth_radius + altitude_km
    T_sec = 2 * np.pi * np.sqrt(r**3 / mu)
    return T_sec / 60


def satellite_position(base_lon, inclination_deg, altitude_km, time_fraction):
    """
    Compute satellite lat/lon given:
      - base_lon: starting longitude offset (degrees)
      - inclination_deg: orbital inclination
      - time_fraction: 0.0 → 1.0 representing one full orbit
    Returns (lat, lon) in degrees.
    """
    angle = 2 * np.pi * time_fraction          # mean anomaly (circular orbit)
    inc   = np.radians(inclination_deg)

    # Position in orbital plane
    x_orb = np.cos(angle)
    y_orb = np.sin(angle)

    # Rotate by inclination around x-axis
    lat = np.degrees(np.arcsin(np.sin(inc) * y_orb))

    # Longitude with RAAN offset
    lon_offset = np.degrees(np.arctan2(np.cos(inc) * y_orb, x_orb))
    lon = (base_lon + lon_offset) % 360
    if lon > 180:
        lon -= 360

    return lat, lon


def coverage_circle_polygon(center_lon, center_lat, radius_km, n_points=90):
    """
    Returns (lons, lats) for a great-circle coverage polygon
    of radius_km around (center_lon, center_lat).
    """
    R   = earth_radius
    lat0 = np.radians(center_lat)
    lon0 = np.radians(center_lon)
    d    = radius_km / R  # angular radius

    angles = np.linspace(0, 2 * np.pi, n_points)
    lats = np.degrees(np.arcsin(
        np.sin(lat0) * np.cos(d) +
        np.cos(lat0) * np.sin(d) * np.cos(angles)
    ))
    lons = np.degrees(lon0 + np.arctan2(
        np.sin(angles) * np.sin(d) * np.cos(lat0),
        np.cos(d) - np.sin(lat0) * np.sin(np.radians(lats))
    ))
    return lons, lats


def point_in_coverage(sat_lat, sat_lon, radius_km, tgt_lat, tgt_lon):
    """Return True if target point is within radius_km of satellite ground track."""
    R    = earth_radius
    lat1, lon1 = np.radians(sat_lat),  np.radians(sat_lon)
    lat2, lon2 = np.radians(tgt_lat),  np.radians(tgt_lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a    = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    dist = 2 * R * np.arcsin(np.sqrt(a))
    return dist <= radius_km


# ==============================================================
# PRE-COMPUTE satellite base longitudes per shell
# ==============================================================
for shell in SHELLS:
    shell["base_lons"] = np.linspace(-180, 180, shell["num_sats"], endpoint=False)
    shell["coverage_km"] = coverage_radius_km(shell["altitude"], shell["fov_deg"])
    shell["period_min"]  = orbital_period_minutes(shell["altitude"])

# ==============================================================
# COVERAGE HISTORY  (Bangladesh coverage checker)
# ==============================================================
coverage_log = []   # list of booleans, one per frame

# ==============================================================
# SET UP FIGURE
# ==============================================================
if CARTOPY_AVAILABLE:
    fig = plt.figure(figsize=(16, 10))
    # Main map (top, wide)
    ax_map = fig.add_axes([0.03, 0.28, 0.94, 0.68], projection=ccrs.PlateCarree())
    ax_map.set_global()
    ax_map.coastlines(linewidth=0.7)
    ax_map.add_feature(cfeature.BORDERS, linewidth=0.4)
    ax_map.add_feature(cfeature.LAND,  facecolor="#e8e8e8")
    ax_map.add_feature(cfeature.OCEAN, facecolor="#cce5ff")
    ax_map.gridlines(draw_labels=True, linewidth=0.3, linestyle='--', color='gray')
    TRANSFORM = ccrs.PlateCarree()
else:
    fig = plt.figure(figsize=(16, 10))
    ax_map = fig.add_axes([0.05, 0.28, 0.92, 0.68])
    ax_map.set_xlim(-180, 180)
    ax_map.set_ylim(-90, 90)
    ax_map.set_facecolor("#cce5ff")
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    ax_map.set_aspect("equal")
    ax_map.grid(linewidth=0.3, linestyle='--', color='gray')
    TRANSFORM = None

# Coverage timeline subplot (bottom)
ax_cov = fig.add_axes([0.07, 0.05, 0.88, 0.16])
ax_cov.set_xlim(0, TOTAL_FRAMES)
ax_cov.set_ylim(-0.2, 1.2)
ax_cov.set_xlabel("Frame (time →)", fontsize=9)
ax_cov.set_title(f"{TARGET_NAME} Coverage Timeline", fontsize=9)
ax_cov.set_yticks([0, 1])
ax_cov.set_yticklabels(["No Coverage", "Covered"], fontsize=8)
ax_cov.axhline(0.5, color='gray', linewidth=0.5, linestyle='--')

# Title
fig.suptitle("Multi-Shell Satellite Constellation — Animated Simulation", fontsize=13, fontweight='bold')

# Legend
legend_elements = []
for shell in SHELLS:
    legend_elements.append(
        Patch(facecolor=shell["color"], alpha=0.35,
              label=f"{shell['name']}  |  alt={shell['altitude']}km  |  inc={shell['inclination']}°  |  {shell['num_sats']} sats")
    )
legend_elements.append(Line2D([0],[0], marker='*', color='w', markerfacecolor='blue',
                                markersize=12, label=f"{TARGET_NAME} (target)"))
ax_map.legend(handles=legend_elements, loc='lower left', fontsize=7.5, framealpha=0.85)

# ==============================================================
# DYNAMIC OBJECTS (to be updated each frame)
# ==============================================================
# We'll store all patch/line objects so we can remove & redraw
dynamic_artists = []

# Timeline bar collection
bar_collection = []

# Coverage status text
status_text = ax_map.text(
    0.01, 0.04, "", transform=ax_map.transAxes,
    fontsize=10, color='white',
    bbox=dict(boxstyle='round,pad=0.3', facecolor='gray', alpha=0.7)
)

# Time info text
time_text = ax_map.text(
    0.99, 0.04, "", transform=ax_map.transAxes,
    fontsize=9, color='black', ha='right',
    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7)
)

# Bangladesh marker (static)
if CARTOPY_AVAILABLE:
    ax_map.plot(TARGET_LON, TARGET_LAT, 'b*', markersize=13,
                transform=TRANSFORM, zorder=10)
    ax_map.text(TARGET_LON + 2, TARGET_LAT + 2, TARGET_NAME,
                transform=TRANSFORM, fontsize=9, color='blue', fontweight='bold')
else:
    ax_map.plot(TARGET_LON, TARGET_LAT, 'b*', markersize=13, zorder=10)
    ax_map.text(TARGET_LON + 2, TARGET_LAT + 2, TARGET_NAME,
                fontsize=9, color='blue', fontweight='bold')


# ==============================================================
# ANIMATION UPDATE FUNCTION
# ==============================================================
def update(frame):
    global dynamic_artists, bar_collection

    # Remove previous dynamic artists
    for artist in dynamic_artists:
        artist.remove()
    dynamic_artists = []

    any_covered = False

    time_frac = (frame % TOTAL_FRAMES) / TOTAL_FRAMES

    for shell in SHELLS:
        alt      = shell["altitude"]
        inc      = shell["inclination"]
        color    = shell["color"]
        cov_km   = shell["coverage_km"]
        period   = shell["period_min"]

        for base_lon in shell["base_lons"]:
            # Satellites at different phases around the orbit
            phase_offset = base_lon / 360.0
            sat_lat, sat_lon = satellite_position(base_lon, inc, alt,
                                                  (time_frac + phase_offset) % 1.0)

            # Coverage circle polygon
            lons_c, lats_c = coverage_circle_polygon(sat_lon, sat_lat, cov_km)

            # Check Bangladesh coverage
            covered = point_in_coverage(sat_lat, sat_lon, cov_km, TARGET_LAT, TARGET_LON)
            if covered:
                any_covered = True

            edge_color = 'darkgreen' if covered else color
            lw = 1.5 if covered else 0.6

            if CARTOPY_AVAILABLE:
                fill, = ax_map.fill(lons_c, lats_c, color=color,
                                    alpha=0.28 if not covered else 0.5,
                                    transform=TRANSFORM, zorder=2)
                edge, = ax_map.plot(lons_c, lats_c, color=edge_color,
                                    linewidth=lw, transform=TRANSFORM, zorder=3)
                dot,  = ax_map.plot(sat_lon, sat_lat, marker='^',
                                    color=color, markersize=6,
                                    transform=TRANSFORM, zorder=5,
                                    markeredgecolor='black', markeredgewidth=0.5)
            else:
                fill, = ax_map.fill(lons_c, lats_c, color=color,
                                    alpha=0.28 if not covered else 0.5, zorder=2)
                edge, = ax_map.plot(lons_c, lats_c, color=edge_color,
                                    linewidth=lw, zorder=3)
                dot,  = ax_map.plot(sat_lon, sat_lat, marker='^',
                                    color=color, markersize=6, zorder=5,
                                    markeredgecolor='black', markeredgewidth=0.5)

            dynamic_artists.extend([fill, edge, dot])

    # Log coverage
    coverage_log.append(any_covered)

    # Update coverage timeline
    bar_color = '#22bb44' if any_covered else '#cc3333'
    bar = ax_cov.bar(frame, 1.0, width=1.0, color=bar_color, alpha=0.85, bottom=0)
    bar_collection.append(bar)

    # Status text
    if any_covered:
        status_text.set_text(f"✔ {TARGET_NAME}: COVERED")
        status_text.get_bbox_patch().set_facecolor('#22bb44')
    else:
        status_text.set_text(f"✘ {TARGET_NAME}: NOT COVERED")
        status_text.get_bbox_patch().set_facecolor('#cc3333')

    # Time info
    sim_minutes = time_frac * max(s["period_min"] for s in SHELLS)
    time_text.set_text(f"t = {sim_minutes:.1f} min")

    return dynamic_artists + [status_text, time_text]


# ==============================================================
# RUN ANIMATION
# ==============================================================
ani = animation.FuncAnimation(
    fig,
    update,
    frames=TOTAL_FRAMES,
    interval=INTERVAL_MS,
    blit=False,
    repeat=True
)

plt.show()

# ==============================================================
# POST-ANIMATION COVERAGE REPORT
# ==============================================================
if coverage_log:
    total      = len(coverage_log)
    covered    = sum(coverage_log)
    percentage = 100 * covered / total
    print("\n" + "="*50)
    print(f"  {TARGET_NAME} Coverage Report")
    print("="*50)
    print(f"  Total frames simulated : {total}")
    print(f"  Frames with coverage   : {covered}")
    print(f"  Coverage percentage    : {percentage:.1f}%")
    for shell in SHELLS:
        print(f"\n  {shell['name']}")
        print(f"    Altitude  : {shell['altitude']} km")
        print(f"    Incl.     : {shell['inclination']}°")
        print(f"    Period    : {shell['period_min']:.1f} min")
        print(f"    Coverage R: {shell['coverage_km']:.1f} km")
    print("="*50)