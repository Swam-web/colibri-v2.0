{
  description = "Colibri v2.0 Launcher - GUI GTK pour le moteur d'inference Colibri (fork communautaire)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      l = import ./nix/launcher.nix { inherit pkgs; };
    in
    {
      packages.${system} = {
        colibri-v2 = l.app;
        default = l.app;
      };
      apps.${system} = {
        colibri-v2 = {
          type = "app";
          program = "${l.app}/bin/colibri-v2-launcher";
        };
        default = self.apps.${system}.colibri-v2;
      };
      nixosModules.colibri-v2 = import ./nix/module.nix;
      nixosModules.default = self.nixosModules.colibri-v2;
    };
}
