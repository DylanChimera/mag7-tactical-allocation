# Passation — mag7-tactical-allocation

État de référence : 12 octobre 2026, version livrée 0.2.0. Ce document décrit le code fourni dans la conversation ; le dossier ouvert dans VS Code peut avoir divergé. Lire le code local et examiner `git status` avant toute modification. Ne pas écraser les changements de l’utilisateur.

## 1. Objectif et contexte utilisateur

Construire un projet Python de recherche quantitative pour évaluer un portefeuille des Magnificent Seven associé à une poche tactique Nasdaq-100 à levier quotidien ×2. L’utilisateur veut étudier les règles d’entrée/sortie et les rééquilibrages quotidiens ou hebdomadaires, puis backtester leur viabilité après coûts et à risque comparable.

Univers initial : AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA ; QLD pour la poche ×2 ; QQQ comme référence de signal et benchmark. Une seule classe Alphabet est retenue.

Extensions envisagées : régimes observables, chaînes de Markov, régression logistique, données Polymarket/Kalshi, puis éventuellement HMM. **Ces extensions prédictives ne sont pas implémentées.**

L’utilisateur développe sur Windows dans VS Code. Les mises à jour précédentes ont été transmises par archives ZIP puis copiées manuellement. Il a confirmé que l’installation initiale fonctionne après correction du dossier courant, mais **n’a pas confirmé l’installation du pipeline v0.2 ni un téléchargement réussi**. Expliquer les commandes et progresser par étapes compréhensibles. Aucun accès au courtier, ordre réel ou déploiement n’est demandé.

## 2. Architecture actuelle

Projet installable avec `pyproject.toml`, Python >= 3.11, package sous `src/`.

| Fichier ou dossier | Fonction réelle |
|---|---|
| `src/mag7/signals.py` | `SignalConfig`, `Signal`, `signal_at` : signal causal tendance/volatilité |
| `src/mag7/__main__.py` | CLI `python -m mag7`, démonstration synthétique ou dernier signal sur CSV |
| `src/mag7/data/pipeline.py` | `DataConfig`, calendrier, téléchargement Yahoo, normalisation, audit, snapshots |
| `src/mag7/data/__main__.py` | CLI `python -m mag7.data` |
| `configs/baseline.toml` | Paramètres du signal |
| `configs/data.toml` | Univers, période, calendrier et dossier des données |
| `tests/test_signals.py` | 7 tests du signal |
| `tests/test_data.py` | 9 tests du pipeline sur données synthétiques et fournisseur simulé |
| `docs/data_pipeline.md` | Guide Windows, sorties et limitations du pipeline |
| `docs/data_contract.md` | Contrat cible et écarts de la source Yahoo |
| `docs/research_protocol.md` | Protocole de recherche proposé, pas un moteur exécutable |
| `docs/roadmap.md` | Feuille de route |
| `experiments/registry.csv` | En-tête seulement ; aucun résultat d’expérience enregistré |
| `data/raw/`, `data/processed/` | Dossiers locaux de snapshots, exclus de Git |
| `notebooks/`, `reports/` | Emplacements réservés, sans analyses ou rapports de performance |
| `.github/workflows/tests.yml` | Workflow de tests écrit, exécution distante non confirmée |
| `.vscode/` | Extensions recommandées et configuration de découverte unittest |

Le noyau de signaux utilise la bibliothèque standard. L’option d’installation `[data]` ajoute pandas, numpy, yfinance, exchange-calendars et tzdata. Les dépendances ont des bornes de versions mais **aucun lockfile complet**.

## 3. Fonctionnalités réellement implémentées

### Signal de référence

`signal_at(closes, index, config)` utilise les observations jusqu’à `index` inclus et ignore les suivantes.

- Tendance positive : clôture strictement supérieure à la moyenne mobile de 200 séances.
- Volatilité : écart-type empirique des 60 derniers rendements simples, annualisé par √252.
- Quatre états : `up_low_vol`, `up_high_vol`, `down_low_vol`, `down_high_vol` ; seuil de volatilité fixé à 20 %.
- Si tendance négative : poids cible QLD = 0.
- Sinon : `min(0.30, 0.30 * 0.20 / vol)` ; volatilité nulle => plafond de 30 %.
- Historique insuffisant : `None`, pas un signal de vente.

Le CLI affiche **un signal**, pas une performance. Il accepte `--demo` ou `--csv` avec `date,close`. Il n’exécute aucune transaction et ne calcule pas les positions du cœur Mag7. Les quatre états ne constituent pas une chaîne de Markov : aucune transition n’est estimée.

### Pipeline quotidien

- Source implémentée : Yahoo via `yfinance.Ticker.history`, sans clé API.
- Paramètres explicites : `auto_adjust=False`, `back_adjust=False`, `actions=True`, `repair=False`, `keepna=True`, `prepost=False`, fréquence quotidienne.
- Neuf instruments par défaut ; un sous-ensemble de cet univers est accepté.
- Début par défaut : 2016-01-01 ; début antérieur à 2013 refusé par le prototype.
- Fin exclusive ; par défaut date du jour à New York, donc séance courante exclue.
- Calendrier XNYS comme approximation des séances communes US, archivé avec le snapshot.
- Téléchargements séquentiels, trois essais maximum par titre, poursuite des autres titres après échec.
- Snapshot complet daté à chaque lancement : pas de mise à jour incrémentale.
- Contrôles : colonnes, devise USD, fuseau New York, dates uniques/croissantes, séances absentes ou inattendues, valeurs finies, prix positifs, volumes/actions non négatifs et cohérence OHLC.
- Alertes non bloquantes : volumes nuls et variations ajustées absolues > 35 %. Aucun cours n’est rempli artificiellement.
- Statuts `passed`, `review`, `failed`. Une erreur bloquante sur un titre interdit l’export traité du run entier.

Sorties :

| Chemin | Contenu |
|---|---|
| `data/raw/<run_id>/<symbol>.csv` | Table renvoyée par yfinance avant nos transformations |
| `data/raw/<run_id>/<symbol>.metadata.json` | Métadonnées et heure de collecte UTC |
| `data/raw/<run_id>/sessions.csv` | Calendrier attendu |
| `data/raw/<run_id>/quality_report.json` | Audit par titre |
| `data/raw/<run_id>/manifest.json` | Configuration, versions, commit Git si disponible, hashes SHA-256, statut |
| `data/processed/<run_id>/market_daily.csv` | Table normalisée date × titre |
| `data/processed/<run_id>/signal_prices.csv` | Matrice des clôtures ajustées |
| `data/processed/<run_id>/qqq.csv` | Entrée du CLI de signal, si QQQ téléchargé |
| `data/processed/latest.json` | Dernier run sans erreur bloquante, y compris statut `review` |

Après échec, `latest.json` reste sur le succès précédent : vérifier le run_id avant utilisation. Il n’existe pas encore de commande de reconstruction hors réseau depuis les snapshots, même si les tables et métadonnées sont archivées.

### Vérification effectivement réalisée

Installation editable, démonstration synthétique et 16 tests hors réseau réussis dans l’environnement de développement. Tests notamment sur causalité du signal, jours fériés, données manquantes, doublons, ajustements, hashes, archivage et conservation de `latest.json` après échec partiel.

Un téléchargement réel QQQ a échoué après trois tentatives avec **HTTP 429 / Too Many Requests** avant qu’un téléchargement complet réussisse dans l’environnement local. Le snapshot réel `20261012T220229517719Z_52db55` est maintenant archivé et audité ; aucun résultat de backtest n’existe. Aucun dépôt GitHub distant n’a été créé par l’assistant ; une création par l’utilisateur n’est pas confirmée.

## 4. Décisions et propositions à ne pas confondre

**Choix matérialisés dans le code :** Python, structure `src`, TOML, Yahoo pour le prototype, univers fixe, données quotidiennes, snapshots datés, validations bloquantes, signal tendance + volatilité causal. Aucun connecteur Alpaca n’a été écrit.

**Conventions proposées et documentées pour le futur backtest, encore modifiables :**

- Portefeuille acheteur uniquement, USD, sans emprunt du compte, parts fractionnaires.
- Cœur Mag7 de 70 % cible, soit 10 % par titre au rééquilibrage mensuel.
- Poche tactique de 30 % maximum en QLD, solde en cash.
- Signal après clôture, exécution au plus tôt à l’ouverture suivante.
- Poids dérivants entre transactions ; garder les quantités du cœur hors rééquilibrage mensuel ; plafonner l’achat QLD au cash réellement disponible.
- Comparer allocation constante, tendance seule, volatilité seule, combinaison ; puis daily vs weekly.
- Benchmarks : QQQ buy-and-hold, Mag7 équipondérées, 70/30 Mag7-cash, 70/30 Mag7-QLD et tactique QQQ sans levier.
- Validation chronologique/walk-forward, période finale réservée avant consultation, coûts et risques comparables ; enregistrer aussi les essais négatifs.

Ces conventions sont des hypothèses expérimentales, pas une allocation optimisée ou une stratégie validée. **Seul le signal de la combinaison est codé.** Aucun moteur, calendrier de rééquilibrage, frais, cash rémunéré, métrique de performance, walk-forward, modèle ML ou paper trading n’est implémenté. Les poids discrets 0/15/30 % ont été évoqués pour de futurs modèles ; le signal livré produit actuellement un poids continu entre 0 et 30 %.

## 5. Problèmes connus et limites essentielles

1. **Accès Yahoo validé pour le snapshot retenu, pas garanti dans le temps.** Le téléchargement réel du 12 octobre 2026 a réussi sur les neuf actifs pour la période 2016-01-01 à 2026-10-12, avec le run `20261012T220229517719Z_52db55`. Le HTTP 429 observé lors d’un essai antérieur peut dépendre de l’environnement ; ne pas multiplier les relances rapprochées.
2. **Prix ajustés.** `auto_adjust=False` ne signifie pas que les OHLC Yahoo sont des cours nominaux historiques non ajustés des splits. Les colonnes sont nommées `*_yahoo` pour éviter cette confusion. `adj_open/high/low` sont dérivés du facteur `adj_close / close_yahoo` : séries synthétiques de recherche, pas prix exécutables.
3. **Ne pas compter deux fois les opérations sur titres.** Ne pas ajouter les dividendes aux rendements de `adj_close`, ni réappliquer les splits à des prix déjà ajustés. Avant le moteur, choisir une comptabilité cohérente de rendement total ou une source de cours bruts/actions complète. Les dates de paiement des dividendes et les taux du cash manquent.
4. **Sens de `raw`.** Il s’agit d’une sérialisation du DataFrame yfinance, pas des octets HTTP ni d’une garantie de prix bruts. Yahoo et yfinance ont déjà pu transformer ou réviser les données.
5. **Biais de recherche.** Les Mag7 sont sélectionnées rétrospectivement ; découper chronologiquement ne supprime pas ce biais. L’historique téléchargé aujourd’hui n’est pas une base point-in-time. Pas de réconciliation indépendante des prix/opérations sur titres.
6. **Portée du risque.** Le seuil de 20 % pilote la poche QLD, pas la volatilité globale. Les actions restent exposées quand QLD est nul. Le levier quotidien ×2 ne double pas simplement un rendement cumulé.
7. **Reproductibilité incomplète.** Versions et hashes sont enregistrés, mais pas de lockfile complet ni capture automatique des modifications non committées. Le workflow GitHub est préparé, pas vérifié en exécution distante.
8. **Installation locale.** Une erreur initiale « pyproject.toml introuvable » a été résolue en travaillant dans la bonne racine. Les chemins de configuration sont relatifs au dossier courant. Vérifier que la v0.2 et l’option `[data]` sont réellement installées dans `.venv`.

## 6. Audit réel du snapshot retenu

Snapshot retenu après inspection locale : `20261012T220229517719Z_52db55`.

- Configuration : neuf actifs, début `2016-01-01`, fin exclusive `2026-10-12`, calendrier XNYS.
- Statut du manifeste : `passed`. Statut du rapport qualité : `passed`.
- Chaque actif contient 2 708 séances, du `2016-01-04` au `2026-10-09`.
- Les neuf ensembles de dates sont identiques : 2 708 séances communes, aucune date manquante ou supplémentaire.
- Le contrôle indépendant des CSV trouve zéro valeur manquante et zéro doublon de date pour chaque actif.
- Aucune variation journalière de `Adj Close` ne dépasse 35 % en valeur absolue ; aucune alerte de volume nul ou de mouvement extrême n’a été produite.
- `market_daily.csv` contient 24 372 lignes, soit exactement 2 708 séances × 9 actifs. `signal_prices.csv` contient 2 708 dates et les neuf tickers.

| Actif | Première date | Dernière date | Séances | Valeurs manquantes | Doublons | Splits | Dividendes |
|---|---|---|---:|---:|---:|---:|---:|
| AAPL | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 1 | 43 |
| MSFT | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 0 | 43 |
| GOOGL | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 1 | 10 |
| AMZN | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 1 | 0 |
| NVDA | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 2 | 43 |
| META | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 0 | 11 |
| TSLA | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 2 | 0 |
| QQQ | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 0 | 43 |
| QLD | 2016-01-04 | 2026-10-09 | 2708 | 0 | 0 | 4 | 23 |

Le manifeste conserve les versions utilisées (`yfinance 1.7.0`, `pandas 2.3.3`, `numpy 2.5.4`, `exchange_calendars 4.13.2`, `tzdata 2026.5`) et les empreintes SHA-256 des fichiers. Aucun commit Git n’est enregistré (`git_commit: null`) car cette copie locale ne contient pas de dossier `.git`.

Le contrôle des colonnes confirme que `adj_close` est la clôture ajustée fournie par Yahoo, que `adjustment_factor = adj_close / close_yahoo`, et que `adj_open/high/low` sont construits avec ce facteur. Les facteurs sont finis et correspondent exactement aux valeurs exportées dans `market_daily.csv` pour les neuf actifs. Les rendements de signal doivent donc utiliser `adj_close` sans ajouter à nouveau les dividendes ni réappliquer les splits. Les colonnes `*_yahoo` et les événements `dividend_yahoo`/`split_ratio` restent archivés pour audit, mais les OHLC ajustés ne sont pas des prix d’exécution historiques.

Ce statut `passed` valide les contrôles automatiques et la couverture du snapshot ; il ne certifie ni l’exactitude économique complète des révisions Yahoo, ni une base point-in-time, ni une comptabilité de portefeuille. Aucune observation n’a été corrigée ou supprimée pendant l’audit.

## 7. Prochaine étape concrète

La validation de couverture du snapshot réel est terminée. Avant tout moteur de backtest ou modèle Markov, arrêter la convention comptable : choisir entre une comptabilité de rendement total fondée sur `adj_close` pour la recherche et un ledger à prix d’exécution avec actions sur titres et dates de paiement complètes. Ne pas mélanger `close_yahoo`/OHLC d’exécution avec `adj_close` dans un même rendement.

Ensuite seulement : construire un moteur minimal avec positions/cash, coûts et exécution next-open ; valider un cas manuel avec gap nocturne et opérations sur titres ; implémenter les benchmarks avant d’enrichir les signaux. Le snapshot retenu doit être passé explicitement au moteur par son `run_id`, et non déduit d’un téléchargement relancé. Ne pas présenter les règles documentées comme des fonctionnalités déjà présentes.

Pour calculer le dernier signal sur un historique assez long :

```powershell
$latestRun = Get-Content .\data\processed\latest.json | ConvertFrom-Json
$qqqPath = ".\data\processed\$($latestRun.run_id)\qqq.csv"
.\.venv\Scripts\python.exe -m mag7 --csv $qqqPath
```

Après ce jalon : arrêter les conventions comptables, construire un moteur minimal avec positions/cash, coûts et exécution next-open ; valider un cas manuel avec gap nocturne et opérations sur titres ; implémenter les benchmarks avant d’enrichir les signaux. Ne pas présenter des règles documentées comme des fonctionnalités déjà présentes.
