{ lib, stdenv, cmake, qt5, libsForQt5, zlib }:

stdenv.mkDerivation {
  pname = "kaiju-viewer";
  version = "1.0.0";
  src = ./.;

  nativeBuildInputs = [ 
    cmake 
    qt5.wrapQtAppsHook 
  ];
  
  buildInputs = [
    qt5.qtbase
    qt5.qtdeclarative
    qt5.qttools
    libsForQt5.qcustomplot
    zlib
  ];

  QT_PLUGIN_PATH = "${qt5.qtbase}/${qt5.qtbase.qtPluginPrefix}";
  QML2_IMPORT_PATH = "${qt5.qtdeclarative}/${qt5.qtbase.qtQmlPrefix}";

  installPhase = ''
    mkdir -p $out/bin
    cp kaiju-viewer $out/bin/ || true
  '';
}
