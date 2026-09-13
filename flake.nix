{
  description = "U-NDT board flake";

  inputs = {
    nixpkgs.url = "nixpkgs/nixos-25.05";
    
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          local-pico-sdk = pkgs.pico-sdk.override {
            withSubmodules = true;
          };
        in
        {
          app = pkgs.callPackage ./app/default.nix {};
          
          pico-firmware = pkgs.callPackage ./firmware/pico/default.nix {
            inherit local-pico-sdk;
          };
          
          default = self.packages.${system}.app;
        }
      );

      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          local-pico-sdk = pkgs.pico-sdk.override {
            withSubmodules = true;
          };

          pythonEnv = pkgs.python313.withPackages (ps: with ps; [
            numpy pyserial matplotlib h5py scipy pyqt5 pyqtgraph
          ]);

          qtEnv = pkgs.qt5.env "qt5-dev" [
            pkgs.qt5.qtdeclarative
            pkgs.qt5.qttools
            pkgs.libsForQt5.qcustomplot
          ];
        in
        {
          default = pkgs.mkShell {
            name = "u-ndt";

            packages = with pkgs; [
              zlib stdenv.cc gcc-unwrapped.lib cmake gcc
              gcc-arm-embedded 
              qtEnv qt5.wrapQtAppsHook qt5.qtbase qtcreator
            ];

            buildInputs = with pkgs; [
              pythonEnv
              local-pico-sdk picotool
              udisks tio binutils cmake pkg-config 
              gdb 
              makeWrapper bashInteractive
            ];
            
            PICO_SDK_PATH = "${local-pico-sdk}/lib/pico-sdk";
            QT_PLUGIN_PATH = "${pkgs.qt5.qtbase}/lib/qt-5/plugins";
            QML2_IMPORT_PATH = "${pkgs.qt5.qtdeclarative}/lib/qt-5/qml";

            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ];
            shellHook = ''
              zshdir=$(mktemp -d)
              makeWrapper "$(type -p zsh)" "$zshdir/zsh" "''${qtWrapperArgs[@]}"
              exec "$zshdir/zsh"
            '';
          };
        }
      );
    };
}
