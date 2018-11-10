{ pkgs ?  import <nixpkgs> {} }:

pkgs.python3.pkgs.buildPythonApplication rec {
  name = "nix-review";
  src = ./.;
  env = pkgs.buildEnv { inherit name; paths = buildInputs ++ checkInputs; };
  buildInputs = [ pkgs.makeWrapper ];
  checkInputs = [ pkgs.mypy pkgs.python3.pkgs.black pkgs.glibcLocales ];
  checkPhase = ''
    echo -e "\x1b[32m## run unittest\x1b[0m"
    ${pkgs.python3.interpreter} -m unittest discover .
    echo -e "\x1b[32m## run mypy\x1b[0m"
    mypy nix_review
    echo -e "\x1b[32m## run black\x1b[0m"
    LC_ALL=en_US.utf-8 black --check .
  '';
  makeWrapperArgs = [
    "--prefix PATH" ":" "${pkgs.nix}/bin"
  ];
}
