from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from .alpaca import ReadOnlyPaper, ExecutionPaper, SafetyError
from .data import frames_from_bars
from .research import compare, write_report
from .runner import probe, cycle
from .state import atomic_json, append_event, code_hash, load, now


def main():
    parser = argparse.ArgumentParser(description="Paper-only research lab; orders disabled by default")
    parser.add_argument("command", choices=("probe", "research", "validate", "renew", "shadow", "paper"))
    parser.add_argument("--state-dir", default="runtime")
    parser.add_argument("--input", help="Replay a saved Alpaca bar JSON for offline research")
    args = parser.parse_args()
    directory = Path(args.state_dir)
    try:
        if args.command == "probe":
            report = probe(ReadOnlyPaper(), directory)
            print(json.dumps(report, indent=2))
        elif args.command == "research":
            if args.input:
                raw = load(args.input)
            else:
                client = ReadOnlyPaper()
                end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                raw = client.bars("2023-01-01T00:00:00Z", end.isoformat(), "all")
                atomic_json(directory / "research-input.json", raw)
                atomic_json(directory / "research-manifest.json", {
                    "downloaded_at": now(), "end": end.isoformat(), "start": "2023-01-01T00:00:00Z",
                    "feed": "iex", "adjustment": "all", "timeframe": "1Hour"})
            write_report(compare(frames_from_bars(raw)), directory)
            print((directory / "research.md").read_text())
        elif args.command == "validate":
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], check=True)
            report = probe(ReadOnlyPaper(), directory)
            research = load(directory / "research.json")
            proof = {"at": now(), "code_sha256": code_hash(), "safety_tests_passed": True,
                "account_hash": report["account_hash"],
                "connection_passed": report["dedicated_2000_account_ready"],
                "research_data_sha256": research["data_sha256"],
                "research_gate_passed": research["research_gate_passed"]}
            atomic_json(directory / "validation.json", proof)
            print(json.dumps(proof, indent=2))
        elif args.command == "renew":
            from .validation import renew
            print(json.dumps(renew(ReadOnlyPaper(), directory), indent=2))
        else:
            execute = args.command == "paper"
            policy = load("execution-policy.json")
            client = ExecutionPaper() if execute else ReadOnlyPaper()
            cycle(client, directory, policy, execute=execute)
    except (SafetyError, ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        # Record a sanitized failure. Exception messages from HTTP never contain credentials.
        error = {"event": "failure", "command": args.command, "type": type(exc).__name__}
        if isinstance(exc, SafetyError):
            error["reason"] = str(exc)
        append_event(directory, error)
        print(json.dumps(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
