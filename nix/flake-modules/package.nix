{ inputs, ... }:
let
  mkAmpCompletions =
    { pkgs, amp }:
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
        mkdir -p \
          "$HOME" \
          "$out/share/amp-completions" \
          "$out/share/carapace/bin" \
          "$out/share/carapace/specs"
        PYTHONPATH="$src" python3 -m amp_completions.generate \
          --amp "${amp}" \
          --output "$out/share/carapace/specs/amp.yaml" \
          --manifest-output "$out/share/amp-completions/amp-manifest.json"
        install -m755 \
          "$src/amp_completions/complete.py" \
          "$out/share/carapace/bin/amp-completions"
        substituteInPlace "$out/share/carapace/bin/amp-completions" \
          --replace-fail 'DEFAULT_AMP = "amp"' 'DEFAULT_AMP = "${amp}"'
        patchShebangs "$out/share/carapace/bin/amp-completions"
      '';
in
{
  flake.lib = { inherit mkAmpCompletions; };
  perSystem =
    { inputs', pkgs, ... }:
    let
      amp-completions = mkAmpCompletions {
        inherit pkgs;
        amp = "${inputs'.llm-agents.packages.amp}/bin/amp";
      };
    in
    {
      packages = {
        inherit amp-completions;
        default = amp-completions;
      };
    };
}
