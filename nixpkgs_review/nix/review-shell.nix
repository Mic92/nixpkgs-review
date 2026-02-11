{
  # Path to json file containing the outputs of all built packages
  outputs-path,
}:
let
  inherit (import <nixpkgs> { }) lib buildEnv mkShell;

  outputs = map builtins.storePath (builtins.fromJSON (builtins.readFile outputs-path));
  supportIgnoreSingleFileOutputs = (lib.functionArgs buildEnv) ? ignoreSingleFileOutputs;
  env = buildEnv (
    {
      name = "env";
      paths = outputs;
      ignoreCollisions = true;
    }
    // lib.optionalAttrs supportIgnoreSingleFileOutputs {
      ignoreSingleFileOutputs = true;
    }
  );
in
mkShell {
  name = "review-shell";
  preferLocalBuild = true;
  allowSubstitutes = false;
  dontWrapQtApps = true;
  # see test_rev_command_with_pkg_count
  packages = if builtins.length outputs > 50 then [ env ] else outputs;
}
