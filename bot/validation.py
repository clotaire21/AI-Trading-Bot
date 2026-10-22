"""Renew an already established connection, without retuning the holdout."""
from pathlib import Path
import subprocess
import sys
from .alpaca import SafetyError
from .config import SYMBOLS
from .risk import account_values
from .runner import account_hash
from .state import load, code_hash, atomic_json, now


def renew(client, directory):
    # These are harmless tests with no secret/network dependency.
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], check=True)
    directory = Path(directory)
    proof = load(directory / "validation.json")
    research = load(directory / "research.json")
    state = load(directory / "state.json")
    account, positions = client.account(), client.positions()
    account_values(account, positions)
    if (not proof.get("connection_passed") or not proof.get("safety_tests_passed") or
        proof.get("code_sha256") != code_hash() or
        proof.get("account_hash") != account_hash(account) or
        state.get("account_hash") != account_hash(account) or
        proof.get("research_data_sha256") != research.get("data_sha256") or
        not research.get("research_gate_passed")):
        raise SafetyError("Cannot renew missing, changed-code or unvalidated paper evidence")
    for symbol in SYMBOLS:
        asset = client.asset(symbol)
        if not (asset.get("tradable") and asset.get("fractionable") and asset.get("status") == "active"):
            raise SafetyError("Asset eligibility changed")
    # Full fills/cash/quantity reconciliation is performed by cycle BEFORE POST.
    # This renews connection/tests only; the original research report is immutable.
    proof.setdefault("initial_validated_at", proof["at"])
    proof["at"] = now()
    proof["research_gate_passed"] = True
    proof["renewal"] = "same_code_same_account_fresh_tests_read_only"
    atomic_json(directory / "validation.json", proof)
    return proof
