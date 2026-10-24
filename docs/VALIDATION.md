# Validation et limites

## Contrôles reproductibles

Commande : `python -m unittest discover -s tests -v` (Python 3.12).

Résultat local au 24 octobre 2026 : **60 tests réussis**, sans accès aux clés
réelles. Vérification de syntaxe YAML, scripts shell et compilation Python réussie.

Les tests couvrent les endpoints, secrets absents, redirections, données payantes,
payload limite DAY paper, pagination, tailles, espèces, ventes à découvert,
preuves périmées ou liées à un autre code/compte, kill switch, compte 100 000 USD,
barres périmées, décalage d'horloge, doublons, réponse POST ambiguë, exécution
partielle, reprise shadow, portefeuilles virtuels prospectifs, refus d'un client
capable d'écrire en mode shadow, intégrité du journal, écriture/relecture de la branche
d'état sans modification de main, données corrompues, absence d'anticipation,
gaps, frais, maintien de la V1, verrouillage de l'audit accéléré, séparation du
compte canari et reproductibilité des empreintes.

Un essai de bout en bout du moteur compare 300 séances synthétiques, puis rejoue
leur export OHLCV via le CLI. Il sert à vérifier la chaîne complète ; ces données
ne sont pas des cours de marché. Aucun rapport synthétique n'autorise le trading.

Commande dédiée : `python -m bot selfcheck --state-dir results/offline`.
Elle exécute 15 combinaisons (marchés plat, haussier, baissier, volatil et krach ;
trois stratégies), plus la chaîne 60/20/20 sur 300 séances synthétiques. Un test
interdit explicitement la création de sockets et de client Alpaca pendant cette
commande. Les plafonds d'entrée et l'arrêt des achats après suspension sont
contrôlés. Le krach vérifie aussi qu'un gap peut dépasser le seuil de drawdown.

La provenance des données est vérifiée séparément : un fichier local sans
manifeste reste analysable, mais ne peut pas autoriser les ordres. Une modification
de son contenu invalide le manifeste. La preuve de sécurité contient l'empreinte
du rapport complet ; un rapport modifié ou produit avec un autre code est refusé.
Les nouveaux tests couvrent également un versement inexpliqué, un remplissage à
prix nul/négatif ou hors limite, et la persistance d'une suspension malgré une
panne de données.

## Ce qui n'est pas encore prouvé

- Les tests réseau utilisent des mocks. Les clés réelles restent dans GitHub et
  ne sont ni lisibles ni disponibles dans l'environnement local.
- La facturation GitHub n'est pas accessible au connecteur. Le verrou de variable
  n'empêche pas techniquement une facture si l'attestation est fausse.
- Le rapport IEX réel existe, mais aucune stratégie historique n'a passé tous les
  critères : la candidate retenue a perdu 2,85 % sur le test final et échoue au
  stress de coûts ainsi qu'à la comparaison 60 % SPY + cash.
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
- Le mode shadow maintient six portefeuilles virtuels prospectifs indépendants,
  avec remplissages modélisés à l'ouverture suivante et coûts hypothétiques. Il
  permet une comparaison homogène, mais ne reproduit pas les files d'attente ni
  les remplissages réels d'ordres limites Alpaca Paper.
- L'audit 2018–2022 est verrouillé avant téléchargement, limité à trois tentatives
  identiques en cas de panne et explicitement inéligible à l'exécution. Il apporte
  un diagnostic historique supplémentaire, pas une observation future.
- Le canari ne peut fonctionner qu'avec un second compte Paper, un code validé,
  une preuve récente, une politique dédiée et un coupe-circuit distinct. Sa
  stratégie fixe teste l'exécution et ne constitue pas une preuve de performance.
- Le journal est chaîné pour détecter une altération accidentelle ; ce n'est pas
  une signature cryptographique contre un acteur pouvant réécrire tout le dépôt.
- Les preuves expirent après sept jours. Le workflow paper renouvelle automatiquement
  les tests et la connexion du même code/compte déjà validé, avec le même rapport
  de recherche. Une modification du code ou du compte bloque ce renouvellement ;
  il ne faut pas remettre artificiellement le compte à zéro pour contourner cela.

## Prochaine étape indispensable

Exécuter une fois l'audit historique verrouillé, laisser `shadow` accumuler de
nouvelles observations et préparer séparément le compte canari. Après au moins
60 séances et 30 allers-retours, une candidate pourra passer aux ordres Paper ;
aucun de ces raccourcis n'autorise de capital réel.
