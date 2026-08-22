.PHONY: generate test check install

generate:
	python3 generate.py

test:
	python3 -m unittest discover -s tests

check: test
	python3 -m py_compile generate.py tests/test_generate.py
	carapace --run amp.yaml >/dev/null

install: amp.yaml
	install -Dm644 amp.yaml "$${XDG_CONFIG_HOME:-$$HOME/.config}/carapace/specs/amp.yaml"
