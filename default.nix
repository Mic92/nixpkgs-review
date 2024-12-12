{
  pkgs ? import <nixpkgs> { },
  withSandboxSupport ? false,
  withAutocomplete ? true,
  withNom ? false,
}:

with pkgs;
let
  withNom' =
    withNom
    && (builtins.tryEval (builtins.elem buildPlatform.system pkgs.ghc.meta.platforms)).value or false;
in
python3.pkgs.buildPythonApplication {
  name = "nixpkgs-review";
  src = ./.;
  format = "pyproject";
  nativeBuildInputs = [ installShellFiles ] ++ lib.optional withAutocomplete python3.pkgs.argcomplete;
  propagatedBuildInputs = [ python3.pkgs.argcomplete ];

  nativeCheckInputs =
    [
      python3.pkgs.setuptools
      python3.pkgs.pylint
      glibcLocales

      # needed for interactive unittests
      python3.pkgs.pytest
      pkgs.nixVersions.stable or nix_2_4
      git
    ]
    ++ lib.optional withSandboxSupport bubblewrap
    ++ lib.optional withNom' nix-output-monitor;

  checkPhase = ''
    echo -e "\x1b[32m## run nixpkgs-review --help\x1b[0m"

    NIX_STATE_DIR=$TMPDIR/var/nix $out/bin/nixpkgs-review --help
  '';
  makeWrapperArgs =
    let
      binPath =
        [
          pkgs.nixVersions.stable or nix_2_4
          git
        ]
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
        --bash <(register-python-argcomplete $cmd) \
        --fish <(register-python-argcomplete $cmd -s fish) \
        --zsh <(register-python-argcomplete $cmd -s zsh)
    done
  '';

  shellHook = ''
    # workaround because `python setup.py develop` breaks for me
  '';
}
