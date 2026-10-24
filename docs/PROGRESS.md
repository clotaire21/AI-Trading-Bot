# État du projet — 24 octobre 2026

## Réalisé et vérifié sans GitHub Actions

- Audit de la V1 et conservation de son fonctionnement.
- Trois stratégies, moteur de backtest et sélection chronologique.
- Exécuteur Alpaca Paper verrouillé, gestion du risque et état durable.
- 56 tests locaux réussis, dont non-régression, reprise après interruption,
  exécutions partielles, données périmées et absence de biais d'anticipation.
- Commande `selfcheck` : 15 scénarios/stratégies synthétiques, sans réseau, sans
  clé et sans ordre. Vérification du pipeline complet sur 300 séances synthétiques.
- Rapports JSON et Markdown rejouables, empreintes des données/code/rapport,
  refus de promouvoir une source locale non vérifiée.

Ces vérifications prouvent des propriétés du logiciel ; elles ne démontrent pas
la rentabilité des stratégies. Les chiffres synthétiques ne sont pas des
performances de marché.

## État réel obtenu

- Dépôt public ; clés Alpaca toujours limitées aux secrets GitHub.
- Connexion au compte Paper dédié de 2 000 USD confirmée en lecture seule.
- Historique IEX réel sauvegardé et reproductible sur la branche d'état.
- `breakout_12` : −2,85 % sur le test final, contre +7,55 % pour 60 % SPY + cash ;
  stress de coûts à −7,91 %. La promotion est correctement bloquée.
- Planning shadow activé ; le prochain créneau utile est une séance de marché.
  Aucun ordre Alpaca Paper n'est autorisé.

## Prochaines étapes

1. Accumuler de nouvelles observations sans réutiliser le test final comme preuve.
2. Comparer rendement, drawdown, coûts, régularité et référence 60 % SPY + cash.
3. Attendre au moins 60 séances et 30 allers-retours ; le rapport expose les
   critères encore bloquants pour chaque candidat.
4. Activer les ordres paper seulement si une stratégie passe réellement les critères.

`execution-policy.json` reste désactivée : aucune soumission d'ordre n'est possible.
