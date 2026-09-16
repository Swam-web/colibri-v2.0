# Briques Nix réutilisables : import ./launcher.nix { inherit pkgs; }
{ pkgs }:
let
  pyEnv = pkgs.python3.withPackages (ps: with ps; [ pygobject3 pycairo ]);

  app = pkgs.stdenv.mkDerivation {
    name = "colibri-v2-launcher";
    src = ../app.py;
    dontUnpack = true;
    nativeBuildInputs = with pkgs; [ makeWrapper wrapGAppsHook3 gobject-introspection python3 ];
    buildInputs = with pkgs; [ gtk3 libnotify gsettings-desktop-schemas hicolor-icon-theme ];
    installPhase = ''
      mkdir -p $out/bin
      cp $src $out/bin/colibri-v2-launcher
      chmod +x $out/bin/colibri-v2-launcher
      patchShebangs $out/bin/colibri-v2-launcher
    '';
    preFixup = ''
      gappsWrapperArgs+=(
        --prefix PYTHONPATH : "${pyEnv}/${pkgs.python3.sitePackages}"
      )
    '';
  };

  desktop = pkgs.makeDesktopItem {
    name = "colibri-v2-launcher";
    desktopName = "Colibri v2.0";
    comment = "Launcher GUI pour le moteur Colibri (fork communautaire)";
    exec = "colibri-v2-launcher";
    icon = "colibri-v2";
    categories = [ "Network" "Science" "Settings" ];
    terminal = false;
    startupNotify = true;
  };

  icons = pkgs.stdenv.mkDerivation {
    name = "colibri-v2-icons";
    src = ../icons;
    installPhase = ''
      mkdir -p $out/share/icons/hicolor/scalable/apps
      cp $src/colibri-v2.svg $out/share/icons/hicolor/scalable/apps/
    '';
  };
in
{
  inherit app desktop icons;
}
