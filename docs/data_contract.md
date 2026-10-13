# Contrat de données et limites de la source

## Implémentation Yahoo v0.2

Le schéma livré est décrit dans [data_pipeline.md](data_pipeline.md). Il diffère volontairement du contrat idéal ci-dessous : les OHLC Yahoo sont historiquement ajustés des splits et ne sont pas des prix exécutables bruts. Les dates de paiement des dividendes ne sont pas fournies. **Ne pas injecter ces données directement dans un ledger à quantités historiques avec application supplémentaire des splits.** Choisir une comptabilité de rendement total cohérente, ou une source de prix bruts et d’actions complète, avant le moteur.

## Contrat cible du moteur de portefeuille

Conserver les données brutes immuables et une table normalisée contenant :

`session_date, symbol, open, high, low, close, volume, dividend, split_ratio, source, retrieved_at_utc`.

- Prix d'exécution non ajustés et opérations sur titres explicites : mettre à jour quantités, droits aux dividendes et trésorerie à leurs bonnes dates. Documenter ex-date et date de paiement.
- Construire séparément la série ajustée utilisée pour les signaux ; ne jamais mélanger ouverture brute et clôture ajustée dans un même rendement.
- Stocker la méthode d'ajustement, les versions et hashes des fichiers. Les historiques téléchargés aujourd'hui peuvent avoir été révisés.
- Calendrier de séances US, jours fériés, clôtures anticipées ; horodatages timezone-aware. Ne pas coder New York comme un décalage UTC constant.
- Ne pas remplir artificiellement les cours négociables manquants. Bloquer ou exclure explicitement les séances affectées et consigner la décision.
- Vérifier doublons, ordre des dates, cours positifs, cohérence OHLC et splits extrêmes.
- Un seul ticker Alphabet. Documenter les anciens symboles et le début effectif de chaque historique ; ne pas inventer les cours antérieurs aux introductions.
- Pour le cash : taux disponible à la date, convention ACT/365 explicite et nombre de jours calendaires entre séances. Un cash à 0 % n'est qu'un scénario de contrôle.

Le CSV `date,close` accepté par le CLI est une entrée minimale pour le signal QQQ uniquement. Il ne suffit pas à un backtest à l'ouverture suivante.

## Marchés de prédiction — extension ultérieure

Archiver : plateforme, event_id, market_id, question, règles, outcome, échéance, timestamp de cotation, timestamp de réception, bid, ask, dernier prix, volume connu à cet instant, statut.

Conserver tous les timestamps en UTC, avec règle de décision en America/New_York. Utiliser une jointure as-of avec une limite d'ancienneté ; aucune observation après l'heure de décision. Une cote manquante reste manquante, jamais une probabilité de zéro. Conserver un indicateur de disponibilité.

Pour une réunion Fed, identifier la même échéance et la même définition avant de calculer une variation de probabilité. Documenter les changements de contrats et leur sélection. Ne pas filtrer sur le volume final connu après résolution.

Commencer par un audit de la couverture historique réellement récupérable. Pas de promesse de backfill complet ; pas de credentials de trading nécessaires au périmètre de recherche.
