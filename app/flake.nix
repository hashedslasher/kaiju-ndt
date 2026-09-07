{
  inputs.nixpkgs.url = "github:nixos/nixpkgs";

  outputs = { self, nixpkgs }:
  let
    pkgs = nixpkgs.legacyPackages.x86_64-linux;
    qtEnv = pkgs.qt5.env "qt6-dev" [
      pkgs.qt5.qtdeclarative
      pkgs.qt5.qttools
      pkgs.libsForQt5.qcustomplot
    ];
  in {
    devShells.x86_64-linux.default = pkgs.mkShell {
      buildInputs = with pkgs; [
        qtEnv
        qt5.qtbase
        qtcreator
        stdenv.cc
        cmake
        gdb
        qt5.wrapQtAppsHook
        makeWrapper
        bashInteractive
      ];
      shellHook = ''
        export QT_PLUGIN_PATH="${qtEnv}/lib/qt-5/plugins"
        export QML_IMPORT_PATH="${qtEnv}/lib/qt-5/qml"
        
        # Wrap bash to ensure Qt apps find libraries
        bashdir=$(mktemp -d)
        makeWrapper "$(type -p bash)" "$bashdir/bash" "''${qtWrapperArgs[@]}"
        exec "$bashdir/bash"
      '';
    };
  };
}
