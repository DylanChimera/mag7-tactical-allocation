# Étape 2 — première comparaison et filtre de tendance

## Installation Windows

Ajouter `src/mag7/compare.py` au projet existant et ce guide dans `docs/`.
Ne remplacer ni `backtest.py`, ni les données, ni HANDOFF.md. Le module requiert
le moteur corrigé `0.3.0-accounting-fix`. Aucune dépendance supplémentaire.

Depuis le dossier contenant pyproject.toml :

```powershell
.\.venv\Scripts\python.exe -m mag7.compare --self-test
.\.venv\Scripts\python.exe -m mag7.compare --cost-bps 0 5
```

La seconde commande utilise le snapshot gelé `20261012T220229517719Z_52db55`.
Aucun téléchargement. Les hashes du snapshot et du calendrier sont vérifiés.

## Scénarios comparés

| Identifiant | Allocation cible | Rééquilibrage |
|---|---|---|
| qqq_buy_hold | 100 % QQQ | Achat initial seulement |
| qld_buy_hold | 100 % QLD | Achat initial seulement |
| mag7_monthly | 1/7 par action | Mensuel |
| b0_monthly | 10 % par action, 30 % QLD | Mensuel |
| static25_monthly | 10 % par action, 25 % QLD, 5 % cash | Mensuel |
| trend200_monthly | 10 % par action, 30 % QLD ou cash selon signal | Mensuel |

Le filtre est strict : QQQ clôture au-dessus de sa MM200 => QLD, sinon cash.
Le calcul utilise uniquement les clôtures jusqu’à la séance précédente incluse.
Exécution à la première ouverture de mois, avec valorisation des anciennes
positions à cette ouverture. Exception : investissement initial à la première
séance disponible après les 200 séances d’échauffement.

Le signal est enregistré quotidiennement, mais la décision n’est appliquée
qu’au calendrier mensuel. Aucun achat/vente intermédiaire même si QQQ franchit
sa moyenne. Le cœur Mag7 est rééquilibré mensuellement dans les quatre
portefeuilles qui le contiennent. Les poids dérivent entre transactions.
Le cash réel est non rémunéré, ne subit pas de frais de transaction et peut
représenter 30 % cible du portefeuille après frais en régime négatif.

Tous les portefeuilles commencent à la même ouverture après 200 observations
antérieures ; aucune performance pendant l’échauffement. Le benchmark B0
sera donc recalculé sur une période plus courte que celui débutant le
4 janvier 2016 : ne pas comparer directement sa nouvelle valeur finale
aux 2,59 millions du précédent run.

Il s’agit d’une exploration de l’historique déjà consulté, pas d’une validation
hors échantillon. Le seuil de 200 séances n’est pas optimisé dans cette étape.
La comparaison quotidienne/hebdomadaire, le filtre de volatilité, Markov et
les données externes restent à développer.

## Sorties

Un nouveau dossier est créé sous `reports/comparison/<snapshot>/<run_id>/` :

- `comparison.csv` et `comparison.json` : douze lignes, six stratégies × deux coûts.
- `signals.csv` : date d’exécution potentielle, date de décision, dernière clôture,
  moyenne mobile et état haussier. L’état quotidien ne signifie pas transaction quotidienne.
- `manifest.json` : paramètres, hashes du moteur, du module et des données, limites.
- Par stratégie/scénario : `daily.csv`, `transactions.csv`, `rebalance_audit.csv`.

Les rendements et drawdowns sont en décimal : 0.25 signifie 25 %.
`max_drawdown` est positif ; dans les lignes quotidiennes, `drawdown` est négatif.
Les frais s’appliquent à tout montant acheté/vendu, investissement initial inclus.
La volatilité inclut la première séance partielle. Le CAGR utilise les jours
calendaires écoulés/365.25. Drawdown mesuré aux clôtures, capital initial inclus.

Chaque stratégie sans frais est comparée à une formule indépendante par périodes :
capital précédent × (poids cash + somme des poids initiaux × ratios de prix).
Cette référence tient compte des changements mensuels de signal et des 30 % de
cash ; elle n’utilise pas la logique de transactions du moteur.

## Lire les résultats

Comparer surtout `trend200_monthly` à `b0_monthly` à coût identique :

- rendement annualisé gagné/perdu ;
- drawdown et volatilité réduits ou augmentés ;
- poids moyen de QLD et proportion de séances en position ;
- transactions, montants échangés et frais cumulés.

Une baisse de drawdown peut simplement provenir d’une exposition moyenne
plus faible. Ce résultat ne prouve pas un alpha. Le contrôle `static25_monthly` permet maintenant de comparer à une exposition
statique plus faible. Il ne constitue pas un appariement exact du risque.

## Validation de la livraison

Neuf tests intégrés sur données synthétiques : période commune, référence
indépendante, décalage du signal, cash de 30 % après frais, invariance aux
observations futures, quantités constantes en buy-and-hold et échauffement
insuffisant (certains tests couvrent plusieurs propriétés). Test de lancement
CLI initial sur snapshot synthétique ; suite de tests étendue à QLD seul, au portefeuille fixe 70/25/5 et douze scénarios. Le test QLD compare la formule directe, les coûts initiaux et les unités constantes. Aucun résultat réel de
comparaison fourni : le snapshot réel complet est sur la machine de l’utilisateur.

Après exécution locale, partager `comparison.csv` et les éventuelles erreurs.
Ajouter ensuite au HANDOFF les résultats constatés et les chemins effectifs.

## Ajout QLD seul

Le benchmark QLD est un buy-and-hold : achat à la même ouverture initiale après 200 séances, conservation des unités jusqu’à la dernière clôture, aucun rééquilibrage externe. Son levier interne est déjà reflété dans les prix. Frais sur l’achat initial seulement, pas de liquidation finale, comme QQQ. Avec le snapshot retenu, la période commune reste le 18 octobre 2016 au 9 octobre 2026.

## Contrôle statique 70/25/5 — implémenté

`static25_monthly` ne lit pas le signal pour déterminer les poids : 0.10 par
Mag7, 0.25 pour QLD, zéro pour QQQ. La somme des poids investis est 0.95 ;
le moteur garde le solde de 0.05 en cash réel, sans ticker fictif ni frais
sur la détention du cash. Ne pas renormaliser les poids investis à 100 %.

À l’initialisation et au rééquilibrage mensuel, ces pourcentages portent sur
la valeur APRÈS frais. Le moteur résout son équation d’autofinancement puis
vend avant d’acheter. Entre rééquilibrages, les unités et le montant de cash
restent constants ; les poids, dont celui du cash, dérivent avec les prix.
La cible de 25 % n’implique pas une moyenne réalisée exactement de 25 %.

Sans frais et pour une période entre rééquilibrages, le facteur de croissance
indépendant est 0.05 + 0.10 * somme(ratios de prix des sept actions)
+ 0.25 * ratio de prix QLD. Avec frais, conserver le ledger du moteur.

Comparer `static25_monthly` à `trend200_monthly` à coût identique : rendement,
volatilité, drawdown, coûts, poids moyen QLD ET cash. Le nouveau champ
`mean_cash_weight` est exporté dans le récapitulatif ; `cash_weight` dans daily.csv.

Le 25 % a été choisi après observation du poids moyen historique de QLD dans
la stratégie MM200 (~25.04 %). C’est un contrôle descriptif approximatif de
l’exposition, pas un ajustement exact du bêta ou du risque ni un test hors
échantillon. Aucun balayage de paramètres n’est effectué.

Exécution inchangée :

```powershell
.\.venv\Scripts\python.exe -m mag7.compare --self-test
.\.venv\Scripts\python.exe -m mag7.compare --cost-bps 0 5
```

Les tests supplémentaires vérifient l’indépendance vis-à-vis du signal, les
5 % de cash après frais, leur dérive entre rééquilibrages et le retour aux
poids cibles au mois suivant. Les données réelles restent à exécuter localement.
