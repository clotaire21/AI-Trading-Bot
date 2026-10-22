# État du projet — 22 octobre 2026

## Réalisé et vérifié sans GitHub Actions

- Audit de la V1 et conservation de son fonctionnement.
- Trois stratégies, moteur de backtest et sélection chronologique.
- Exécuteur Alpaca Paper verrouillé, gestion du risque et état durable.
- 43 tests locaux réussis, dont non-régression, reprise après interruption,
  exécutions partielles, données périmées et absence de biais d'anticipation.
- Commande `selfcheck` : 15 scénarios/stratégies synthétiques, sans réseau, sans
  clé et sans ordre. Vérification du pipeline complet sur 300 séances synthétiques.
- Rapports JSON et Markdown rejouables, empreintes des données/code/rapport,
  refus de promouvoir une source locale non vérifiée.

Ces vérifications prouvent des propriétés du logiciel ; elles ne démontrent pas
la rentabilité des stratégies. Les chiffres synthétiques ne sont pas des
performances de marché.

## Blocages extérieurs

Le budget Actions du dépôt est à 0 USD avec usage bloqué, d'après la capture
fournie par l'utilisateur. Les minutes et le stockage inclus du compte sont
épuisés. Aucun crédit payant n'est ajouté et la visibilité du dépôt reste privée.

Les clés Alpaca se trouvent uniquement dans les secrets GitHub. La connexion
authentifiée et le téléchargement IEX réel restent à vérifier dans un environnement
autorisé disposant de ces secrets. Les secrets GitHub ne sont pas extractibles
par le connecteur. Le code et les tests locaux peuvent continuer à évoluer.

## Prochaines étapes lors du déblocage

1. Preflight en lecture seule et confirmation du compte dédié vierge de 2 000 USD.
2. Recherche IEX réelle et examen du test final/stress de coûts.
3. Observation shadow ; rapprochement des signaux, prix et horaires réels.
4. Activation versionnée des ordres paper seulement si les preuves passent.

`execution-policy.json` reste désactivée et le planning n'est pas activé.
