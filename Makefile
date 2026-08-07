.PHONY: install test test-fast test-extended test-all lint typecheck clean dev hooks precommit push-both bump-version changelog

install:
	pip install -e ".[test]"

test:
	python tests/runner.py --batch 1

test-fast:
	python tests/runner.py --batch 1

test-extended:
	python tests/runner.py --batch 2

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
	mypy src/ --no-namespace-packages --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators

hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit .githooks/commit-msg .githooks/post-checkout

precommit:
	pre-commit run --all-files

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('.ruff_cache'), pathlib.Path('.pytest_cache'), pathlib.Path('htmlcov')]]"
	python -c "import os; [os.remove(f) for f in ['.coverage'] if os.path.exists(f)]"
	rm -rf *.egg-info 2>/dev/null; true

dev:
	python src/main.py boot

push-both:
	bash scripts/push-both.sh

bump-version:
	python scripts/bump-version.py

changelog:
	@git log $$(git describe --tags --abbrev=0 2>/dev/null || echo HEAD)..HEAD --pretty=%s --no-merges | sed 's/^/  /'
	@echo "--- 按类型统计 ---"
	@git log $$(git describe --tags --abbrev=0 2>/dev/null || echo HEAD)..HEAD --pretty=%s --no-merges | grep -oE '^(feat|fix|perf|refactor|docs|style|test|chore|build|ci|revert)' | sort | uniq -c | sort -rn
