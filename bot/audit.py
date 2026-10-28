"""One-shot locked historical audit that can never authorize execution."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pandas as pd

from .alpaca import ReadOnlyPaper, SafetyError
from .backtest import benchmark, run
from .config import LIMITS
from .data import align_research, fingerprint, frames_from_bars
from .provenance import payload_hash
from .state import atomic_json, code_hash, load, now
from .strategies import AUDIT_STRATEGIES, SHADOW_WARMUP


PLAN_FILE = Path("accelerated-audit-plan.json")
LOCK_FILE = "accelerated-audit-lock.json"
INPUT_FILE = "accelerated-audit-input.json"
MANIFEST_FILE = "accelerated-audit-manifest.json"
REPORT_FILE = "accelerated-audit-report.json"


def _plan_hash(plan):
    payload = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_plan(plan):
    if (plan.get("schema") != 1 or
            plan.get("purpose") != "one_shot_pre_2023_resilience_check_no_promotion" or
            plan.get("start") != "2018-01-01T00:00:00Z" or
            plan.get("end") != "2023-01-01T00:00:00Z" or
            tuple(plan.get("strategies", ())) != AUDIT_STRATEGIES or
            plan.get("minimum_sessions") != 750 or
            plan.get("minimum_round_trips") != 30 or
            plan.get("stress_slippage_bps_per_side") != 29 or
            plan.get("benchmark_allocation") != .6):
        raise SafetyError("Accelerated audit plan changed after declaration")


def evaluate(frames, plan, lock):
    frames = align_research(frames)
    index = frames["SPY"].index
    if len(index) <= SHADOW_WARMUP:
        raise SafetyError("Insufficient accelerated audit history")
    start, end = index[SHADOW_WARMUP], index[-1] + pd.Timedelta(hours=1)
    matched = benchmark(frames["SPY"], start, end, plan["benchmark_allocation"])
    strategies = {}
    stressed_limits = replace(LIMITS, slippage_bps=plan["stress_slippage_bps_per_side"])
    for name in AUDIT_STRATEGIES:
        normal = run(frames, name, start, end)
        stress = run(frames, name, start, end, stressed_limits)
        metrics = normal["metrics"]
        blockers = []
        if metrics["days"] < plan["minimum_sessions"]:
            blockers.append("below_750_sessions")
        if metrics["round_trips"] < plan["minimum_round_trips"]:
            blockers.append("below_30_round_trips")
        if metrics["return_pct"] <= 0:
            blockers.append("not_profitable")
        if metrics["return_pct"] <= matched["return_pct"]:
            blockers.append("does_not_beat_60pct_spy")
        if metrics["max_drawdown_pct"] < -LIMITS.drawdown * 100:
            blockers.append("drawdown_exceeds_limit")
        if stress["metrics"]["return_pct"] <= 0:
            blockers.append("fails_cost_stress")
        if normal["halted"] or stress["halted"]:
            blockers.append("risk_circuit_breaker_triggered")
        strategies[name] = {
            "metrics": metrics,
            "stress_metrics": stress["metrics"],
            "excess_vs_spy_60pct": metrics["return_pct"] - matched["return_pct"],
            "robustness_screen_passed": not blockers,
            "blockers": blockers,
        }
    leaderboard = sorted(AUDIT_STRATEGIES, key=lambda name: (
        strategies[name]["robustness_screen_passed"],
        strategies[name]["excess_vs_spy_60pct"],
        strategies[name]["stress_metrics"]["return_pct"],
        strategies[name]["metrics"]["max_drawdown_pct"],
    ), reverse=True)
    return {
        "schema": 1,
        "mode": "locked_historical_diagnostic_no_promotion",
        "created_at": now(),
        "locked_at": lock["locked_at"],
        "plan_sha256": lock["plan_sha256"],
        "code_sha256": lock["code_sha256"],
        "input_payload_sha256": lock["input_payload_sha256"],
        "data_sha256": fingerprint(frames),
        "period": {"start": str(start), "end": str(end)},
        "feed": "iex",
        "adjustment": "all",
        "spy_60pct": matched,
        "strategies": strategies,
        "leaderboard": leaderboard,
        "eligible_for_execution": False,
        "warning": "One-shot historical diagnostic only; it cannot authorize paper or live orders.",
    }


def run_locked_audit(client, directory, plan_path=PLAN_FILE):
    if type(client) is not ReadOnlyPaper:
        raise SafetyError("Accelerated audit requires the read-only broker client")
    directory = Path(directory)
    plan = load(plan_path)
    _validate_plan(plan)
    plan_digest = _plan_hash(plan)
    lock_path = directory / LOCK_FILE
    report_path = directory / REPORT_FILE
    if report_path.exists():
        raise SafetyError("Accelerated audit already completed; rerun forbidden")
    if lock_path.exists():
        lock = load(lock_path)
        if (lock.get("plan_sha256") != plan_digest or
                lock.get("code_sha256") != code_hash() or
                lock.get("attempts", 0) >= 3):
            raise SafetyError("Accelerated audit lock mismatch or retry limit reached")
        lock["attempts"] += 1
    else:
        lock = {"schema": 1, "locked_at": now(), "plan_sha256": plan_digest,
                "code_sha256": code_hash(), "attempts": 1,
                "status": "locked_before_download"}
    atomic_json(lock_path, lock)
    input_path = directory / INPUT_FILE
    manifest_path = directory / MANIFEST_FILE
    if input_path.exists():
        raw = load(input_path)
        manifest = load(manifest_path)
        digest = payload_hash(raw)
        if (lock.get("input_payload_sha256") != digest or
                manifest.get("payload_sha256") != digest or
                manifest.get("plan_sha256") != plan_digest):
            raise SafetyError("Accelerated audit input/manifest integrity failure")
    else:
        raw = client.bars(plan["start"], plan["end"], "all")
        digest = payload_hash(raw)
        lock["input_payload_sha256"] = digest
        lock["status"] = "download_complete"
        atomic_json(lock_path, lock)
        atomic_json(input_path, raw)
        atomic_json(manifest_path, {
            "downloaded_at": now(), "start": plan["start"], "end": plan["end"],
            "source": "alpaca_iex_download", "payload_sha256": digest,
            "feed": "iex", "adjustment": "all", "timeframe": "1Hour",
            "plan_sha256": plan_digest,
        })
    report = evaluate(frames_from_bars(raw), plan, lock)
    atomic_json(report_path, report)
    lock["status"] = "completed"
    lock["completed_at"] = now()
    atomic_json(lock_path, lock)
    return report
