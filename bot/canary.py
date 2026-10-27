"""Isolated second-account PAPER canary for execution plumbing only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import re
import subprocess
import sys

from .alpaca import ExecutionPaper, ReadOnlyPaper, SafetyError
from .config import SYMBOLS
from .risk import account_values, number
from .runner import account_hash, cycle, probe
from .state import atomic_json, code_hash, load, now


PROOF_FILE = "canary-validation.json"
CANARY_STRATEGY = "trend_6_24"
# Explicit one-time path from the validated executor currently holding the
# canary position. A later code change must name its own reviewed predecessor.
CANARY_UPGRADE_PREDECESSORS = frozenset({
    "31e357916a0bbb7df545fc07ff8296952474e5ba5c981ee5d8d17288f7440504",
})


def validate_canary(client, directory, main_directory):
    if type(client) is not ReadOnlyPaper:
        raise SafetyError("Canary validation requires the read-only broker client")
    directory, main_directory = Path(directory), Path(main_directory)
    report = probe(client, directory)
    main = load(main_directory / "connection.json")
    main_hash = main.get("account_hash")
    if not isinstance(main_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", main_hash):
        raise SafetyError("Missing valid main shadow account identity")
    if not report["dedicated_2000_account_ready"]:
        raise SafetyError("Canary requires a new unused flat USD 2,000 paper account")
    if report["account_hash"] == main_hash:
        raise SafetyError("Canary account must differ from the shadow account")
    proof = {
        "schema": 1, "at": now(), "initial_validated_at": now(),
        "code_sha256": code_hash(), "safety_tests_passed": True,
        "connection_passed": True, "account_hash": report["account_hash"],
        "main_account_hash": main_hash,
        "mode": "operational_canary_only", "strategy": CANARY_STRATEGY,
        "performance_evidence": False,
    }
    atomic_json(directory / PROOF_FILE, proof)
    return proof


def renew_canary(client, directory):
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], check=True)
    directory = Path(directory)
    proof = load(directory / PROOF_FILE)
    state = load(directory / "state.json")
    account, positions = client.account(), client.positions()
    account_values(account, positions)
    identity = account_hash(account)
    if (proof.get("code_sha256") != code_hash() or
            not proof.get("safety_tests_passed") or
            not proof.get("connection_passed") or
            proof.get("mode") != "operational_canary_only" or
            proof.get("strategy") != CANARY_STRATEGY or
            proof.get("performance_evidence") is not False or
            proof.get("account_hash") != identity or
            proof.get("main_account_hash") == identity or
            state.get("account_hash") != identity):
        raise SafetyError("Cannot renew changed-code or mismatched canary evidence")
    for symbol in SYMBOLS:
        asset = client.asset(symbol)
        if not (asset.get("tradable") and asset.get("fractionable") and asset.get("status") == "active"):
            raise SafetyError("Canary asset eligibility changed")
    proof["at"] = now()
    proof["renewal"] = "same_code_same_second_account_fresh_tests_read_only"
    atomic_json(directory / PROOF_FILE, proof)
    return proof


def migrate_canary(client, directory, main_directory):
    """Re-attest a used canary account across one explicitly reviewed upgrade."""
    if type(client) is not ReadOnlyPaper:
        raise SafetyError("Canary migration requires the read-only broker client")
    directory, main_directory = Path(directory), Path(main_directory)
    proof = load(directory / PROOF_FILE)
    state = load(directory / "state.json")
    main = load(main_directory / "connection.json")
    account, positions, open_orders = client.account(), client.positions(), client.orders()
    cash, _, _ = account_values(account, positions)
    identity = account_hash(account)
    previous = proof.get("code_sha256")
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(proof["at"])
        observed = {p["symbol"]: Decimal(str(p["qty"])) for p in positions}
        tracked = {symbol: Decimal(str(qty))
                   for symbol, qty in state["tracked_quantities"].items()}
        tracked_cash = number(state["tracked_cash"])
    except (KeyError, TypeError, ValueError):
        raise SafetyError("Invalid canary migration evidence") from None
    if (previous not in CANARY_UPGRADE_PREDECESSORS or previous == code_hash() or
            not timedelta(0) <= age <= timedelta(days=7) or
            not proof.get("safety_tests_passed") or not proof.get("connection_passed") or
            proof.get("account_hash") != identity or state.get("account_hash") != identity or
            proof.get("main_account_hash") != main.get("account_hash") or
            proof.get("main_account_hash") == identity or
            proof.get("mode") != "operational_canary_only" or
            proof.get("strategy") != CANARY_STRATEGY or
            proof.get("performance_evidence") is not False or
            state.get("pending") is not None or open_orders or observed != tracked or
            abs(cash - tracked_cash) > .02):
        raise SafetyError("Canary migration state or predecessor mismatch")
    for value in (*observed.values(), *tracked.values()):
        if not value.is_finite() or value <= 0:
            raise SafetyError("Invalid canary migration quantity")
    for symbol in SYMBOLS:
        asset = client.asset(symbol)
        if not (asset.get("tradable") and asset.get("fractionable") and asset.get("status") == "active"):
            raise SafetyError("Canary asset eligibility changed")
    proof.update(schema=2, at=now(), code_sha256=code_hash(), migrated_from=previous,
                 renewal="reviewed_code_upgrade_same_account_reconciled_read_only")
    atomic_json(directory / PROOF_FILE, proof)
    return proof


def canary_gate(directory, policy, account):
    if os.environ.get("CANARY_KILL_SWITCH", "true") != "false":
        raise SafetyError("Canary kill switch is on (default)")
    if (policy.get("mode") != "operational_canary_only" or
            not policy.get("orders_enabled") or
            policy.get("strategy") != CANARY_STRATEGY):
        raise SafetyError("Canary order policy disabled")
    try:
        proof = load(Path(directory) / PROOF_FILE)
    except (OSError, ValueError):
        raise SafetyError("Missing/corrupt canary validation evidence") from None
    identity = account_hash(account)
    if (proof.get("code_sha256") != code_hash() or
            not proof.get("safety_tests_passed") or
            not proof.get("connection_passed") or
            proof.get("account_hash") != identity or
            proof.get("main_account_hash") == identity or
            proof.get("mode") != "operational_canary_only" or
            proof.get("strategy") != CANARY_STRATEGY or
            proof.get("performance_evidence") is not False):
        raise SafetyError("Missing or invalid canary safety evidence")
    age = datetime.now(timezone.utc) - datetime.fromisoformat(proof["at"])
    if not timedelta(0) <= age <= timedelta(days=7):
        raise SafetyError("Expired canary safety validation")


def canary_cycle(client, directory, policy, risk_only=False):
    if type(client) is not ExecutionPaper:
        raise SafetyError("Canary execution requires the PAPER execution client")
    return cycle(client, directory, policy, execute=True, gate=canary_gate,
                 risk_only=risk_only)
