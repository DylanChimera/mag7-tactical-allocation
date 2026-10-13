# Mag 7 Tactical Allocation

Laboratoire Python de recherche sur un portefeuille Magnificent Seven et une poche tactique Nasdaq-100 à levier quotidien ×2. Développement dans VS Code ; code et noms de variables en anglais, documentation en français.

**Statut v0.2 : signaux + pipeline quotidien Yahoo implémentés et testés sur fixtures. Le téléchargement réel nécessite un accès Yahoo fonctionnel ; **

**Pour installer cette mise à jour et télécharger les données : [guide du pipeline](docs/data_pipeline.md).**

## Question de recherche

Une allocation dynamique à un ETF Nasdaq ×2 améliore-t-elle le rendement net à risque comparable face à une allocation permanente ? Les régimes observables, puis leurs transitions de Markov, apportent-ils une information supplémentaire ? Les variations des probabilités de marchés de prédiction améliorent-elles ensuite les décisions hors échantillon ?

On recherche des règles reproductibles, pas des points d'entrée et de sortie optimaux déterminés après coup.

## Périmètre initial

| Élément | Convention de recherche |
|---|---|
| Actions | AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA ; une seule classe Alphabet |
| Cœur | 70 % cible, 10 % par entreprise lors du rééquilibrage mensuel |
| Poche tactique | 30 % maximum, répartis entre QLD et liquidités |
| Référence de signal | QQQ |
| Décision | Après clôture ; exécution au plus tôt à l'ouverture suivante |
| Fréquences à comparer | Quotidienne et hebdomadaire, avec mêmes contraintes |
| Devise | USD ; parts fractionnaires autorisées dans le prototype |
| Contraintes | Acheteur uniquement, aucun emprunt au niveau du compte |

Ces poids sont des paramètres expérimentaux. Le plafond de QLD limite son poids dans le compte, pas l'exposition économique totale. Le cœur actions reste risqué même lorsque QLD est à zéro.

QLD vise deux fois le rendement **quotidien** du Nasdaq-100 avant frais. Sa performance sur plusieurs jours n'est pas le double du rendement cumulé de l'indice. Source : [ProShares, QLD](https://www.proshares.com/our-etfs/leveraged-and-inverse/qld), consultée le 12 octobre 2026. Le produit réellement accessible au courtier devra être étudié séparément.

## Démarrer dans VS Code

Prérequis : Python 3.11 ou ultérieur, Git, VS Code et son extension Python. Le noyau de signaux utilise la bibliothèque standard. Installer l’option `[data]` pour le pipeline et tous les tests.

1. Extraire le dossier et l'ouvrir avec **File → Open Folder**.
2. Dans le terminal PowerShell de VS Code, à la racine :

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[data]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m mag7 --demo
```

L'appel direct à l'interpréteur évite de devoir modifier la politique d'exécution PowerShell pour activer l'environnement.

Sur macOS / Linux :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[data]"
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m mag7 --demo
```

3. Dans VS Code : **Ctrl+Shift+P → Python: Select Interpreter → .venv**.

La commande de démonstration utilise des prix **synthétiques**, sans réseau, et affiche un régime ainsi qu'un poids cible pour QLD. Elle ne simule pas de transactions ou de rendements de portefeuille.

Pour utiliser une série quotidienne locale de clôtures QQQ ajustées :

```powershell
.\.venv\Scripts\python.exe -m mag7 --csv data/processed/qqq.csv
```

Format CSV : `date,close`, dates ISO croissantes, uniques, sans données manquantes. Au moins 200 clôtures sont nécessaires avec la configuration initiale. Le CLI calcule uniquement le dernier signal ; il ne vérifie pas que toutes les séances sont présentes. Voir [le contrat de données](docs/data_contract.md).

## Contenu

| Chemin | Rôle |
|---|---|
| `configs/baseline.toml` | Paramètres du premier signal |
| `configs/data.toml` | Univers, dates et dossier des téléchargements |
| `src/mag7/data/` | Téléchargement Yahoo, normalisation, audits et sauvegardes |
| `docs/data_pipeline.md` | Installation et utilisation pas à pas du pipeline |
| `src/mag7/signals.py` | Régime observable, volatilité et poids tactique |
| `src/mag7/__main__.py` | Démonstration et lecture d'un CSV local |
| `tests/test_signals.py` | Contrôles de causalité et des limites de l'allocation |
| `docs/research_protocol.md` | Hypothèses, validation et benchmarks |
| `docs/data_contract.md` | Schéma des données et conventions temporelles |
| `docs/roadmap.md` | Étapes et critères de réussite |
| `experiments/registry.csv` | Registre de tous les essais, y compris négatifs |
| `data/raw`, `data/processed` | Données locales exclues de Git |
| `notebooks` | Exploration ; déplacer les règles réutilisables dans `src` |
| `reports` | Sorties futures du backtest, exclues de Git |
| `.github/workflows/tests.yml` | Tests automatiques GitHub |

## Signal initial implémenté

Pour une décision après la clôture de la séance t :

- Tendance positive si la clôture de QQQ est strictement supérieure à sa moyenne sur 200 séances.
- Volatilité : écart-type empirique des 60 derniers rendements simples, annualisé par √252.
- Quatre états : tendance positive/négative × volatilité faible/élevée ; seuil fixé à 20 % annualisés.
- Poids QLD : zéro si la tendance est négative ; sinon `min(0.30, 0.30 * 0.20 / vol)`.
- Volatilité nulle et tendance positive : poids au plafond. Historique insuffisant : aucun signal.

Le seuil de 20 % n'est **pas** une volatilité cible du portefeuille. Les probabilités de transition de Markov ne sont pas encore estimées. `signal_at(prices, t)` ignore explicitement les observations après t.

Le poids retourné est une **cible de la poche tactique**. Il ne réinitialise pas chaque jour le cœur actions à 70 %. Le futur moteur devra respecter sa dérive et son calendrier mensuel ; si la trésorerie disponible ne suffit pas pour atteindre la cible QLD sans emprunt, plafonner l'achat et journaliser le poids effectivement obtenu.

## Prochain travail : premier jalon

Le pipeline Yahoo est décrit dans [le guide](docs/data_pipeline.md). Valider un téléchargement local, lire son rapport qualité et examiner les opérations sur titres. Ensuite coder le moteur de portefeuille et les benchmarks.

Les extensions Markov, régression logistique, Polymarket/Kalshi et HMM sont détaillées dans [la feuille de route](docs/roadmap.md).

## Publier sur GitHub

Le dossier téléchargé est prêt à versionner ; aucun dépôt distant n'a été créé. Depuis sa racine :

```bash
git init -b main
git add .
git commit -m "Initialize Mag7 tactical allocation research"
```

Sur GitHub, créer un dépôt vide nommé `mag7-tactical-allocation`, privé ou public selon ton choix, **sans** initialisation README, licence ou gitignore. Puis remplacer `TON_IDENTIFIANT` :

```bash
git remote add origin https://github.com/TON_IDENTIFIANT/mag7-tactical-allocation.git
git push -u origin main
```

Authentification avec le gestionnaire d'identifiants Git ou SSH ; ne jamais mettre de token dans le code ou l'URL du dépôt. Si Git demande une identité, configurer `user.name` et `user.email` avant le commit.

## Reproductibilité

Pour chaque expérience, conserver le commit Git, la configuration exacte, les versions Python et des dépendances, le hash des données, les périodes utilisées et les résultats nets. Ne pas publier des données sans vérifier leurs conditions de redistribution. Ne jamais committer `.env`, clés API ou fichiers de courtier.

Aucune licence de redistribution du code n'a été choisie automatiquement : ajouter une licence avant d'encourager sa réutilisation publique.
