{ inputs, ... }:
{
  perSystem =
    { inputs', pkgs, ... }:
    let
      amp-completions =
        pkgs.runCommand "amp-completions"
          {
            src = builtins.path {
              path = inputs.self + /src;
              name = "amp-completions-source";
            };
            nativeBuildInputs = [ pkgs.python3 ];
          }
          ''
            export HOME="$TMPDIR/home"
            mkdir -p "$HOME" "$out/share/amp-completions" "$out/share/carapace/specs"
            PYTHONPATH="$src" python3 -m amp_completions.generate \
              --amp "${inputs'.llm-agents.packages.amp}/bin/amp" \
              --output "$out/share/carapace/specs/amp.yaml" \
              --manifest-output "$out/share/amp-completions/amp-manifest.json"
          '';
    in
    {
      packages = {
        inherit amp-completions;
        default = amp-completions;
      };
    };
}
