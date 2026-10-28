"""Only print known, sanitized performance/evidence fields to Actions summary."""
import json
from pathlib import Path
import sys

directory = Path(sys.argv[1])
print('# Paper lab\n')
for name, fields in {
    'connection.json': ('at', 'read_only', 'cash_usd', 'equity_usd', 'dedicated_2000_account_ready'),
    'validation.json': ('at', 'safety_tests_passed', 'connection_passed', 'research_gate_passed'),
    'canary-validation.json': ('at', 'safety_tests_passed', 'connection_passed', 'mode',
                               'strategy', 'performance_evidence', 'renewal'),
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

shadow = directory / 'shadow-performance.json'
if shadow.exists():
    data = json.loads(shadow.read_text())
    print('### Forward shadow comparison (no orders)\n')
    print('| Rank | Strategy | Sessions | Equity | Return % | vs SPY % | Drawdown % | Costs | Trips | Gate | Blockers | Positions |')
    print('|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|')
    for name in ('trend_6_24', 'breakout_12', 'reversion_20',
                 'selective_reversion_20', 'trend_24_72', 'rsi25_trend',
                 'trend_pullback_rsi_stoch'):
        item = data.get('strategies', {}).get(name)
        if item:
            positions = ', '.join(item.get('positions', [])) or 'cash'
            blockers = ', '.join(item.get('blockers', [])) or 'none'
            rank = data.get('leaderboard', []).index(name) + 1
            gate = 'PASS' if item.get('forward_gate_passed') else 'WAIT'
            print(f"| {rank} | {name} | {int(item['sessions'])} | ${float(item['equity_usd']):.2f} | "
                  f"{float(item['return_pct']):.2f} | {float(item['excess_vs_spy_pct']):.2f} | "
                  f"{float(item['max_drawdown_pct']):.2f} | ${float(item['modeled_cost_usd']):.2f} | "
                  f"{int(item['round_trips'])} | {gate} | {blockers} | {positions} |")
    print("\nEach candidate is compared with 60% SPY + cash from its own start. "
          "These are modeled portfolios; no Alpaca order was sent.\n")

audit = directory / 'accelerated-audit-report.json'
if audit.exists():
    data = json.loads(audit.read_text())
    print('### Locked pre-2023 historical audit (diagnostic only)\n')
    print('| Rank | Strategy | Return % | Stress % | vs 60% SPY % | Drawdown % | Trips | Screen | Blockers |')
    print('|---:|---|---:|---:|---:|---:|---:|---|---|')
    for rank, name in enumerate(data.get('leaderboard', []), 1):
        item = data['strategies'][name]
        metrics, stress = item['metrics'], item['stress_metrics']
        screen = 'PASS' if item['robustness_screen_passed'] else 'FAIL'
        blockers = ', '.join(item['blockers']) or 'none'
        print(f"| {rank} | {name} | {float(metrics['return_pct']):.2f} | "
              f"{float(stress['return_pct']):.2f} | {float(item['excess_vs_spy_60pct']):.2f} | "
              f"{float(metrics['max_drawdown_pct']):.2f} | {int(metrics['round_trips'])} | "
              f"{screen} | {blockers} |")
    print('\nThis locked historical diagnostic cannot authorize any order.\n')
