# Colibri v2.0

GUI GTK moderne (cartes + mode sombre) pour utiliser le moteur d'inférence
[Colibri](https://github.com/JustVugg/colibri) **sans terminal** — avec le
moteur **optimisé** inclus (perf UI + serveur, voir `COLIBRI_CHANGES.md`).

## Fonctions

- **Modèles** : 9 familles (Qwen3.8-Flash, GLM-5.3-Flash, DeepSeek V4.1...),
  statut local, ⬇ téléchargement HF, 🔨 build, 🗑 suppression
- **Moteur** : binaires présents, `make check`
- **Lancer** : ctx/cap/ngen/port/think, chat terminal, serve/stop, web,
  plan/doctor, **🔌 Opencode** (provider auto), **🔌 Hermes** (snippet)
- **Chat** style opencode : streaming SSE, 📎 fichiers (images lues par le
  moteur, txt/code inclus), sessions persistantes + suppression,
  horodatage discret, bulles contrastées
- **Système** : RAM / disque / GPU / version `coli`

## Installer (NixOS flake)

```nix
inputs.colibri.url = "github:Swam-web/colibri-v2.0";
# modules = [ colibri.nixosModules.bundle ];
# sudo nixos-rebuild switch --flake /etc/nixos#host
```
Une fois installé via le module : **« Colibri »** dans les applications
GNOME.

## Lancer

- **Installé (module)** : « Colibri » dans les applications.
- **Bundle complet (moteur + launcher)** :
```bash
nix run github:Swam-web/colibri-v2.0#colibri-bundle
```
- **Launcher seul** :
```bash
nix run github:Swam-web/colibri-v2.0#launcher
```
- **Depuis les sources** :
```bash
nix-shell -p python3Packages.pygobject3 python3Packages.pycairo gtk3 \
  gobject-introspection libnotify \
  --run "python3 launcher/app.py"
```

Prérequis runtime : `coli` accessible (fourni par le bundle),
un modèle téléchargé.

## Licence

Launcher : MIT — moteur : Apache-2.0, voir `LICENSE` (upstream
JustVugg/colibri).
