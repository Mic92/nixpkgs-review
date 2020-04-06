{ pkgs ?  import <nixpkgs> {} }:

with pkgs;
python3.pkgs.buildPythonApplication rec {
  name = "nixpkgs-review";
  src = ./.;
  buildInputs = [ makeWrapper ];
  checkInputs = [ mypy python3.pkgs.black python3.pkgs.flake8 glibcLocales ];
  checkPhase = ''
    echo -e "\x1b[32m## run unittest\x1b[0m"
    ${pkgs.python3.interpreter} -m unittest discover .
    echo -e "\x1b[32m## run black\x1b[0m"
    LC_ALL=en_US.utf-8 black --check .
    echo -e "\x1b[32m## run flake8\x1b[0m"
    flake8 nixpkgs_review
    echo -e "\x1b[32m## run mypy\x1b[0m"
    mypy nixpkgs_review
  '';
  makeWrapperArgs = [
    "--prefix PATH" ":" "${nix}/bin"
  ];
  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';

  passthru.env = buildEnv { inherit name; paths = buildInputs ++ checkInputs; };
}
