"""Only print known, sanitized performance/evidence fields to Actions summary."""
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
print('# Paper lab\n')
for name, fields in {
    'connection.json': ('at', 'read_only', 'cash_usd', 'equity_usd', 'dedicated_2000_account_ready'),
    'validation.json': ('at', 'safety_tests_passed', 'connection_passed', 'research_gate_passed'),
    'performance.json': ('bar', 'equity_usd', 'net_modeled_equity_usd', 'return_pct', 'net_return_pct',
                         'spy_price_benchmark_usd', 'spy_return_pct', 'max_drawdown_pct', 'halted', 'daily_halt'),
}.items():
    path = directory / name
    if path.exists():
        data = json.loads(path.read_text())
        print(f'### {name}\n\n| Field | Value |\n|---|---|')
        for key in fields:
            print(f'| {key} | {data.get(key)} |')
        print()
research = directory / 'research.md'
if research.exists():
    print(research.read_text())
