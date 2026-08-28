{ inputs, ... }:
{
  perSystem =
    {
      config,
      inputs',
      pkgs,
      ...
    }:
    let
      generated = config.packages.amp-completions;
      customAmp = pkgs.writeShellScriptBin "amp" ''
        case "''${1-}" in
          --help) echo "Options:" ;;
          version) echo "9.8.7" ;;
          *) exit 1 ;;
        esac
      '';
      customCompletions = inputs.self.lib.mkAmpCompletions {
        inherit pkgs;
        amp = "${customAmp}/bin/amp";
      };
    in
    {
      checks.custom-amp = pkgs.runCommand "custom-amp-completions-check" { } ''
        grep -Fx "# Amp version: 9.8.7" \
          "${customCompletions}/share/carapace/specs/amp.yaml"
        touch "$out"
      '';
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
            make test
            python3 -m compileall -q src tests
            PYTHONPATH=src python3 -m amp_completions.generate \
              --amp "$AMP_BIN" \
              --output "$TMPDIR/amp.yaml" \
              --manifest-output "$TMPDIR/amp-manifest.json"
            carapace --run "${generated}/share/carapace/specs/amp.yaml" >/dev/null
            diff -u amp.yaml "${generated}/share/carapace/specs/amp.yaml"
            diff -u amp-manifest.json "${generated}/share/amp-completions/amp-manifest.json"
            diff -u "$TMPDIR/amp.yaml" "${generated}/share/carapace/specs/amp.yaml"
            diff -u "$TMPDIR/amp-manifest.json" "${generated}/share/amp-completions/amp-manifest.json"
            touch "$out"
          '';
    };
}
