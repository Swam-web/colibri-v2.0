# Launcher Colibri (inclus dans ce repo)

GUI GTK pour utiliser ce moteur **sans terminal** : modèles, build,
serve, chat, système. Voir `app.py`.

## Utiliser avec le moteur de ce repo (recommandé)

```bash
# Launcher seul (moteur trouvé via PATH) :
nix run .#launcher
# Bundle complet (moteur optimisé + launcher) :
nix run .#colibri-bundle
# ou directement :
nix build .#colibri-bundle
./result/bin/colibri-launcher
```

## Module NixOS

```nix
inputs.colibri.url = "github:Swam-web/colibri-v2.0";
modules = [ colibri.nixosModules.bundle ];
```

« Colibri » apparaît alors dans les applications GNOME.

## Sans installer

```bash
nix-shell -p python3Packages.pygobject3 python3Packages.pycairo gtk3 \
  gobject-introspection libnotify \
  --run "python3 launcher/app.py"
```

Prérequis runtime : `coli` accessible (fourni par `colibri-bundle`),
un modèle téléchargé.
