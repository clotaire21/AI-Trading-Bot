"""Dataset lineage for accidental misuse prevention, not an external signature."""
import hashlib
import json
from pathlib import Path
from .alpaca import SafetyError
from .state import code_hash

VERIFIED_ORIGINS = ("alpaca_iex_download", "alpaca_iex_replay")


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def replay_origin(raw, input_path, manifest_path=None):
    path = Path(manifest_path) if manifest_path else Path(input_path).with_name("research-manifest.json")
    if not path.exists():
        return {"kind": "unverified_local", "payload_sha256": payload_hash(raw)}
    manifest = json.loads(path.read_text())
    if (manifest.get("source") != "alpaca_iex_download" or manifest.get("feed") != "iex" or
        manifest.get("adjustment") != "all" or manifest.get("timeframe") != "1Hour" or
        manifest.get("payload_sha256") != payload_hash(raw)):
        raise SafetyError("Research replay does not match its Alpaca manifest")
    return {"kind": "alpaca_iex_replay", "payload_sha256": payload_hash(raw),
            "downloaded_at": manifest["downloaded_at"]}


def check_research_evidence(report, proof):
    if (report.get("schema") != 2 or report.get("code_sha256") != code_hash() or
        report.get("data_origin", {}).get("kind") not in VERIFIED_ORIGINS or
        not report.get("research_gate_passed") or
        proof.get("research_sha256") != payload_hash(report) or
        proof.get("research_data_sha256") != report.get("data_sha256")):
        raise SafetyError("Unverified, altered or incompatible research evidence")
