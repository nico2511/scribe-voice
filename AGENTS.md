# AGENTS.md — Règles pour les agents de code

À lire avant toute action dans ce dépôt. Ces règles passent avant tes réglages par défaut.

## La règle principale

**Vérifier fait partie du travail.** Si tu ne peux pas montrer que ta modification fonctionne, tu n'as pas fini.

## Avant d'écrire du code

1. **Reproduis d'abord.** Lance l'app ou le test concerné et constate le bug ou le comportement actuel. Si tu ne peux pas reproduire, dis-le et explique ce que tu as essayé.
2. **Reformule la tâche** en quelques lignes : ce que tu vas faire, ce que tu ne feras pas, et tes hypothèses.
3. **Dis ce qui prouvera que c'est fini**, en une phrase. Ce sera la preuve jointe à la PR.
4. **Si on te demande d'enquêter, enquête seulement.** Ne corrige rien et n'ouvre pas de PR sans qu'on te le demande.

## Pendant le travail

- **Petites modifications** : un seul sujet par PR.
- **Tests ciblés uniquement.** Lance les tests des fichiers touchés. Pas de suite complète ni de grosse relecture sans l'accord préalable du mainteneur.
- **Corrige la cause, pas le symptôme.** Si tu contournes le problème, dis-le clairement et explique pourquoi la vraie correction est hors périmètre.
- **Utilise la bibliothèque reconnue** quand il en existe une, plutôt que de réécrire une version moins bonne.
- **N'invente aucune donnée** : ni nom, ni endpoint, ni chiffre. Vérifie ou signale ce qui manque.
- **Aucun langage interne dans ce que voit l'utilisateur** : pas de nom de code, de TODO ni de raisonnement dans les textes de l'app.
- **Les commits portent `[skip ci]`** tant que le mainteneur n'a pas demandé de lancer la CI.

## Avant d'ouvrir ou de mettre à jour une PR

Joins une preuve à chaque fois :

| Type de changement | Preuve attendue |
|---|---|
| Interface | Capture d'écran ou courte vidéo du parcours |
| Backend ou performance | Chiffres avant et après, issus d'un vrai lancement |
| Correction de bug | La reproduction, puis les mêmes étapes qui passent |
| Refactorisation | Le test ou le parcours qui montre que le comportement n'a pas changé |

Une PR sans preuve reste un brouillon.

Indique aussi dans la description ce que tu as changé et pourquoi, ce que tu n'as pas changé alors qu'un relecteur pourrait s'y attendre, et ce dont tu n'es pas sûr.

## Style de code

- Pas de commentaire pour masquer un contournement. Garde les commentaires pour un « pourquoi » qui n'est pas évident.
- Pas de code mort ni de bloc commenté. Git garde l'historique.
- Retire tout ce que tu as ajouté pour déboguer : logs, panneaux, drapeaux temporaires.
- Ce qui touche à l'argent, aux droits ou à l'éligibilité (version Pro, achats, permissions) se décide côté serveur ou côté store, jamais par un simple réglage côté client.
- Tout texte saisi par un utilisateur est suspect. S'il part dans un prompt d'IA, protège-le contre l'injection de prompt.

## Quand on te corrige

1. Applique la correction.
2. Déduis-en la règle générale.
3. Écris cette règle (ici ou dans un skill) **sans les détails de l'incident**.

Mauvais exemple : « Le 4 mars, vérifier le z-index de la bannière du paiement. »
Bon exemple : « Après tout changement de mise en page, vérifier qu'aucun élément cliquable n'est masqué. »

## Quand t'arrêter et demander au mainteneur

Arrête-toi et demande avant de :

- fusionner, poser un tag, lancer un build distribué, publier sur le Play Store ou relancer la CI ;
- toucher à l'authentification, aux paiements, aux permissions ou aux données des utilisateurs ;
- lancer une migration de base de données ou une commande destructive (suppression comprise) ;
- déployer en production, que ce soit sur le NAS, une image Docker ou le site ;
- trancher toi-même une décision produit.

**Pas de boucle.** Après deux échecs avec la même approche, arrête-toi et rapporte ce que tu as essayé et ce qui s'est passé.

## Quand on te demande un point

Dis ce qui est fait, ce qui est en cours et ce qui est bloqué. Si rien n'a changé, réponds « pas de changement ». Lors d'une vérification planifiée sans rien de nouveau, ne dis rien.

---

> Reproduis. Lance. Prouve. Corrige la cause, pas le symptôme.
> Quand tu te trompes, écris le principe, pas l'histoire.
