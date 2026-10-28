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

def _stats(values, prefix):
    """Mean / p90 / p95 / % within the 15-min norm / variance / Gini for one group."""
    n = len(values)
    mean = (sum(values) / n) if n else float("nan")
    return {
        f"{prefix}_n": n,
        f"{prefix}_resp_mean": mean,
        f"{prefix}_resp_p90": percentile(values, 0.90),
        f"{prefix}_resp_p95": percentile(values, 0.95),
        f"{prefix}_within15_pct": (sum(x <= config.A1_NORM_MIN for x in values) / n * 100) if n else float("nan"),
        f"{prefix}_resp_var": (sum((x - mean) ** 2 for x in values) / (n - 1)) if n > 1 else float("nan"),
        f"{prefix}_gini": gini(values),
    }


def window_summary(model, since_tick=0, until_tick=None, handling_min=0.0):
    """summary(model) plus metrics restricted to incidents CREATED in [since_tick, until_tick).

    Used by calibrate.py / run_experiments.py (not per tick). Differences from summary():
      - a warm-up can be excluded (hospitals start empty, so early calls are unrealistically easy);
      - handling_min is added to every response (default 0: call processing is now simulated
        inside the model, config.DISPATCH_HANDLING_MIN, so responses already run from the call);
      - a call never reached by the end of the run counts with the time it had waited so
        far (a lower bound), so overload is not hidden by only averaging the lucky calls;
      - 'urg_*' = A0+A1 (the calls the 15-min norm applies to); 'a2_*' = A2 (30-min norm [AZN 2019]);
        'all_*' = A0+A1+A2; urg_wait_assign_mean = minutes from the call to unit assigned
        (call processing + any queueing + any bidding window); *_wait_operator_* = minutes a
        call waited for a free operator before processing began (centralized only).
    """
    out = summary(model)
    end = model.clock if until_tick is None else until_tick
    win = [i for i in model.incidents if since_tick <= i.created_tick < end]

    def resp(i):
        r = i.response_min if i.response_min is not None else model.clock - i.created_tick
        return r + handling_min

    urgent = [i for i in win if i.code in ("A0", "A1")]
    out.update(_stats([resp(i) for i in urgent], "urg"))
    out.update(_stats([resp(i) for i in win], "all"))
    out.update(_stats([resp(i) for i in win if i.code == "A2"], "a2"))
    out["a2_within30_pct"] = (sum(resp(i) <= 30 for i in win if i.code == "A2")
                              / max(out["a2_n"], 1) * 100)
    out["urg_wait_assign_mean"] = (sum((i.assigned_tick if i.assigned_tick is not None else model.clock)
                                       - i.created_tick for i in urgent) / len(urgent)) if urgent else float("nan")

    # time waiting for a free operator (centralized; 0 in decentralized), and the longest queue
    def op_wait(i):
        return (i.answered_tick if i.answered_tick is not None else model.clock) - i.created_tick
    out["urg_wait_operator_mean"] = (sum(op_wait(i) for i in urgent) / len(urgent)) if urgent else float("nan")
    out["all_wait_operator_mean"] = (sum(op_wait(i) for i in win) / len(win)) if win else float("nan")
    out["all_wait_operator_p95"] = percentile([op_wait(i) for i in win], 0.95)
    out["max_call_queue"] = model.max_call_queue

    urb = [resp(i) for i in urgent if is_urban(i.pos)]
    rur = [resp(i) for i in urgent if not is_urban(i.pos)]
    out["urg_resp_urban"] = (sum(urb) / len(urb)) if urb else float("nan")
    out["urg_resp_rural"] = (sum(rur) / len(rur)) if rur else float("nan")
    out["urg_fairness_gap"] = out["urg_resp_rural"] - out["urg_resp_urban"]

    out["win_total"] = len(win)
    out["win_unreached"] = sum(1 for i in win if i.on_scene_tick is None)
    out["win_unserved"] = sum(1 for i in win if i.closed_tick is None)
    out["win_unserved_pct"] = (out["win_unserved"] / len(win) * 100) if win else float("nan")

    # offload rate = share of hospital arrivals that had to wait (WAITED-style definition)
    transported = [i for i in win if i.closed_tick is not None and i.transport_needed]
    offl = [i.offload_min for i in transported if i.offload_min > 0]
    out["win_transported"] = len(transported)
    out["win_offload_events"] = len(offl)
    out["win_offload_rate_pct"] = (len(offl) / len(transported) * 100) if transported else float("nan")
    out["win_offload_median"] = percentile(offl, 0.50) if offl else 0.0
    return out
