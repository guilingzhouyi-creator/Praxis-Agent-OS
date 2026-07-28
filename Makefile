.PHONY: install test lint typecheck clean dev

install:
	pip install -e ".[test]"

test:
	python -m pytest tests/test_kernel.py -x -q --tb=short

test-all:
	python tests/runner.py

lint:
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

format:
	ruff format src/ tests/

format-check:
	ruff format --check src/ tests/

typecheck:
	mypy src/ --python-version 3.11 --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators

hooks:
	git config core.hooksPath .githooks

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('.ruff_cache'), pathlib.Path('.pytest_cache'), pathlib.Path('htmlcov')]]"
	python -c "import os; [os.remove(f) for f in ['.coverage'] if os.path.exists(f)]"
	rm -rf *.egg-info 2>/dev/null; true

dev:
	python src/main.py boot
