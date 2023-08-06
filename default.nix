{ pkgs ? import <nixpkgs> { }
, withSandboxSupport ? false
, withAutocomplete ? true
, withNom ? false
}:

with pkgs;
let
  withNom' = withNom && (builtins.tryEval (builtins.elem buildPlatform.system pkgs.ghc.meta.platforms)).value or false;
in
python3.pkgs.buildPythonApplication {
  name = "nixpkgs-review";
  src = ./.;
  format = "pyproject";
  nativeBuildInputs = [ installShellFiles ] ++ lib.optional withAutocomplete python3.pkgs.argcomplete;
  propagatedBuildInputs = [ python3.pkgs.argcomplete ];

  nativeCheckInputs = [
    mypy
    python3.pkgs.setuptools
    python3.pkgs.black
    ruff
    glibcLocales

    # needed for interactive unittests
    python3.pkgs.pytest
    pkgs.nixVersions.stable or nix_2_4
    git
  ] ++ lib.optional withSandboxSupport bubblewrap
  ++ lib.optional withNom' nix-output-monitor;

  checkPhase = ''
    ${if pkgs.lib.versionAtLeast python3.pkgs.black.version "20" then ''
      echo -e "\x1b[32m## run black\x1b[0m"
      LC_ALL=en_US.utf-8 black --check .
    '' else ''
      echo -e "\033[0;31mskip running black (version too old)\x1b[0m"
    ''}
    echo -e "\x1b[32m## run ruff\x1b[0m"
    ruff .
    echo -e "\x1b[32m## run mypy\x1b[0m"
    mypy --strict nixpkgs_review
  '';
  makeWrapperArgs =
    let
      binPath = [ pkgs.nixVersions.stable or nix_2_4 git ]
        ++ lib.optional withSandboxSupport bubblewrap
        ++ lib.optional withNom' nix-output-monitor;
    in
    [
      "--prefix PATH : ${lib.makeBinPath binPath}"
      "--set-default NIX_SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt"
      # we don't have any runtime deps but nix-review shells might inject unwanted dependencies
      "--unset PYTHONPATH"
    ];

  postInstall = lib.optionalString withAutocomplete ''
    for cmd in nix-review nixpkgs-review; do
      installShellCompletion --cmd $cmd \
        --bash <(register-python-argcomplete $out/bin/$cmd) \
        --fish <(register-python-argcomplete $out/bin/$cmd -s fish) \
        --zsh <(register-python-argcomplete $out/bin/$cmd -s zsh)
    done
  '';

  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';
}
