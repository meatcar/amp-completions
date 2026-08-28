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
