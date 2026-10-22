import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from .alpaca import SafetyError


def now():
    return datetime.now(timezone.utc).isoformat()


def code_hash():
    h = hashlib.sha256()
    paths = sorted(Path("bot").glob("*.py")) + sorted(Path("tests").glob("*.py"))
    paths += sorted(Path("tools").glob("*.py")) + sorted(Path("tools").glob("*.sh"))
    paths += sorted(Path(".github/workflows").glob("*.yml"))
    paths += [Path("requirements-research.txt"), Path("simulate.py")]
    for path in paths:
        h.update(str(path).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as out:
        json.dump(payload, out, indent=2, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def append_event(directory, event):
    path = Path(directory) / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = "0" * 64
    if path.exists():
        # Verify the whole existing journal before appending; do not reset it.
        for line in path.read_text().splitlines():
            item = json.loads(line)
            digest = item.pop("hash")
            if item["previous"] != previous or digest != hashlib.sha256(
                    json.dumps(item, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
                raise SafetyError("Journal hash chain mismatch")
            previous = digest
    entry = {"at": now(), "previous": previous, **event}
    entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with path.open("a") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")
        out.flush()
        os.fsync(out.fileno())


def load(path):
    return json.loads(Path(path).read_text())
