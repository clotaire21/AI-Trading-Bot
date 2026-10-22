# AI Trading Bot — laboratoire fictif

**Aucun investissement réel.** V1 sans ordre Alpaca : simulation locale d'une stratégie simple sur des données publiques. Les clés Alpaca ne sont PAS requises pour cette première étape.

## Principe
- Capital fictif : 2 000 USD
- Univers : SPY (ETF S&P 500) comme premier actif test
- Signaux : croisement de moyennes mobiles 10/30 jours, calculés uniquement avec les clôtures passées
- Achat/vente simulés à l'ouverture de séance suivante (proxy : prix d'ouverture Yahoo Finance)
- Frais et slippage simulés : 0,10 % par transaction
- Aucun levier, aucun ordre réel, aucun endpoint de trading
- Comparaison à l'achat-conservation

## Lancer
```bash
pip install -r requirements.txt
python simulate.py
```
Ou GitHub > Actions > Paper simulation (manual only) > Run workflow.

## Limites
Cette stratégie est un simple banc d'essai, **pas une stratégie validée ni une IA prédictive**. Les données Yahoo via yfinance peuvent être retardées/ajustées; un backtest n'est pas du paper trading en temps réel. Les performances futures sont inconnues. Aucun horaire automatique n'est activé.

## Suite
Une fois le code et ses tests validés, ajouter une connexion Alpaca **paper uniquement**, un registre durable des ordres fictifs et des garde-fous; ne jamais utiliser les identifiants live.
