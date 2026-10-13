# Protocole de recherche

## Expériences initiales préspécifiées

| ID | Hypothèse | Comparaison |
|---|---|---|
| B0 | Exposition statique | 70 % Mag7 + 30 % QLD |
| T1 | Persistance de tendance | Poche QLD si QQQ > MM200, cash sinon |
| V1 | Réduction du risque en forte volatilité | Poche QLD plafonnée et pondérée par 20 % / volatilité 60 séances |
| TV1 | Apport des deux filtres | Combinaison T1 + V1 |

Seul le **signal TV1** est codé à ce stade. B0/T1/V1 et tous les backtests restent à implémenter.

Benchmarks : QQQ buy-and-hold ; Mag7 équipondérées mensuellement ; 70 % Mag7 + 30 % cash ; B0 ; même tactique avec QQQ à la place de QLD. Pour comparer à risque égal, calibrer les expositions sur le passé uniquement et expliciter les contraintes qui empêchent éventuellement d'atteindre la cible.

## Horloge et comptabilité du futur moteur

1. Traiter opérations sur titres et positions détenues.
2. À l'ouverture t+1, valoriser les anciennes positions : elles supportent le gap depuis la clôture t.
3. Exécuter le signal calculé après clôture t, appliquer spreads/slippage/commissions et contraintes de cash. Le coût doit être calculé sur le montant réellement négocié, achats et ventes inclus.
4. Conserver les quantités entre transactions ; les poids dérivent. Valoriser à la clôture t+1 puis calculer le prochain signal.
5. Calendrier hebdomadaire : décision à la dernière séance de chaque semaine, exécution à la suivante ; mensuel : dernière séance du mois, exécution à la suivante. Gérer les semaines courtes.

Sur une date tactique seule, garder les quantités d'actions du cœur ; ajuster QLD avec le cash disponible. Sur une date mensuelle, rétablir les cibles des actions en tenant compte des coûts. Ne pas rééquilibrer tout le portefeuille quotidiennement par accident.

Tester des coûts hypothétiques de 1, 5 et 10 bps par montant négocié, puis des scénarios dégradés. Ce ne sont pas des estimations de coûts observés. Les frais internes de QLD sont déjà dans ses prix historiques ; ne pas les déduire deux fois. Exclure la fiscalité du prototype et l'indiquer.

## Validation

Avant toute optimisation : figer dates d'apprentissage, validation chronologique et test final dans le registre. Choisir ces dates après audit de disponibilité, avant d'observer les résultats. Ne pas qualifier d'intacte une période déjà explorée. Si nécessaire, réserver un test prospectif en paper trading.

En walk-forward : entraînement sur le passé, prédiction sur le bloc suivant, réestimation suivant un calendrier fixé. Purger les observations d'entraînement dont la cible recouvre le bloc de test ; adapter le gap à l'horizon du label. Ajuster normalisations et seuils appris uniquement sur l'entraînement.

L'univers Mag7 est sélectionné rétrospectivement : un découpage temporel ne supprime pas ce biais. Les périodes anciennes servent à comprendre les risques ; présenter cette limite et tester ultérieurement un univers sélectionnable à chaque date.

Conserver chaque essai et éviter une grille géante. Comparer daily/weekly avec les mêmes règles ; mesurer la sensibilité au jour hebdomadaire. Une amélioration doit persister hors échantillon, après coûts, et ne pas dépendre d'un seul titre ou épisode.

## Sorties attendues

Courbe de capital et drawdown ; CAGR, volatilité, Sharpe d'excès au cash, drawdown maximal et durée de récupération (indiquer si non récupéré) ; turnover avec convention ; exposition et poids réalisés ; coûts ; attribution par actif ; résultats par sous-période. Une métrique non définie doit être signalée, pas forcée à zéro.

Pour chaque résultat : configuration, commit, version de données, historique des essais. Les intervalles d'incertitude devront respecter la dépendance temporelle (par exemple bootstrap par blocs). Aucune conclusion de viabilité sur la seule performance in-sample.
