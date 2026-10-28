# AI Trading Bot — laboratoire Alpaca Paper

**Capital fictif : 2 000 USD. Ordres désactivés par défaut. Aucun trading réel.**

La V1 est conservée dans `simulate.py`. Le nouveau laboratoire ajoute une
connexion Alpaca en lecture seule, trois stratégies historiques, des backtests
chronologiques, des contrôles de risque et un exécuteur d'ordres **paper** verrouillé.
La connexion réelle en lecture seule est validée, mais aucune stratégie n'a encore
passé les critères de promotion. Aucun résultat synthétique ne constitue une
preuve de rentabilité.

## Risque et stratégies

| Règle | Limite initiale |
|---|---|
| Univers fixe, achats uniquement | SPY, QQQ, IWM |
| Position à l'entrée | au plus 20 % de min(2 000 USD, valeur nette) ; marge de sécurité 1 % |
| Exposition totale | 60 % ; réserve de trésorerie 40 % |
| Levier / ventes à découvert | interdits ; le buying power n'est jamais utilisé |
| Perte quotidienne | 2 % ; suspension des entrées jusqu'à la séance suivante |
| Drawdown | 8 % ; suspension persistante |
| Stop observé | 3 % par position ; watchdog nominal toutes les 15 min, soumis aux retards GitHub |
| Durée cible maximale | 18 barres horaires retenues, environ 3 séances |
| Ordres | un par cycle ; 6 entrées/sorties ordinaires au plus par jour ; sorties prioritaires autorisées au-delà |

Stratégies fixes : moyenne mobile 6/24 heures, cassure des 12 dernières barres,
retour à la moyenne avec z-score 20 barres. Aucun modèle payant ni appel à un LLM.
L'ajout de ML nécessitera un gain hors échantillon après coûts ; il n'est pas
nécessaire pour faire fonctionner ce laboratoire.

Le mode `shadow` suit en parallèle six portefeuilles virtuels distincts de
2 000 USD : les trois stratégies historiques et trois hypothèses pré-déclarées,
un retour à la moyenne plus sélectif, une tendance 24/72 heures et un achat sur
RSI(14) inférieur à 25 uniquement lorsque la tendance 24/72 reste positive. Ces
hypothèses ne sont pas ajoutées rétroactivement au test final déjà lu : elles
commencent à zéro lors de leur première observation future. Les signaux,
positions virtuelles, frais modélisés et performances sont conservés sans aucun
ordre envoyé à Alpaca.

Pour accélérer la validation sans diminuer les critères, deux voies sont ajoutées
en parallèle. L'audit historique verrouillé teste une seule fois les six règles
figées sur 2018–2022, période antérieure à la recherche principale démarrant en
2023. Son plan est versionné avant le téléchargement et son résultat ne peut
jamais autoriser un ordre. Un canari d'exécution séparé peut tester les véritables
ordres Alpaca Paper sur un **deuxième compte** de 2 000 USD. Il utilise une règle
fixe uniquement pour éprouver les remplissages, reprises et rapprochements ; sa
performance n'est jamais une preuve d'investissement.

Les plafonds s'appliquent aux ordres et aux observations périodiques. Les
variations de prix, gaps, limites non exécutées et interruptions peuvent dépasser
les seuils : **ils ne garantissent pas une perte maximale**.

## Démarrage gratuit et vérifiable

1. Vérifier dans **GitHub Settings → Billing and licensing → Budgets and alerts**
   qu'un arrêt des dépenses payantes Actions à **0 USD** couvre effectivement ce
   dépôt et le stockage. Un budget d'alerte ou un plafond de 3 USD n'est pas une
   garantie de gratuité. Le dépôt étant privé, les quotas sont partagés avec les
   autres dépôts. Ne pas modifier sa visibilité pour contourner ce point.
2. Après cette vérification seulement, créer la variable de dépôt
   `FREE_ACTIONS_CONFIRMED=true` dans **Settings → Secrets and variables → Actions → Variables**.
   Cette variable est une attestation, pas un contrôle de facturation.
3. Lancer **Actions → Paper lab — safety, research and execution → Run workflow**,
   branche `main`, commande **preflight**. Les tests passent avant tout accès
   aux secrets ; le programme utilise ensuite uniquement des requêtes GET.
4. Lire le résumé. Si Alpaca affiche le solde initial par défaut de 100 000 USD,
   la connexion peut fonctionner, mais le bot refusera de l'utiliser. Préparer un
   compte Paper dédié de 2 000 USD, sans position ni ordre historique, et mettre
   à jour les deux secrets si de nouvelles clés sont générées. Aucun reset n'est
   effectué par le code.
5. Lancer **validate** : lecture seule, données IEX gratuites, recherche,
   nouvelle exécution des tests et génération des preuves. Une exécution verte
   peut contenir `research_gate_passed=false` ou `connection_passed=false` :
   consulter les champs, pas seulement la couleur du workflow.
6. Lancer une seule fois **audit** pour le diagnostic historique 2018–2022. Le
   verrou est écrit avant le téléchargement et deux reprises réseau au plus sont
   permises sans changer le code ni le plan.

Le canari nécessite ensuite un second compte Alpaca Paper neuf de 2 000 USD et
deux secrets distincts, `ALPACA_CANARY_API_KEY` et
`ALPACA_CANARY_SECRET_KEY`. `canary-validate` refuse le compte shadow principal.
Même après validation, `canary-policy.json`, `CANARY_KILL_SWITCH` et
`CANARY_SCHEDULE_ENABLED` restent trois verrous indépendants. La politique est
désactivée par défaut.

Le canari possède aussi un verrou d'entrée explicite `entries_enabled`. Le
passer à `false` active un mode de vidange : aucun nouvel achat n'est créé, mais
les sorties de signal, de durée, de stop et du watchdog restent autorisées. Une
fois les ordres rapprochés et toutes les positions fermées, l'état durable écrit
une seule fois `drain_complete` et reste à plat. Réactiver les entrées depuis cet
état est refusé sans activation de stratégie explicitement revue.

Une mise à niveau du moteur sur un compte canari déjà utilisé passe par la
commande exceptionnelle `canary-migrate`. Elle n'accepte que l'empreinte
prédécesseur explicitement revue dans le code, relance les tests, utilise un
client Alpaca en lecture seule et exige l'égalité exacte entre compte, position,
trésorerie, état durable et compte shadow distinct. Elle ne remet pas à zéro le
compte et ne peut pas autoriser une migration générique.

Tous les jobs, y compris la V1, sont bloqués tant que la gratuité n'est pas
attestée. Le connecteur GitHub ne permet pas de vérifier/modifier la facturation
ni de lire les valeurs des secrets. Aucun service supplémentaire n'est provisionné.

## Promotion contrôlée vers les ordres fictifs

L'activation nécessite **ensemble** :

- des preuves `validation.json` pour le code courant et le bon compte, datant de moins de 7 jours ;
- un test final d'au moins 60 séances et 30 allers-retours, rentable après coûts,
  meilleur que SPY investi à 60 %, sans coupe-circuit, rentable sous coûts renforcés ;
- une modification versionnée de `execution-policy.json` avec `orders_enabled=true`
  et la stratégie choisie **sur la validation**, après lecture des preuves ;
- `PAPER_KILL_SWITCH=false` et, pour les horaires, `BOT_SCHEDULE_ENABLED=true`.

**Aucune promotion automatique à partir d'un backtest.** La demande de travail
autorise la poursuite technique, mais les preuves doivent réellement exister.
Par défaut, le planning et les ordres restent inactifs. Après promotion, le
planning exécute automatiquement `paper` ; avant promotion il exécute `shadow`
si le planning est explicitement activé. Les preuves expirées arrêtent les
soumissions. Après initialisation du portefeuille, le workflow renouvelle
automatiquement les tests et la connexion en lecture seule avant chaque cycle
paper, uniquement pour le même code et le même compte déjà validés. Il conserve
le rapport de recherche initial et ne retune pas le holdout. Un code ou un compte
différent exige une nouvelle validation adaptée à l'état du portefeuille.

Arrêt immédiat des **nouvelles soumissions** : `PAPER_KILL_SWITCH=true`, puis
`BOT_SCHEDULE_ENABLED=false`. Cela ne ferme ni n'annule les ordres existants.
L'exécuteur ne possède pas d'API d'annulation ni de liquidation forcée.

## Données, backtests et suivi

- IEX explicite, barres 1 heure complètes de 10 h à 15 h, heure de New York.
  L'ouverture partielle et les heures étendues sont exclues. Absence de données,
  dates incohérentes ou désalignement entre symboles : échec, sans forward-fill.
- Décisions à la clôture, exécution simulée à l'ouverture disponible suivante.
  Un seul ordre par cycle, sorties prioritaires. Gaps et interruptions conservés.
- Coûts par côté : frais fictifs **1 bp** + slippage **9 bp** ; stress à **29 bp**
  de slippage. Liquidation finale conventionnelle à la dernière clôture avec coûts.
- Découpage par séances **60 % entraînement / 20 % validation / 20 % test final**.
  Trois candidats fixes comparés sur les deux premières parties ; seul le candidat
  retenu est évalué sur le test final. Diagnostics walk-forward antérieurs au test.
- Rapports JSON/Markdown, courbes, transactions et décisions ; empreinte des
  données et des sources. Relecture possible du fichier d'entrée sauvegardé.
- Référence SPY à 100 % et à 60 % + cash, mêmes dates et coûts. SPY est un ETF
  proxy du S&P 500, pas l'indice exact. Recherche sur données ajustées des dividendes ;
  paper sur prix bruts, Alpaca Paper ne simulant pas les dividendes.
- Le suivi shadow conserve, pour chaque candidat, la trésorerie et les positions
  virtuelles, la performance nette des coûts modélisés, le drawdown et une
  référence 60 % SPY + 40 % cash. Le résumé classe les candidats et affiche les
  raisons précises d'attente : moins de 60 séances, moins de 30 allers-retours,
  perte, sous-performance du benchmark ou coupe-circuit. Ce diagnostic ne peut
  pas autoriser automatiquement les ordres.
- Le suivi paper conserve valeur brute, valeur nette de coûts modélisés, rendement,
  drawdown et référence SPY en prix. Le benchmark utilise la dernière barre complète,
  le compte la valorisation du courtier ; les deux horodatages sont conservés.
- L'audit accéléré compare les six stratégies sur 2018–2022 avec coûts normaux
  et stressés, sans sélection rétroactive et sans droit de promotion.
- Le canari utilise `trend_6_24` comme générateur déterministe d'ordres fictifs
  sur le second compte. Il mesure uniquement la plomberie d'exécution.

Le cycle de stratégie est demandé à `:23` chaque heure de séance, dans le fuseau
`America/New_York`, afin d'éviter les conversions DST et le pic de charge GitHub
du début d'heure. Un workflow séparé contrôle les positions à `:13`, `:28`, `:43`
et `:58` sans attendre une nouvelle barre : il peut demander une sortie de risque
sur le prix courant, mais ne crée jamais une entrée. Les deux workflows partagent
la même concurrence et le même état durable pour empêcher des écritures simultanées.
Le calendrier Alpaca filtre les fermetures.

GitHub Actions n'offre toujours aucune garantie de ponctualité : sa documentation
précise que les jobs planifiés peuvent être retardés ou abandonnés. Le watchdog
réduit cette fenêtre, il ne constitue donc pas un stop garanti. Alpaca ne permet
les stops fractionnés qu'en `DAY`; un stop permanent `GTC` ne peut pas protéger
proprement les tailles fractionnées de ce compte de 2 000 USD. Les sorties restent
des limites DAY pouvant ne pas être exécutées ; les backtests à l'open sont un modèle
de recherche, pas une reproduction de ces limites ni du retard de quelques minutes.
Une phase shadow et une observation des remplissages restent indispensables.

## État durable et reprise

La branche `bot-state`, créée au premier lancement autorisé, contient `runtime/` :

- `connection.json`, `validation.json`, `research.json`, `research.md` ;
- `research-input.json`, manifeste des données, pour rejouer la recherche ;
- `state.json`, `performance.json`, journal `journal.jsonl` avec chaîne de hachage.
- `shadow-state.json` et `shadow-performance.json` pour les six portefeuilles
  virtuels prospectifs, sans mélange avec l'état d'exécution paper.
- `accelerated-audit-*` pour le plan verrouillé, les données et le rapport uniques ;
- `canary/` pour les preuves, décisions et positions du second compte Paper.

Les workflows sont sérialisés, sans force-push ni cache/artifact supplémentaire.
Une intention est écrite et synchronisée localement avant la requête d'ordre,
puis l'état est poussé à la fin même en cas d'erreur. Une réponse ambiguë n'est
jamais retentée ; quantités, cash, ordres et remplissages doivent être rapprochés.
Un arrêt brutal avant le push peut perdre le dernier journal local : toute
discordance au redémarrage suspend les transactions et nécessite un rapprochement
avec l'historique Alpaca. Ne jamais effacer l'état pour « débloquer » le bot.

## Utilisation locale

```bash
python -m pip install -r requirements-research.txt
python -m unittest discover -s tests -v
# Vérification entièrement hors ligne, sans clés ni GitHub Actions :
python -m bot selfcheck --state-dir results/offline
python -m bot probe
python -m bot research
python -m bot audit
python -m bot validate
python -m bot shadow
# Le mode paper reste verrouillé par les preuves et la politique :
python -m bot paper
# Second compte Paper uniquement, verrouillé par défaut :
python -m bot canary-probe --state-dir runtime-canary
python -m bot canary-validate --state-dir runtime-canary --main-state-dir runtime
python -m bot canary-migrate --state-dir runtime-canary --main-state-dir runtime
python -m bot canary-paper --state-dir runtime-canary
python -m bot canary-risk --state-dir runtime-canary
# Rejouer exactement une entrée sauvegardée, sans réseau ni clés :
python -m bot research --input runtime/research-input.json --state-dir results/replay
```

`selfcheck` produit un tableau et un JSON pour 15 combinaisons (5 marchés
synthétiques × 3 stratégies) et exécute toute la chaîne chronologique. Ses
résultats ne peuvent pas servir de preuve d'activation. Ce travail reste possible
quand les quotas GitHub Actions sont épuisés.

Une recherche rejouée doit retrouver `research-manifest.json` près du fichier
d'entrée (ou via `--manifest`). L'empreinte du contenu doit correspondre au
téléchargement IEX enregistré. Sans manifeste, le calcul reste disponible mais
le rapport est marqué non vérifié et sa promotion est bloquée. Une preuve de
validation lie désormais le rapport complet, les données et la version du code.
Cette traçabilité détecte les mélanges/altérations accidentels ; elle ne remplace
pas une signature indépendante de la source de données.

Secrets : `ALPACA_API_KEY` et `ALPACA_SECRET_KEY`, variables d'environnement en
local ou secrets GitHub. Ne jamais les mettre dans le code, les journaux ou un chat.
La V1 reste exécutable avec `requirements.txt` et `python simulate.py` ; c'est un
backtest quotidien de référence, distinct du moteur horaire.

Voir [l'audit et l'état du chantier](docs/AUDIT.md) et
[les limites de validation](docs/VALIDATION.md).
