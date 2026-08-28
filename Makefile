.PHONY: setup setup-managed check-managed runtime-versions setup-xverif check-xverif setup-wavepeek check-wavepeek test structure format sanitize example check release-check docs

setup:
	./scripts/setup

setup-managed:
	./scripts/setup_managed.sh

check-managed:
	./scripts/setup_managed.sh --check

runtime-versions:
	./scripts/runtime-versions

setup-xverif:
	python3 scripts/setup_xverif.py

check-xverif:
	python3 scripts/check_xverif.py

setup-wavepeek:
	python3 scripts/setup_wavepeek.py

check-wavepeek:
	python3 scripts/check_wavepeek.py

test:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 skills/verif-harness/add-regression-runner/scripts/test_regression_tools.py
	python3 skills/verif-harness/tests/test_capability_tools.py
	python3 skills/verif-harness/tests/test_freeze_tools.py

structure:
	python3 scripts/check_structure.py

format:
	python3 scripts/check_text_format.py

sanitize:
	python3 scripts/check_public_release.py

example:
	./scripts/run_example.sh

check: structure format test sanitize

release-check: check example

docs:
	python3 -m mkdocs build --strict
