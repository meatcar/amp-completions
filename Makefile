.PHONY: generate test check install

generate:
	python3 generate.py --amp "$${AMP_BIN:-amp}"

test:
	python3 -m unittest discover -s tests

check: test
	python3 -m py_compile *.py tests/*.py
	carapace --run amp.yaml >/dev/null
	python3 check_generated.py --amp "$${AMP_BIN:-amp}"

install: amp.yaml
	install -Dm644 amp.yaml "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/specs/amp.yaml"
