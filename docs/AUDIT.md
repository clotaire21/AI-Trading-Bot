# Audit du 22 octobre 2026

## État initial vérifié

- Dépôt privé `clotaire21/AI-Trading-Bot`, `main` à `bff4587b7a800082b744301a9b2f8200bc326484`.
- PR #1 fusionnée, workflow manuel #39785674714 réussi le 22 octobre 2026.
- Les logs confirment un téléchargement Yahoo puis le backtest V1. Aucun appel
  à Alpaca, aucun secret injecté dans ce workflow : ce vert ne valide pas les clés.
- Résultats historiques V1 dans ces logs : capital 3 305,05 USD (+65,25 %),
  benchmark 4 217,41 USD, drawdown −6,83 %, 954 barres quotidiennes. Ce sont des
  résultats de la V1 sur son ancienne fenêtre, pas des résultats du nouveau robot.

## Conservé

Backtest V1, décalage des signaux d'un jour, prix d'ouverture, coûts simples,
workflow manuel et dépendances legacy. L'import yfinance devient local à main()
pour permettre les tests hors réseau ; shift(fill_value=False) supprime un
avertissement pandas sans modifier les décisions. Deux tests de non-régression.

## Corrigé/ajouté

- V1 investissait jusqu'à 100 %, benchmark sans coûts et fenêtre différente
  du premier signal ; le moteur horaire utilise des plafonds, références
  contemporaines avec coûts et départs communs. La V1 reste une référence isolée.
- Client à domaines/routes/méthodes autorisés, GET isolés du POST paper,
  refus des redirections et des flux payants ; ni fallback live ni service LLM.
- Trois stratégies horaires fixes ; moteur chronologique, gaps, frais/slippage,
  sélection hors test, stress de coûts et rapports reproductibles.
- Exécuteur paper verrouillé : compte dédié 2 000 USD, espèces contrôlées,
  ordres limites plafonnés, suspensions, idempotence, rapprochement des exécutions
  partielles, détection d'interventions externes et état Git séparé.
- Tests automatisés, rapports de performance et verrous de gratuité des workflows.

## Résultat actuel

Le code est vérifié localement, avec transport Alpaca simulé dans les tests.
La recherche a été exécutée/rejouée sur un jeu synthétique déterministe : aucune
performance réelle ni connexion authentifiée n'est déduite de cet essai.

Les ordres restent désactivés. Restent à obtenir : garantie externe de blocage
des dépenses Actions, premier preflight utilisant les secrets GitHub, historique
IEX réel, rapport hors échantillon et observation du comportement shadow/paper.
Ces étapes peuvent révéler qu'aucune stratégie n'est suffisamment bonne : dans ce
cas, garder du cash et rester suspendu est le résultat attendu.

## Sources techniques vérifiées

- [Alpaca Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading) :
  endpoint dédié, IEX, différences de simulation, solde initial et création de compte.
- [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars) :
  pagination, IEX explicite et ajustements.
- [Alpaca fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading)
  et [ordres fractionnaires limites](https://alpaca.markets/blog/fractional-shares-trading-supports-limit-orders-and-extended-hours/).
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
  et [budgets bloquants](https://docs.github.com/en/billing/how-tos/set-up-budgets).

Les actions checkout/setup-python sont fixées aux commits des tags v6 récupérés
via GitHub le 22 octobre 2026. Pas de runner renforcé, cache ou abonnement ajouté.
