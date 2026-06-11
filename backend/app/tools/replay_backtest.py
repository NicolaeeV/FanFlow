"""Replay backtester — calibrate the demand-wave model against real past event days.

The idea: 49ers home games at the SAME stadium are natural experiments for World Cup match
days. For each historical event day we have (a) the kickoff time and (b) an OBSERVED hourly
aggregate from fully-anonymous public data — PeMS freeway loop flow (US-101 / I-280), 511
transit ridership, or attendance proxies (odds/fixture data). We replay the day through our
forecast and score how well the predicted demand wave matches the observed one.

Honesty rules:
  - Observations must be PUBLIC AGGREGATES (loop detectors, ridership CSVs, line movements) —
    inherently anonymous, no individuals.
  - Offline, the bundled fixtures are ILLUSTRATIVE (clearly labeled) so the pipeline is
    testable; real calibration requires real PeMS/511/OddsPapi exports dropped into
    seed/data/replay_days.json with source attribution.
  - The output is a calibration report, never presented as proof the model is "right".
"""
from __future__ import annotations
import json
import pathlib
from .forecast import forecast_foot_traffic

_REPLAY_PATH = pathlib.Path(__file__).resolve().parents[2] / "seed" / "data" / "replay_days.json"


def load_replay_days() -> list:
    """Historical event days: [{day_id, label, kickoff_local, source, illustrative,
    observed_hourly: {"15:00": flow_index, ...}}]. Real data replaces/extends the bundled
    illustrative fixtures — same schema, with `illustrative: false` + a real `source`."""
    if not _REPLAY_PATH.exists():
        return []
    with open(_REPLAY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _peak_hour(series: dict) -> str | None:
    return max(series, key=series.get) if series else None


def _normalize(series: dict) -> dict:
    mx = max(series.values()) if series else 0
    return {k: (v / mx if mx else 0.0) for k, v in series.items()}


def score_day(day: dict, business_id: str = "biz_sofa_taqueria",
              match_id: str = "wc26_mex_ksa_2026-06-27") -> dict:
    """Replay one historical day: predicted hourly wave vs the observed aggregate.

    Metrics (simple + interpretable):
      - peak_hour_error_h: |predicted peak hour − observed peak hour|
      - shape_overlap: 1 − mean |normalized predicted − normalized observed| over shared hours
        (1.0 = identical wave shape, 0 = totally different)
    """
    fc = forecast_foot_traffic(business_id, match_id)
    predicted = {row["hour_local"]: row["expected_walkins_p50"] for row in fc.get("hours", [])}
    observed = dict(day.get("observed_hourly") or {})
    shared = sorted(set(predicted) & set(observed))
    if not shared:
        return {"day_id": day.get("day_id"), "comparable": False,
                "reason": "no overlapping hours between forecast and observation"}
    pn, on = _normalize({h: predicted[h] for h in shared}), _normalize({h: observed[h] for h in shared})
    shape_overlap = round(1 - sum(abs(pn[h] - on[h]) for h in shared) / len(shared), 3)
    p_peak, o_peak = _peak_hour(pn), _peak_hour(on)
    peak_err = abs(int(p_peak[:2]) - int(o_peak[:2])) if p_peak and o_peak else None
    return {
        "day_id": day.get("day_id"), "label": day.get("label"),
        "comparable": True, "hours_compared": len(shared),
        "predicted_peak": p_peak, "observed_peak": o_peak,
        "peak_hour_error_h": peak_err, "shape_overlap": shape_overlap,
        "observation_source": day.get("source"),
        "illustrative": bool(day.get("illustrative", True)),
    }


def run_replay(business_id: str = "biz_sofa_taqueria",
               match_id: str = "wc26_mex_ksa_2026-06-27") -> dict:
    """Replay every loaded historical day and summarize calibration quality. Honest: flags
    when ALL observations are illustrative (pipeline proven, model NOT yet calibrated)."""
    days = load_replay_days()
    results = [score_day(d, business_id, match_id) for d in days]
    comparable = [r for r in results if r.get("comparable")]
    all_illustrative = bool(days) and all(d.get("illustrative", True) for d in days)
    summary = {
        "days_total": len(days), "days_comparable": len(comparable),
        "mean_peak_error_h": (round(sum(r["peak_hour_error_h"] for r in comparable) / len(comparable), 2)
                              if comparable else None),
        "mean_shape_overlap": (round(sum(r["shape_overlap"] for r in comparable) / len(comparable), 3)
                               if comparable else None),
        "all_illustrative": all_illustrative,
        "calibration_status": ("pipeline_only — observations are illustrative; drop real PeMS/511/"
                               "odds exports into seed/data/replay_days.json to calibrate"
                               if all_illustrative else "calibrating_on_real_aggregates"),
    }
    return {"results": results, "summary": summary,
            "disclaimer": "Public aggregate observations only (loop detectors / ridership / "
                          "odds) — inherently anonymous. A calibration report, not a proof."}
