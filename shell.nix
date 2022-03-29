{ pkgs ? import <nixpkgs> { } }:

with pkgs;

pkgs.mkShell {
  buildInputs = [
    (import ./. { }).passthru.env
  ] ++ lib.optional stdenv.isLinux [
    bubblewrap
  ];
}
