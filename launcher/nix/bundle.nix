# Bundle Colibri optimisé + launcher GTK.
# Usage (depuis la racine du fork) : import ./launcher/nix/bundle.nix { inherit pkgs colibri; }
{ pkgs, colibri }:
let
  pyEnv = pkgs.python3.withPackages (ps: with ps; [ pygobject3 pycairo ]);

  app = pkgs.stdenv.mkDerivation {
    name = "colibri-launcher";
    src = ../app.py;
    dontUnpack = true;
    nativeBuildInputs = with pkgs; [ makeWrapper wrapGAppsHook3 gobject-introspection python3 ];
    buildInputs = with pkgs; [ gtk3 libnotify gsettings-desktop-schemas hicolor-icon-theme ];
    installPhase = ''
      mkdir -p $out/bin
      cp $src $out/bin/colibri-launcher
      chmod +x $out/bin/colibri-launcher
      patchShebangs $out/bin/colibri-launcher
    '';
    preFixup = ''
      gappsWrapperArgs+=(
        --prefix PYTHONPATH : "${pyEnv}/${pkgs.python3.sitePackages}"
        --prefix PATH : "${colibri}/bin"
      )
    '';
  };

  desktop = pkgs.makeDesktopItem {
    name = "colibri-launcher";
    desktopName = "Colibri";
    comment = "Moteur Colibri optimisé + launcher (sans terminal)";
    exec = "colibri-launcher";
    icon = "colibri-v2";
    categories = [ "Network" "Science" "Settings" ];
    terminal = false;
    startupNotify = true;
  };

  icons = pkgs.stdenv.mkDerivation {
    name = "colibri-launcher-icons";
    src = ../icons;
    installPhase = ''
      mkdir -p $out/share/icons/hicolor/scalable/apps
      cp $src/colibri-v2.svg $out/share/icons/hicolor/scalable/apps/
    '';
  };

  bundle = pkgs.symlinkJoin {
    name = "colibri-bundle";
    paths = [ colibri app desktop icons ];
  };
in
{
  inherit app desktop icons bundle;
}
