"""
config.py — Shared constants for the Twente emergency-response MAS.

Single source of truth for every tunable value and real-world parameter.

Provenance tags:
  [RIVM/VZinfo]     national / norm figures from vzinfo.nl (RIVM, AZN Sectorkompas)
  [Ambulance Oost]  Twente-specific figures from ambulanceoost.nl
  [WAITED]          Dutch ambulance offload-delay study (IJEM 2025)
  [NL-dashboard]    Dutch nationwide ED diversion-dashboard study (IJEM 2025)
  [DES-lit]         international DES/queueing literature (see REFERENCES at bottom)
  [ASSUMPTION]      not published as a single figure; a starting value to CALIBRATE

Full citations are in the REFERENCES block at the end of this file.

Coordinates are approximate town-centre lat/lon, projected to a local km grid at
import, so Mesa's ContinuousSpace uses plain x, y in km (Euclidean = real distance).
"""

import os
from math import cos, radians

# ---------------------------------------------------------------------------
# Region metadata
# ---------------------------------------------------------------------------
REGION_NAME = "RAV Twente (Ambulance Oost)"   # [Ambulance Oost]
POPULATION = 639_000                          # [Ambulance Oost] ~639k, 14 municipalities
N_MUNICIPALITIES = 14                         # [Ambulance Oost]

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
# Shared handoff location for the incident stream: the teammate's generator
# writes here, the loader reads here. Override without editing code, e.g.:
#   INCIDENT_FILE=data/incident_sample.json solara run app.py
INCIDENT_FILE = os.environ.get("INCIDENT_FILE", "data/incident.json")

# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
TICK_MINUTES = 1.0        # one tick = one minute; response times come out in minutes

# ---------------------------------------------------------------------------
# Response-time norm (A1)  [RIVM/VZinfo]
# 15 min target = 3 min call-handling/dispatch + 12 min net drive; 95% of A1 calls.
# ---------------------------------------------------------------------------
A1_NORM_MIN = 15.0
DISPATCH_HANDLING_MIN = 3.0
DRIVE_BUDGET_MIN = 12.0
TARGET_PERCENTILE = 0.95

# Validation band for achieved 95th-percentile response  [RIVM/VZinfo]
# National 16:51; regional range 14:38..18:36. Calibrate baseline to ~15..17 min.
VALIDATION_P95_MIN_RANGE = (15.0, 17.0)

# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------
FLEET_TOTAL = 32          # [Ambulance Oost] 25 ambulances + 5 care + 2 rapid responders
N_AMBULANCES = 12         # [ASSUMPTION] concurrently-staffed A1 units; tune to hit the norm

# ---------------------------------------------------------------------------
# Travel  [ASSUMPTION — calibrate so coverage ~98% within 15 min]
# travel_time_min = (euclidean_km * DETOUR_FACTOR) / EFFECTIVE_SPEED_KMH * 60
# ---------------------------------------------------------------------------
EFFECTIVE_SPEED_KMH = 60.0
DETOUR_FACTOR = 1.3

# ---------------------------------------------------------------------------
# Demand  [Ambulance Oost] + [RIVM/VZinfo]
# ~45,000 dispatches/year for Twente (all urgencies); ~half urgent (A0+A1).
# Incidents come from incident.json; these drive load-scaling / any generator.
# ---------------------------------------------------------------------------
DISPATCHES_PER_YEAR = 45_000     # [Ambulance Oost]
URGENT_FRACTION = 0.5            # [RIVM/VZinfo-derived] A0+A1 share of all dispatches
LOAD_FACTOR = 1.0               # multiply the incident stream to raise demand in a sweep

# ---------------------------------------------------------------------------
# Urgency / severity mix  [RIVM/VZinfo]  national counts 2025 (AZN Sectorkompas 2025)
# B = planned transport, excluded from the emergency model.
# ---------------------------------------------------------------------------
URGENCY_COUNTS_NL_2025 = {"A0": 28_159, "A1": 724_732, "A2": 452_611, "B": 308_686}

_emerg = {k: URGENCY_COUNTS_NL_2025[k] for k in ("A0", "A1", "A2")}
_total = sum(_emerg.values())
SEVERITY_MIX = {k: round(v / _total, 3) for k, v in _emerg.items()}  # ~A0 .023 A1 .601 A2 .375

# Per-severity behaviour  [ASSUMPTION — calibrate, except A0 which is sourced below]
# on_scene time is drawn from a (truncated) normal: mean +/- sd, minimum 1 min.
# immediate_dispatch: A0 (arrest) skips bidding and sends the nearest unit now.
#
# A0 (out-of-hospital cardiac arrest) — values from the Amsterdam ARREST registry (NL):
#   - EMS resuscitates ON SCENE; it ends in transport (with/without ROSC) OR
#     termination on scene (declared dead, NO hospital trip). [ARREST 2020, 2021]
#   - ~54% do not achieve ROSC on scene; of those, most are terminated on scene
#     (2269) and a minority transported with ongoing CPR (921). [ARREST 2021]
#   - transport_prob ~0.5 = ROSC cases (~46%) + the minority transported with CPR.
#   - long on-scene time: median 25 min (IQR 19-32) before transport. [ARREST 2020]
#   Sources:
#     ARREST 2020  https://www.tandfonline.com/doi/full/10.1080/10903127.2020.1752868
#     ARREST 2021  https://www.resuscitationjournal.com/article/S0300-9572(21)00186-6/fulltext
#     NL registry  https://link.springer.com/article/10.1007/s12471-018-1162-9
SEVERITY_PROFILE = {
    "A0": {"on_scene_mean_min": 32.0, "on_scene_sd_min": 8.0, "transport_prob": 0.50, "immediate_dispatch": True},
    "A1": {"on_scene_mean_min": 15.0, "on_scene_sd_min": 4.0, "transport_prob": 0.80, "immediate_dispatch": False},
    "A2": {"on_scene_mean_min": 12.0, "on_scene_sd_min": 3.0, "transport_prob": 0.60, "immediate_dispatch": False},
}

# ---------------------------------------------------------------------------
# Coverage sanity check  [RIVM/VZinfo]  ~98.1% within 15 min (24/7); ~1.9% beyond
# ---------------------------------------------------------------------------
COVERAGE_WITHIN_NORM = 0.981

# ---------------------------------------------------------------------------
# HOSPITAL CAPACITY MODEL
# capacity = number of concurrent ED "servers" (beds/slots). A patient holds one
# server for a length of stay (LOS), then frees it. ED is "full" when occupied
# servers reach capacity.  [server/LOS model: DES-lit — Sun 2016, Kolker 2008]
# ---------------------------------------------------------------------------
# Length of stay: how long an admitted patient occupies a server.
HOSPITAL_LOS_MEAN_MIN = 210.0    # [ASSUMPTION ~3.5h] NL ED LOS is relatively short [NL-dashboard];
                                 #   LOS->diversion link from Kolker 2008 [DES-lit]
HOSPITAL_LOS_FLOOR_MIN = 60.0    # [ASSUMPTION] minimum stay

# Diversion: a hospital stops accepting new ambulances at this occupancy fraction,
# then stays on diversion for a fixed window before reopening.
DIVERSION_THRESHOLD = 0.90       # [ASSUMPTION; threshold-diversion mechanism: Wan et al. 2024, DES-lit]
DIVERSION_DURATION_MIN = 120.0   # [NL-dashboard] MAX diversion window (NL: 1-2h); cap, not fixed length
DIVERSION_CLEAR_THRESHOLD = 0.75 # [NL-dashboard] reopen early once crowding subsides below this

# Handover / offload (the ambulance's time at the hospital).
HANDOVER_MIN = 12.0              # [WAITED] normal handover; 95.6% of handovers were < 15 min
OFFLOAD_DELAY_MEDIAN_MIN = 16.0  # [WAITED] median offload delay when it occurs
OFFLOAD_DELAY_IQR_MIN = (10.0, 25.0)   # [WAITED] interquartile range
VALIDATION_OFFLOAD_RATE = 0.077  # [WAITED] 7.7% of arrivals met the offload-delay criterion (validation target)

# BOTH-FULL RULE (design note, not a single parameter):
# With only two EDs, if both are over the diversion threshold there is nowhere to
# divert. The ambulance then waits (patient boards on the ambulance) until a server
# frees, logged as an offload delay. This ties up the unit and feeds back into
# response times. Sources: offload-delay / ambulance-queueing [WAITED], [DES-lit].

# ---------------------------------------------------------------------------
# Coordination / channel
# ---------------------------------------------------------------------------
MODE = "centralized"     # "centralized" or "decentralized"; the only switch between conditions
BID_WINDOW_TICKS = 2     # [ASSUMPTION] ticks to collect bids before awarding (late bids missed)

# Communication reliability (resilience stress knobs) — default to perfect comms.
LOSS_PROB = 0.0
DELAY_TICKS = 0
DISPATCHER_OUTAGE = None  # e.g. (start_tick, end_tick) to block the dispatcher for a window

SEED = 42

# ---------------------------------------------------------------------------
# Ambulance posts  [Ambulance Oost]  (approximate town-centre lat/lon)  — 11 posts
# ---------------------------------------------------------------------------
POSTS_LATLON = {
    "Almelo":        (52.357, 6.662),
    "Enschede":      (52.221, 6.893),
    "Enschede-oost": (52.223, 6.945),
    "Goor":          (52.231, 6.583),
    "Haaksbergen":   (52.159, 6.742),
    "Hengelo":       (52.265, 6.793),
    "Markelo":       (52.244, 6.513),
    "Nijverdal":     (52.363, 6.462),
    "Oldenzaal":     (52.313, 6.928),
    "Tubbergen":     (52.408, 6.777),
    "Vroomshoop":    (52.448, 6.567),
}

# ---------------------------------------------------------------------------
# Emergency hospitals — only the two with a 24/7 ED (SEH).
# ZGT Hengelo EXCLUDED: its ED closed in 2018. capacity = concurrent ED servers [ASSUMPTION].
# ---------------------------------------------------------------------------
HOSPITALS_LATLON = {
    "MST Enschede": {"lat": 52.211, "lon": 6.881, "capacity": 8},  # large topclinical hospital
    "ZGT Almelo":   {"lat": 52.345, "lon": 6.672, "capacity": 5},  # ~30k SEH visits/yr
}

# ---------------------------------------------------------------------------
# Projection: lat/lon -> local km grid (equirectangular, fine at this scale)
# ---------------------------------------------------------------------------
_LAT_REF = 52.30
_KM_PER_DEG_LAT = 111.19
_KM_PER_DEG_LON = 111.19 * cos(radians(_LAT_REF))
_ORIGIN_LAT = 52.08
_ORIGIN_LON = 6.38
_MARGIN_KM = 3.0


def xy_to_latlon(x, y):
    """Inverse of latlon_to_xy: local km grid -> (lat, lon)."""
    lon = x / _KM_PER_DEG_LON + _ORIGIN_LON
    lat = y / _KM_PER_DEG_LAT + _ORIGIN_LAT
    return (lat, lon)


def latlon_to_xy(lat, lon):
    """Return (x_km, y_km) on the local grid for a lat/lon."""
    x = (lon - _ORIGIN_LON) * _KM_PER_DEG_LON
    y = (lat - _ORIGIN_LAT) * _KM_PER_DEG_LAT
    return (x, y)


POSTS_XY = {name: latlon_to_xy(lat, lon) for name, (lat, lon) in POSTS_LATLON.items()}
HOSPITALS_XY = {
    name: {"pos": latlon_to_xy(h["lat"], h["lon"]), "capacity": h["capacity"]}
    for name, h in HOSPITALS_LATLON.items()
}

_all_xy = list(POSTS_XY.values()) + [h["pos"] for h in HOSPITALS_XY.values()]
SPACE_WIDTH_KM = max(x for x, _ in _all_xy) + _MARGIN_KM
SPACE_HEIGHT_KM = max(y for _, y in _all_xy) + _MARGIN_KM


def travel_time_min(km):
    """Convert a straight-line distance (km) to travel time (minutes)."""
    return (km * DETOUR_FACTOR) / EFFECTIVE_SPEED_KMH * 60.0


# ---------------------------------------------------------------------------
# REFERENCES (for the provenance tags above)
# ---------------------------------------------------------------------------
# [RIVM/VZinfo]  Ambulancezorg, regionaal. vzinfo.nl.
#     https://www.vzinfo.nl/acute-zorg/regionaal/ambulancezorg
# [Ambulance Oost]  Ambulance Oost (RAV Twente). https://ambulanceoost.nl
# [WAITED]  Waiting time ambulances in the Emergency Department; a Dutch single
#     center study (WAITED study). Int J Emerg Med, 2025.
#     https://link.springer.com/article/10.1186/s12245-025-01068-y
# [NL-dashboard]  Emergency department crowding in the Netherlands; evaluation of
#     a real-time ambulance diversion dashboard. Int J Emerg Med, 2025.
#     https://link.springer.com/article/10.1186/s12245-024-00784-1
# [DES-lit] Kolker A. Process Modeling of ED Patient Flow: Effect of Patient LOS
#     on ED Diversion. J Medical Systems, 2008.
#     https://link.springer.com/article/10.1007/s10916-008-9144-x
# [DES-lit] Sun X. Modeling the Emergency Care Delivery System Using a Queueing
#     Approach. Univ. of Waterloo (thesis).
# [DES-lit] Wan et al. Prediction-Enhanced Monte Carlo (two-hospital threshold
#     diversion). arXiv:2412.11257 (preprint).
# [DES-lit] A Realistic DES model for Ambulance Location and Deployment within a
#     regional EMS. arXiv:2604.24394 (preprint).
# NOTE: WAITED is single-centre; the dashboard study is national scope. The
# server/LOS/threshold mechanics are DES/queueing concepts implemented here in a
# tick-based ABM (our own design choice; no cited source is agent-based).

if __name__ == "__main__":
    print(f"Region: {REGION_NAME}  |  space = {SPACE_WIDTH_KM:.1f} x {SPACE_HEIGHT_KM:.1f} km")
    print(f"Severity mix (A0/A1/A2): {SEVERITY_MIX}")
    print(f"Hospital LOS mean: {HOSPITAL_LOS_MEAN_MIN} min  | diversion >= {DIVERSION_THRESHOLD:.0%} for {DIVERSION_DURATION_MIN} min")
    print(f"Handover {HANDOVER_MIN} min | offload median {OFFLOAD_DELAY_MEDIAN_MIN} min (IQR {OFFLOAD_DELAY_IQR_MIN})")
    print("\nPosts (x_km, y_km):")
    for name, (x, y) in POSTS_XY.items():
        print(f"  {name:<14} ({x:5.1f}, {y:5.1f})")
    print("\nHospitals (x_km, y_km, capacity):")
    for name, h in HOSPITALS_XY.items():
        x, y = h["pos"]
        print(f"  {name:<14} ({x:5.1f}, {y:5.1f})  cap={h['capacity']}")