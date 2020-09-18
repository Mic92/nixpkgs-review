{
  description = "nixpkgs-review";

  outputs = { self, nixpkgs }: {
    packages.x86_64-linux.nixpkgs-review = import ./. {
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    };

    defaultPackage.x86_64-linux = self.packages.x86_64-linux.nixpkgs-review;
  };
}
