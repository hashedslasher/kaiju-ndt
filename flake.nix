{
  description = "U-NDT board flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          local-pico-sdk = pkgs.pico-sdk.override {
            withSubmodules = true;
          };

          pythonEnv = pkgs.python314.withPackages (ps: with ps; [
            numpy
            pyserial
            matplotlib
            h5py
            scipy
          ]);
        in
        {
          default = pkgs.mkShell {
            name = "u-ndt-pic0rick";

            buildInputs = with pkgs; [
              pythonEnv
              zlib
              stdenv.cc.cc.lib
              gcc-unwrapped.lib

              gcc-arm-embedded
              local-pico-sdk
              picotool
              cmake
              udisks
              tio

              glibc.dev
              binutils
              gcc
              cmake
              ninja
              pkg-config
              qt5.wrapQtAppsHook            
              qt5.qtbase
              qtcreator
            ];

            PICO_SDK_PATH = "${local-pico-sdk}/lib/pico-sdk";
            
            QT_PLUGIN_PATH = "${pkgs.qt5.qtbase}/lib/qt-5/plugins";
            QML2_IMPORT_PATH = "${pkgs.qt5.qtdeclarative}/lib/qt-5/qml";

            LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
              pkgs.zlib
            ];

            shellHook = ''
              exec zsh
            '';
          };
        }
      );
    };
}
