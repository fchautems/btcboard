# BTC Dashboard

Application web simple pour visualiser l\'évolution du Bitcoin et simuler une stratégie DCA locale.

## Installation
```
pip install -r requirements.txt
```

## Lancement
```
python app.py
```

L\'interface est disponible sur [http://localhost:5000](http://localhost:5000).

L'API `/api/trend-data` permet de récupérer les scores Google Trends en cache.
Lorsque la variable d'environnement `RENDER` est présente, elle ne tente pas de
télécharger de nouvelles données et se contente de ce qui est stocké dans la
base.

## Préremplissage de la table `trends`

Sur les plateformes où l'accès à Google Trends est bloqué (par exemple Render),
il est conseillé de remplir la table `trends` en local avant le déploiement :

1. Lancez l'application sur une machine non restreinte afin que les données
   Google Trends soient enregistrées dans `btc.db`.
2. Exportez la table au format SQL :
   ```
   sqlite3 /tmp/btc.db .dump trends > trends.sql
   ```
   (ou en CSV selon vos préférences).
3. Importez ce fichier lors du déploiement – copie de la base ou exécution du
   script SQL – pour éviter toute tentative de récupération automatique.

Si la variable d'environnement `RENDER` est définie, l'application désactive
les appels réseau Google Trends et se contente des données présentes dans la
base.