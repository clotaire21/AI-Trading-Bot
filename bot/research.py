"""Fixed candidates, chronological 60/20/20 split, one untouched holdout.

No ML, tuning or selection on holdout. Expanding walk-forward diagnostics
use only preceding data to choose a candidate. Reports cannot activate orders.
"""
from dataclasses import replace
import json
from pathlib import Path
import pandas as pd
from .backtest import run, benchmark
from .config import LIMITS
from .data import align, fingerprint
from .strategies import STRATEGIES, WARMUP
from .provenance import VERIFIED_ORIGINS
from .state import code_hash


def score(result):
    m = result["metrics"]
    return m["return_pct"] + m["max_drawdown_pct"]


def compare(frames, *, origin=None):
    align(frames)
    idx = frames["SPY"].index
    # Split on whole NY sessions, preventing a shared session across sets.
    sessions = sorted(set(idx.tz_convert("America/New_York").date))
    if len(sessions) < 250:
        raise ValueError("At least 250 aligned sessions required")
    boundary = lambda n: idx[next(i for i, t in enumerate(idx) if t.tz_convert("America/New_York").date() == sessions[n])]
    a, b = boundary(int(len(sessions) * .60)), boundary(int(len(sessions) * .80))
    end = idx[-1] + pd.Timedelta(hours=1)
    train = {s: run(frames, s, idx[WARMUP], a) for s in STRATEGIES}
    validation = {s: run(frames, s, a, b) for s in STRATEGIES}
    selected = max(STRATEGIES, key=lambda s: score(validation[s]))
    test = run(frames, selected, b, end)
    stress = run(frames, selected, b, end, replace(LIMITS, slippage_bps=29))
    passive = benchmark(frames["SPY"], b, end)
    matched = benchmark(frames["SPY"], b, end, .60)
    # Descriptive validation walk-forward; never use the final holdout.
    walk = []
    for split in (.40, .50, .60, .70):
        left, right = boundary(int(len(sessions) * split)), boundary(int(len(sessions) * (split + .10)))
        prior = {s: run(frames, s, idx[WARMUP], left) for s in STRATEGIES}
        pick = max(STRATEGIES, key=lambda s: score(prior[s]))
        walk.append(dict(start=str(left), end=str(right), selected=pick,
                         metrics=run(frames, pick, left, right)["metrics"]))
    m = test["metrics"]
    reasons = []
    origin = origin or {"kind": "unverified_local"}
    if origin.get("kind") not in VERIFIED_ORIGINS: reasons.append("unverified_data_provenance")
    if m["days"] < 60: reasons.append("holdout_below_60_sessions")
    if m["round_trips"] < 30: reasons.append("holdout_below_30_round_trips")
    if m["return_pct"] <= 0: reasons.append("holdout_not_profitable")
    if m["return_pct"] <= matched["return_pct"]: reasons.append("does_not_beat_60pct_spy")
    if m["max_drawdown_pct"] < -LIMITS.drawdown * 100: reasons.append("drawdown_exceeds_limit")
    if stress["metrics"]["return_pct"] <= 0: reasons.append("fails_cost_stress")
    if test["halted"]: reasons.append("risk_circuit_breaker_triggered")
    return {"schema": 2, "data_sha256": fingerprint(frames), "code_sha256": code_hash(),
        "data_origin": origin, "feed": "iex" if origin.get("kind") in VERIFIED_ORIGINS else "unverified",
        "adjustment": "all" if origin.get("kind") in VERIFIED_ORIGINS else "unverified",
        "price_basis": "dividend_adjusted_research_proxy" if origin.get("kind") in VERIFIED_ORIGINS else "unknown_or_synthetic",
        "split": {"train_start": str(idx[WARMUP]), "validation_start": str(a),
                  "holdout_start": str(b), "end": str(end)},
        "assumptions": {"fee_bps_per_side": LIMITS.fee_bps, "slippage_bps_per_side": LIMITS.slippage_bps,
            "stress_slippage_bps_per_side": 29, "execution": "next_available_bar_open",
            "end_liquidation": "last_close_with_costs", "annualization": "daily_252"},
        "train": {s: r["metrics"] for s, r in train.items()},
        "validation": {s: r["metrics"] for s, r in validation.items()},
        "selected_on_validation": selected, "walk_forward_before_holdout": walk,
        "holdout": test, "stress": stress["metrics"], "spy_100pct": passive,
        "spy_60pct": matched, "research_gate_passed": not reasons, "blockers": reasons,
        "warning": "Research eligibility is not execution authorization; holdout reuse requires a new future sample."}


def write_report(report, directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    (out / "research.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    rows = ["# Quantitative research — 2,000 USD", "", "Results are specific to the supplied dataset; no forecast.",
            "Data origin: " + report["data_origin"]["kind"], "",
            "| Sample | Strategy | Return % | Max drawdown % | Round trips |",
            "|---|---|---:|---:|---:|"]
    for sample in ("train", "validation"):
        for name, m in report[sample].items():
            rows.append(f"| {sample} | {name} | {m['return_pct']:.2f} | {m['max_drawdown_pct']:.2f} | {m['round_trips']} |")
    for name, m in ((report["selected_on_validation"], report["holdout"]["metrics"]),
                    ("SPY 100%", report["spy_100pct"]), ("SPY 60% + cash", report["spy_60pct"])):
        rows.append(f"| holdout | {name} | {m['return_pct']:.2f} | {m['max_drawdown_pct']:.2f} | {m['round_trips']} |")
    rows += ["", "Research gate: " + str(report["research_gate_passed"]),
             "Blockers: " + ", ".join(report["blockers"]), "", "Data hash: " + report["data_sha256"],
             "", "Feed: " + report["feed"],
             "Declared price basis: " + report["price_basis"] + ". Paper fills and dividends differ. No automatic promotion."]
    (out / "research.md").write_text("\n".join(rows) + "\n")
