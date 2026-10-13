# Feuille de route

## 0 — Squelette : livré

Configuration, signal causal TV1, quatre états observables, CLI synthétique/CSV, tests et CI. Aucun modèle prédictif ou backtest terminé.

## 1 — Données : pipeline livré, audit réel à terminer

Yahoo via yfinance est intégré : neuf instruments, snapshots fournisseur, manifeste, calendrier et contrôles. Reste à valider le téléchargement réel localement, inspecter les alertes et réconcilier les opérations sur titres. Réussite : données reproductibles et audit documenté, sans remplissage silencieux.

## 2 — Moteur et benchmarks

Construire un ledger positions/cash avec calendrier réel, next-open, opérations sur titres et coûts. Tests financiers nécessaires : gap nocturne sur anciennes positions ; split sans création de richesse ; dividende et créance ; prix constants avec coûts => baisse du capital ; conservation des quantités hors rééquilibrage ; pas d'emprunt involontaire. Réussite : réconciliation manuelle d'un petit cas et benchmarks exécutables.

## 3 — Stratégies simples

Implémenter B0, T1, V1, TV1 ; comparer daily/weekly sur périodes identiques, coûts et risques comparables. Réussite : premier rapport hors échantillon, même si résultat négatif.

## 4 — Markov observable

Compter les transitions entre les quatre états avec données passées uniquement. Lissage des probabilités à documenter ; afficher effectifs et incertitude. Comparer une décision selon état courant à une décision enrichie par transitions. Associer les états aux rendements futurs sur l'horizon d'exécution réel ; la probabilité de l'état suivant ne prédit pas directement le gain. Réussite : apport marginal mesuré, pas simplement matrice de transition présentée.

## 5 — Référence supervisée simple

Régression logistique régularisée avec peu de variables : rendements passés, tendance, volatilité, participation des sept titres. Validation chronologique, calibration probabiliste et performance économique après coûts. Avoir raison sur le signe ne suffit pas ; tenir compte des amplitudes.

## 6 — Kalshi / Polymarket

Auditer puis archiver une famille récurrente de contrats (par exemple Fed). Comparer modèle de marché seul vs même modèle enrichi sur les mêmes dates ; vérifier stale quotes, règles, échéances et heures. Réussite : couverture suffisante et apport marginal hors échantillon, sinon abandon documenté.

## 7 — Extensions

HMM à probabilités filtrées, risque global par covariance, allocation dynamique du cœur, mesure en EUR et produit du courtier. Une extension à la fois. Passer en paper trading seulement après validation comptable et gel des règles.
