.PHONY: generate test check install

PYTHON = PYTHONPATH=src python3

generate:
	$(PYTHON) -m amp_completions.generate --amp "$${AMP_BIN:-amp}"

test:
	$(PYTHON) -m unittest discover -s tests

check: test
	$(PYTHON) -m compileall -q src tests
	carapace --run amp.yaml >/dev/null
	$(PYTHON) -m amp_completions.check_generated --amp "$${AMP_BIN:-amp}"

install: amp.yaml
	install -Dm644 amp.yaml "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/specs/amp.yaml"
	install -Dm755 src/amp_completions/complete.py "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/bin/amp-completions"
	sed -i "1s|.*|#!$$(command -v python3)|" "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/bin/amp-completions"
	python3 -c 'import json, pathlib, sys; p = pathlib.Path(sys.argv[1]); p.write_text(p.read_text().replace("DEFAULT_AMP = \"amp\"", "DEFAULT_AMP = " + json.dumps(sys.argv[2])))' "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/bin/amp-completions" "$${AMP_BIN:-$$(command -v amp)}"
