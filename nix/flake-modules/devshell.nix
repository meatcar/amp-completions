{ ... }:
{
  imports = [
    ./treefmt.nix
  ];
  perSystem =
    {
      inputs',
      pkgs,
      config,
      ...
    }:
    {
      legacyPackages = pkgs;
      devShells.default = pkgs.mkShell {
        name = "amp-completions";
        AMP_BIN = "${inputs'.llm-agents.packages.amp}/bin/amp";
        inputsFrom = [
          config.flake-root.devShell
          config.treefmt.build.devShell
        ];
        buildInputs =
          with pkgs;
          (builtins.attrValues config.treefmt.build.programs)
          ++ [
            nil # nix lsp
            carapace
            gnumake
            python3
          ];
      };
    };
}
