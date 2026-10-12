"""
metrics.py — All the measures the study reports, computed from model state.

summary(model) returns the full end-of-run metric dict (used by the batch
experiments). The model also feeds a few of these into Mesa's DataCollector each
tick so they can be charted live.
"""

import math

import config

# City centres (lat, lon) -> km, to split incidents into urban vs rural.
_CITY_CENTRES_LATLON = [(52.221, 6.893), (52.265, 6.793), (52.357, 6.662)]  # Enschede, Hengelo, Almelo
_URBAN_RADIUS_KM = 6.0
_CENTRES_XY = [config.latlon_to_xy(lat, lon) for lat, lon in _CITY_CENTRES_LATLON]


def is_urban(pos):
    return any(math.hypot(pos[0] - cx, pos[1] - cy) <= _URBAN_RADIUS_KM
               for cx, cy in _CENTRES_XY)


def percentile(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p * len(s))) - 1))
    return s[k]


def gini(values):
    """Inequality of response times: 0 = everyone equal, higher = more unequal."""
    v = sorted(x for x in values if x is not None)
    n = len(v)
    if n == 0:
        return float("nan")
    total = sum(v)
    if total == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return (2 * cum) / (n * total) - (n + 1) / n


def _response_times(model):
    return [i.response_min for i in model.completed if i.response_min is not None]


def summary(model):
    r = _response_times(model)
    urban = [i.response_min for i in model.completed
             if i.response_min is not None and is_urban(i.pos)]
    rural = [i.response_min for i in model.completed
             if i.response_min is not None and not is_urban(i.pos)]
    offloads = [i.offload_min for i in model.completed if i.offload_min > 0]

    n_amb = max(len(model.ambulances), 1)
    denom = n_amb * max(model.clock, 1)
    sent = model.channel.sent_counts
    n_done = max(len(model.completed), 1)

    return {
        "mode": model.mode,
        "clock": model.clock,
        "completed": len(model.completed),
        "total": len(model.incidents),
        "unserved": len(model.incidents) - len(model.completed),
        # response time
        "resp_mean": (sum(r) / len(r)) if r else float("nan"),
        "resp_p90": percentile(r, 0.90),
        "resp_p95": percentile(r, 0.95),
        "within15_pct": (sum(x <= 15 for x in r) / len(r) * 100) if r else float("nan"),
        # fairness
        "resp_urban": (sum(urban) / len(urban)) if urban else float("nan"),
        "resp_rural": (sum(rural) / len(rural)) if rural else float("nan"),
        "fairness_gap": ((sum(rural) / len(rural)) - (sum(urban) / len(urban)))
                        if (urban and rural) else float("nan"),
        "gini": gini(r),
        # utilization
        "utilization_pct": model.busy_ticks / denom * 100,
        # hospitals
        "diversions": model.n_diversions,
        "offload_events": len(offloads),
        "offload_median": percentile(offloads, 0.50) if offloads else 0.0,
        # coordination overhead
        "msgs_total": sum(sent.values()),
        "bids": sent.get("BID", 0),
        "bids_per_incident": sent.get("BID", 0) / n_done,
    }