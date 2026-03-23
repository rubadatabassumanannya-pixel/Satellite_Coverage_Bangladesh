import numpy as np
import matplotlib.pyplot as plt

# Try importing cartopy
try:
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    CARTOPY_AVAILABLE = True
except ImportError:
    CARTOPY_AVAILABLE = False

# --------------------------
# Parameters
# --------------------------
earth_radius = 6371          # km
sat_altitude = 550           # km
num_satellites = 6
fov_deg = 30
target_lat = 23.685          # Bangladesh
target_lon = 90.356

# Coverage radius (km) on Earth's surface
theta_rad = np.radians(fov_deg / 2)
R_coverage = (earth_radius + sat_altitude) * np.sin(theta_rad)
print("Coverage radius (km):", round(R_coverage, 2))

# Satellite positions evenly spaced in longitude along equator
sat_angles = np.linspace(-180, 180, num_satellites, endpoint=False)

# --------------------------
# Helper: draw a coverage circle as a lat/lon polygon
# (works correctly on both plain matplotlib and cartopy)
# --------------------------
def coverage_circle_polygon(center_lon, center_lat, radius_km, n_points=90):
    """
    Returns (lons, lats) arrays for a great-circle approximation of a
    coverage circle of radius_km around (center_lon, center_lat).
    """
    R = 6371.0  # Earth radius km
    lat0 = np.radians(center_lat)
    lon0 = np.radians(center_lon)
    d = radius_km / R  # angular radius in radians

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

# --------------------------
# If Cartopy is available → map view
# --------------------------
if CARTOPY_AVAILABLE:
    print("Running with Cartopy (map view)")

    fig = plt.figure(figsize=(14, 8))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_global()
    ax.coastlines(linewidth=0.8)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    ax.add_feature(cfeature.LAND, facecolor='lightgray')
    ax.add_feature(cfeature.OCEAN, facecolor='lightblue')
    ax.gridlines(draw_labels=True, linewidth=0.4, linestyle='--', color='gray')

    for angle in sat_angles:
        sat_lon = angle
        sat_lat = 0.0

        # FIX: Draw coverage circle as a proper lat/lon polygon
        lons, lats = coverage_circle_polygon(sat_lon, sat_lat, R_coverage)
        ax.fill(lons, lats, color='red', alpha=0.25, transform=ccrs.PlateCarree())
        ax.plot(lons, lats, color='red', linewidth=0.8, transform=ccrs.PlateCarree())

        # Satellite marker
        ax.plot(sat_lon, sat_lat, 'r^', markersize=7,
                transform=ccrs.PlateCarree(), label='Satellite' if angle == sat_angles[0] else '')

    # Bangladesh marker
    ax.plot(target_lon, target_lat, 'b*', markersize=12,
            transform=ccrs.PlateCarree(), label='Bangladesh')
    ax.text(target_lon + 2, target_lat + 2, 'Bangladesh',
            transform=ccrs.PlateCarree(), fontsize=9, color='blue')

    ax.set_title("Satellite Constellation Coverage Simulation (Cartopy)", fontsize=13)
    ax.legend(loc='lower left')

# --------------------------
# If Cartopy NOT available → simple matplotlib map
# --------------------------
else:
    print("Cartopy not installed → using simple map")

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Satellite Constellation Coverage Simulation (Simple Map)", fontsize=13)
    ax.set_aspect('equal')   # FIX: prevent distortion
    ax.grid(linewidth=0.4, linestyle='--', color='gray')

    for angle in sat_angles:
        sat_lon = angle
        sat_lat = 0.0

        # FIX: Draw circle as lat/lon polygon for accuracy
        lons, lats = coverage_circle_polygon(sat_lon, sat_lat, R_coverage)
        ax.fill(lons, lats, color='red', alpha=0.25)
        ax.plot(lons, lats, color='red', linewidth=0.8)

        ax.plot(sat_lon, sat_lat, 'r^', markersize=7,
                label='Satellite' if angle == sat_angles[0] else '')

    # Bangladesh marker
    ax.plot(target_lon, target_lat, 'b*', markersize=12, label='Bangladesh')
    ax.text(target_lon + 2, target_lat + 2, 'Bangladesh', fontsize=9, color='blue')
    ax.legend(loc='lower left')

# --------------------------
# Save + show
# --------------------------
plt.tight_layout()
plt.savefig("constellation_coverage.png", dpi=150, bbox_inches='tight')
plt.show()