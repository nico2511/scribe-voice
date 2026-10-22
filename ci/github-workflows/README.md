# Workflows GitHub Actions (à activer)

`ci.yml` et `release.yml` doivent vivre dans `.github/workflows/`.
Ils sont provisoirement ici parce que le jeton OAuth `gh` utilisé pour pousser cette
branche n'a pas le scope `workflow` (GitHub refuse alors tout fichier sous `.github/workflows/`).

Activation (une fois, avec un jeton ayant le scope `workflow`) :

```bash
gh auth refresh -h github.com -s workflow
git switch release/v1.0
mkdir -p .github/workflows
git mv ci/github-workflows/ci.yml ci/github-workflows/release.yml .github/workflows/
git rm ci/github-workflows/README.md
git commit -m "Activer les workflows CI et release"
git push
```
