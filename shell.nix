{ pkgs ? import <nixpkgs> { } }:

with pkgs;

pkgs.mkShell {
  buildInputs = [
    (import ./. { }).passthru.python
  ] ++ lib.optional stdenv.isLinux [
    bubblewrap
  ];
}
