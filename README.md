# Colibri v2.0 Launcher

GUI GTK moderne (cartes + mode sombre) pour utiliser le moteur d'inférence
[Colibri](https://github.com/JustVugg/colibri) **sans terminal** — fork
communautaire, moteur upstream inchangé (licence d'origine conservée).

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
inputs.colibri-v2.url = "github:Swam-web/colibri-v2.0";
# modules = [ colibri-v2.nixosModules.default ];
# sudo nixos-rebuild switch --flake /etc/nixos#host
```
Une fois installé via le module : **« Colibri v2.0 »** dans les applications
GNOME (icône verte).

## Lancer

- **Installé (module)** : « Colibri v2.0 » dans les applications.
- **Sans installer** :
```bash
nix run github:Swam-web/colibri-v2.0
```
- **Depuis les sources** :
```bash
nix-shell -p python3Packages.pygobject3 python3Packages.pycairo gtk3 \
  gobject-introspection libnotify \
  --run "python3 app.py"
```

Prérequis runtime : `coli` accessible, un modèle téléchargé.

## Licence

MIT — moteur : voir upstream JustVugg/colibri.
