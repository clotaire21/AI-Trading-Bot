"""Deterministic synthetic scenarios. No keys, sockets or broker objects.

This is a safety/reproducibility check, NOT a market-performance experiment.
Synthetic returns must never be considered promotion evidence.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from .backtest import run
from .config import LIMITS, SYMBOLS
from .data import fingerprint
from .research import compare
from .state import atomic_json, code_hash
from .strategies import STRATEGIES

SCENARIOS = ("flat", "rising", "falling", "volatile", "crash")


def scenario(name, days=80, seed=42):
    if name not in SCENARIOS or days < 10:
        raise ValueError("Unknown/insufficient offline scenario")
    dates = pd.bdate_range("2023-01-02", periods=days)
    local = [d + pd.Timedelta(hours=h) for d in dates for h in range(10, 16)]
    index = pd.DatetimeIndex(local).tz_localize("America/New_York").tz_convert("UTC")
    n, rng = len(index), np.random.default_rng(seed)
    t = np.arange(n)
    result = {}
    for i, symbol in enumerate(SYMBOLS):
        if name == "flat": close = np.full(n, 100.)
        elif name == "rising": close = 100 * np.exp(t * .0005)
        elif name == "falling": close = 100 * np.exp(-t * .0005)
        elif name == "volatile": close = 100 * np.exp(np.cumsum(rng.normal(0, .006, n)))
        else:
            close = 100 * np.exp(t * .0002)
            close[n // 3:] *= .65
        # Each next bar opens at its previous close, apart from a sudden crash
        # gap. Signal prices are not replaced with stop prices.
        opening = np.r_[close[0], close[:-1]]
        if name == "crash": opening[n // 3] = close[n // 3]
        multiplier = 1 + i * .25
        result[symbol] = pd.DataFrame({"Open": opening * multiplier,
            "High": np.maximum(opening, close) * multiplier * 1.001,
            "Low": np.minimum(opening, close) * multiplier * .999,
            "Close": close * multiplier, "Volume": np.full(n, 10000.)}, index=index)
    return result


def selfcheck(directory):
    cases = []
    for name in SCENARIOS:
        data = scenario(name)
        for strategy in STRATEGIES:
            result = run(data, strategy)
            buys = [t for t in result["trades"] if t["side"] == "buy"]
            if any(t["qty"] * t["price"] > LIMITS.capital * LIMITS.position + .00001 for t in buys):
                raise AssertionError("Offline entry exceeds position cap")
            halt = next((t["timestamp"] for t in result["trades"] if t["reason"] == "drawdown_halt"), None)
            if halt and any(pd.Timestamp(t["timestamp"]) >= pd.Timestamp(halt) for t in buys):
                raise AssertionError("Offline entry after drawdown suspension")
            cases.append({"scenario": name, "strategy": strategy, "data_sha256": fingerprint(data),
                          "halted": result["halted"], "metrics": result["metrics"]})
    # Also exercise the entire chronological train/validation/holdout pipeline.
    research = compare(scenario("volatile", days=300), origin={"kind": "synthetic"})
    if research["research_gate_passed"] or "unverified_data_provenance" not in research["blockers"]:
        raise AssertionError("Synthetic data must not authorize paper execution")
    report = {"schema": 1, "synthetic_only": True, "network_used": False,
              "orders_submitted": 0, "execution_authorized": False,
              "seed": 42, "code_sha256": code_hash(), "cases": cases,
              "chronological_pipeline": {"selected_on_validation": research["selected_on_validation"],
                  "research_gate_passed": False, "blockers": research["blockers"],
                  "data_sha256": research["data_sha256"]}}
    out = Path(directory)
    atomic_json(out / "selfcheck.json", report)
    rows = ["# Offline safety scenarios", "", "**Synthetic data only — no claim about market returns.**",
            "No broker connection or order submission. This report cannot authorize trading.", "",
            "| Scenario | Strategy | Orders | Drawdown % | Suspended |",
            "|---|---|---:|---:|---|"]
    for case in cases:
        m = case["metrics"]
        rows.append(f"| {case['scenario']} | {case['strategy']} | {m['orders']} | {m['max_drawdown_pct']:.2f} | {case['halted']} |")
    rows += ["", "Full chronological research pipeline: passed technical execution; promotion blocked.",
             "", "Code hash: " + report["code_sha256"]]
    (out / "selfcheck.md").write_text("\n".join(rows) + "\n")
    return report
