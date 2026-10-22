# Validation et limites

## Contrôles reproductibles

Commande : `python -m unittest discover -s tests -v` (Python 3.12).

Résultat local au 22 octobre 2026 : **34 tests réussis**, sans accès aux clés
réelles. Vérification de syntaxe YAML, scripts shell et compilation Python réussie.

Les tests couvrent les endpoints, secrets absents, redirections, données payantes,
payload limite DAY paper, pagination, tailles, espèces, ventes à découvert,
preuves périmées ou liées à un autre code/compte, kill switch, compte 100 000 USD,
barres périmées, décalage d'horloge, doublons, réponse POST ambiguë, exécution
partielle, reprise shadow, intégrité du journal, écriture/relecture de la branche
d'état sans modification de main, données corrompues, absence d'anticipation,
gaps, frais, maintien de la V1 et reproductibilité des empreintes.

Un essai de bout en bout du moteur compare 300 séances synthétiques, puis rejoue
leur export OHLCV via le CLI. Il sert à vérifier la chaîne complète ; ces données
ne sont pas des cours de marché. Aucun rapport synthétique n'autorise le trading.

## Ce qui n'est pas encore prouvé

- Les tests réseau utilisent des mocks. Les clés réelles restent dans GitHub et
  ne sont ni lisibles ni disponibles dans l'environnement local.
- La facturation GitHub n'est pas accessible au connecteur. Le verrou de variable
  n'empêche pas techniquement une facture si l'attestation est fausse.
- Aucune stratégie n'est déclarée supérieure au S&P 500 sans le rapport IEX réel.
- IEX ne représente pas toutes les places américaines. Les barres manquantes
  communes aux trois symboles ne sont pas détectées comme des trous par un
  calendrier externe ; elles restent des gaps entre observations.
- Les données ajustées sont révisables. Le fichier brut et son empreinte sont
  sauvegardés pour pouvoir reproduire une comparaison précise. Les indicateurs
  sont des ratios/prix relatifs ; aucun estimateur n'est ajusté sur le test final.
- L'univers fixe de trois ETF n'est pas un backtest de sélection de tout le marché.
- Le holdout unique n'autorise pas des réoptimisations répétées. Les résultats
  walk-forward restent descriptifs, avec fenêtres de test successives ; leurs
  choix n'utilisent que les données antérieures.
- Les frais sont des hypothèses conservatrices, pas un barème réglementaire.
  Le slippage stressé ne reproduit pas toutes les conditions de marché.
- À raison d'un ordre par cycle, plusieurs sorties nécessaires peuvent prendre
  plusieurs heures. Les seuils et la durée maximale sont observés périodiquement,
  non garantis ; un ordre limite peut ne pas se remplir.
- Le mode shadow journalise les décisions et observe le compte ; il ne simule
  pas un second portefeuille avec remplissages hypothétiques. Le backtest et le
  paper effectif fournissent les deux courbes de performance utiles.
- Le journal est chaîné pour détecter une altération accidentelle ; ce n'est pas
  une signature cryptographique contre un acteur pouvant réécrire tout le dépôt.
- Les preuves expirent après sept jours. Le workflow paper renouvelle automatiquement
  les tests et la connexion du même code/compte déjà validé, avec le même rapport
  de recherche. Une modification du code ou du compte bloque ce renouvellement ;
  il ne faut pas remettre artificiellement le compte à zéro pour contourner cela.

## Prochaine étape indispensable

Vérifier le blocage des dépenses Actions à 0 USD, attester
`FREE_ACTIONS_CONFIRMED=true`, puis lancer **preflight** sur main.
Il renverra uniquement des informations de connexion anonymisées et la
compatibilité du compte dédié. Poursuivre ensuite avec **validate**, puis lire les
preuves avant toute modification d'activation des ordres.
