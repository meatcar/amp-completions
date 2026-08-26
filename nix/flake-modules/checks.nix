{ inputs, ... }:
{
  perSystem =
    { inputs', pkgs, ... }:
    {
      checks.completions =
        pkgs.runCommand "amp-completions-check"
          {
            src = inputs.self;
            AMP_BIN = "${inputs'.llm-agents.packages.amp}/bin/amp";
            nativeBuildInputs = with pkgs; [
              carapace
              gnumake
              python3
            ];
          }
          ''
            cp -R "$src" source
            chmod -R u+w source
            cd source
            export HOME="$TMPDIR/home"
            mkdir -p "$HOME"
            make check
            touch "$out"
          '';
    };
}
