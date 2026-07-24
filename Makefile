.PHONY: install format lint test security package check run docker-build

install:
	python -m pip install -e '.[dev]'

format:
	ruff check --fix .
	ruff format .

lint:
	ruff check .
	ruff format --check .
	mypy seo_analyzer

test:
	pytest --cov=seo_analyzer --cov-report=term-missing --cov-report=xml

security:
	pip-audit

package:
	python -m build

check: lint test security package

run:
	uvicorn main:app --reload

docker-build:
	docker build --tag saas-seo-analyzer:local .
