{
  pkgs ? import <nixpkgs> { },
}:

with pkgs;

callPackage ./. {
  withSandboxSupport = stdenv.isLinux;
  withNom = true;
}
