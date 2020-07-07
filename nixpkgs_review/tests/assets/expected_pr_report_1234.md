##### Result of `nixpkgs-review pr 1234` [1](https://github.com/Mic92/nixpkgs-review)
<details>
  <summary>1 package failed to build:</summary>
<br>- baz
</details>
<details>
  <summary>2 packages built:</summary>
<br>- foo
<br>- bar
</details>

<!-- remove inapropriate review points sections -->

##### Reviewed points (package update)
- [ ] package name fits guidelines
- [ ] package version fits guidelines
- [ ] package build on <ARCHITECTURE>
- [ ] executables tested on <ARCHITECTURE>
- [ ] all depending packages build

##### Reviewed points (new package)
- [ ] package path fits guidelines
- [ ] package name fits guidelines
- [ ] package version fits guidelines
- [ ] package build on <ARCHITECTURE>
- [ ] executables tested on <ARCHITECTURE>
- [ ] `meta.description` is set and fits guidelines
- [ ] `meta.license` fits upstream license
- [ ] `meta.platforms` is set
- [ ] `meta.maintainers` is set
- [ ] build time only dependencies are declared in `nativeBuildInputs`
- [ ] source is fetched using the appropriate function
- [ ] phases are respected
- [ ] patches that are remotely available are fetched with `fetchpatch`

##### Reviewed points (module update)
- [ ] changes are backward compatible
- [ ] removed options are declared with `mkRemovedOptionModule`
- [ ] changes that are not backward compatible are documented in release notes
- [ ] module tests succeed on <ARCHITECTURE>
- [ ] options types are appropriate
- [ ] options description is set
- [ ] options example is provided
- [ ] documentation affected by the changes is updated

##### Reviewed points (module update)
- [ ] module path fits the guidelines
- [ ] module tests succeed on <ARCHITECTURE>
- [ ] options have appropriate types
- [ ] options have default
- [ ] options have example
- [ ] options have descriptions
- [ ] No unneeded package is added to environment.systemPackages
- [ ] meta.maintainers is set
- [ ] module documentation is declared in meta.doc

##### Possible improvements

##### Comments

