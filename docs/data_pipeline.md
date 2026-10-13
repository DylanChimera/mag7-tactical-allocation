# Pipeline de données — guide pas à pas

## Installer la mise à jour

L’archive contient le projet complet. Extraire d’abord dans un dossier temporaire, puis copier les fichiers du projet dans ton dossier existant, celui contenant `pyproject.toml`. Ne pas créer un deuxième niveau `mag7-tactical-allocation`. Préserver `.venv`, `.git` et les données déjà téléchargées ; aucune de ces données n’est incluse dans l’archive. Si tu as modifié les fichiers du projet, faire un commit ou une copie avant de fusionner.

Fichiers ajoutés : `configs/data.toml`, `src/mag7/data/`, `tests/test_data.py`, ce guide.
Fichiers mis à jour : `pyproject.toml`, `README.md`, `docs/data_contract.md`, `docs/roadmap.md`, `.github/workflows/tests.yml`.

Dans PowerShell, à la racine du projet (pas dans `src`) :

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[data]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`[data]` installe les bibliothèques nécessaires en plus de ton code : pandas/numpy pour les tables, yfinance pour Yahoo, exchange-calendars pour les séances, tzdata pour les fuseaux horaires sous Windows. Les versions effectivement utilisées sont enregistrées à chaque téléchargement.

## Premier essai : une période courte

```powershell
.\.venv\Scripts\python.exe -m mag7.data --start 2025-01-01 --end 2025-02-01
```

Cette commande demande les neuf actifs de janvier 2025. La borne de fin est **exclusive**. Lancer une petite période d’abord pour vérifier l’accès réseau ; aucun jeton API n’est requis.

Si le statut est `passed`, télécharger l’historique :

```powershell
.\.venv\Scripts\python.exe -m mag7.data --start 2016-01-01
```

Sans `--end`, le programme s’arrête avant la date du jour à New York : il exclut ainsi la séance éventuellement en cours. Il ne détermine pas une heure optimale de trading.

Chaque lancement télécharge un snapshot complet de la période, sans fusion ni téléchargement incrémental. Cela simplifie la reproductibilité. Éviter de relancer inutilement sur Yahoo.

## Ce qui se passe

1. Lire dates et univers dans `configs/data.toml`, avec priorité aux options CLI.
2. Construire la liste attendue des séances et archiver le calendrier.
3. Télécharger chaque titre séparément : OHLC, clôture ajustée, volume, dividendes et splits.
4. Sauvegarder les tables retournées par yfinance avant nos transformations, avec métadonnées et date de collecte.
5. Vérifier intégralité des séances, doublons, valeurs finies/positives, cohérence OHLC, devise et fuseau.
6. Produire les fichiers normalisés seulement si les neuf téléchargements passent les contrôles bloquants.
7. Écrire le rapport, les paramètres, versions, commit Git disponible et empreintes SHA-256.

Le calendrier XNYS est utilisé comme calendrier quotidien commun des actions/ETF US. Il ne modélise pas les règles d’exécution spécifiques du Nasdaq. Les fermetures exceptionnelles dépendent aussi de la version du calendrier ; le snapshot des séances permet de retrouver ce qui a été utilisé.

## Où sont les résultats ?

| Fichier | Contenu |
|---|---|
| `data/raw/<run_id>/QQQ.csv` (et huit autres) | Table fournisseur archivée avant nos transformations |
| `data/raw/<run_id>/<symbol>.metadata.json` | Métadonnées et heure UTC de collecte |
| `data/raw/<run_id>/sessions.csv` | Séances attendues, horaires UTC dont demi-séances |
| `data/raw/<run_id>/quality_report.json` | Rapport par titre, erreurs et avertissements |
| `data/raw/<run_id>/manifest.json` | Paramètres, versions, empreintes, statut |
| `data/processed/<run_id>/market_daily.csv` | Une ligne par séance et par titre |
| `data/processed/<run_id>/signal_prices.csv` | Matrice des clôtures ajustées : date × ticker |
| `data/processed/<run_id>/qqq.csv` | Entrée `date,close` du premier signal |
| `data/processed/latest.json` | Référence au dernier snapshot sans erreur bloquante |

`run_id` est un identifiant de téléchargement horodaté. Chaque exécution crée un nouveau dossier : les anciens fichiers sont préservés. Les fichiers CSV s’ouvrent dans VS Code ; garder les originaux inchangés.

`raw` signifie ici « table telle que renvoyée par yfinance », pas réponse HTTP Yahoo originale ni cours non ajustés. Le fournisseur et yfinance peuvent déjà avoir transformé ces données.

## Interpréter le statut

- `passed` : contrôles automatiques passés, **pas certification d’exactitude financière**.
- `review` : données exportées, mais examiner les alertes (volume nul ou variation ajustée supérieure à 35 %). Le seuil est un détecteur d’anomalie, pas un filtre de stratégie ; aucune ligne n’est supprimée.
- `failed` : au moins une erreur bloquante ; pas de fichiers traités pour ce lancement. Les données déjà reçues restent archivées. `latest.json` continue de pointer vers l’ancien succès : ne pas le confondre avec le lancement qui vient d’échouer.

Le programme retente trois fois une requête échouée, puis poursuit l’audit des autres titres. Il sort avec un code non nul si le snapshot est incomplet. Il ne remplit jamais un cours manquant avec le cours de la veille.

## Prix et ajustements : règle essentielle

| Colonnes | Signification et usage |
|---|---|
| `open_yahoo`, `high_yahoo`, `low_yahoo`, `close_yahoo` | OHLC fournis avec `auto_adjust=False` ; historiquement ajustés des splits chez Yahoo, pas nécessairement les prix nominaux observés à l’époque |
| `adj_close` | Clôture ajustée du fournisseur pour étudier les rendements et construire les signaux |
| `adjustment_factor` | `adj_close / close_yahoo` |
| `adj_open`, `adj_high`, `adj_low` | OHLC synthétiques multipliés par ce même facteur pour rester cohérents avec `adj_close` |
| `dividend_yahoo`, `split_ratio` | Événements du fournisseur, conservés pour audit ; zéro indique aucun événement |

**Ne pas ajouter les dividendes aux rendements calculés sur `adj_close` et ne pas appliquer à nouveau les splits à ces séries.** Les OHLC ajustés sont des séries de recherche, pas des prix d’exécution réellement accessibles. Les dates de paiement des dividendes ne sont pas livrées ; la comptabilité exacte d’un portefeuille en quantités historiques n’est donc pas encore prête.

Les séries ajustées téléchargées aujourd’hui incorporent les ajustements et corrections disponibles aujourd’hui. Elles ne constituent pas une base point-in-time. Le choix rétrospectif des Mag7 reste un biais même si tous les contrôles passent.

## Lire le signal sur les données réelles

Après un téléchargement suffisamment long (au moins 200 séances), depuis la racine :

```powershell
$latestRun = Get-Content .\data\processed\latest.json | ConvertFrom-Json
$qqqPath = ".\data\processed\$($latestRun.run_id)\qqq.csv"
.\.venv\Scripts\python.exe -m mag7 --csv $qqqPath
```

Vérifier que `latestRun.run_id` correspond au téléchargement voulu. Cela calcule seulement le dernier signal de recherche ; aucune transaction ou simulation de performance.

## En cas de problème

- `No module named mag7.data` : copier aussi `src/mag7/data/`, puis réinstaller depuis la bonne racine.
- Dépendance manquante : relancer l’installation `-e ".[data]"` avec le Python de `.venv`.
- HTTP 429 / accès Yahoo refusé : arrêter les relances rapprochées, attendre puis essayer à nouveau. Les limitations peuvent dépendre de l’IP ; aucun contournement n’est implémenté.
- Séances manquantes : lire les dates du rapport et contrôler la source/calendrier ; ne pas remplacer ces trous par zéro.
- `signal: null` : période trop courte pour les 200 séances de la moyenne mobile.

## Vérification de cette livraison

Les tests hors réseau couvrent les jours fériés, trous de données, doublons, valeurs invalides, ajustements cohérents, conservation des snapshots et échecs partiels. Ils utilisent des données synthétiques explicitement dédiées aux tests. Un essai réel sur QQQ a rencontré une limitation HTTP 429 : un premier téléchargement réussi sur ta machine reste nécessaire. Aucun historique réel validé n’est inclus dans l’archive.

## Sources techniques

- [yfinance : paramètres de téléchargement](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [yfinance : code de traitement historique](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/history.py)
- [exchange-calendars : calendrier et séances](https://github.com/gerrymanoim/exchange_calendars)

Documentation consultée le 12 octobre 2026. yfinance est un outil non officiel ; vérifier les conditions d’utilisation Yahoo avant redistribution ou usage autre que recherche personnelle. Alpaca pourra être ajouté derrière la même interface fournisseur après validation de ses propres conventions de prix.
