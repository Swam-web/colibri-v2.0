# Colibri v2.0 Launcher (paquet NixOS)
#
# Usage dans votre flake :
#   inputs.colibri-v2.url = "github:VOTRE-USER/colibri-v2-launcher";
#   modules = [ colibri-v2.nixosModules.default ];
{ config, lib, pkgs, ... }:
let
  l = import ./launcher.nix { inherit pkgs; };
in
{
  environment.systemPackages = [ l.app l.desktop l.icons ];
}
