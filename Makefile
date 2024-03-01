.PHONY: format

python_files = tests *.py

format:
	ruff check --select I --fix $(python_files)
	ruff format --preview $(python_files)

lint:
	ruff check --preview $(python_files)
	mypy $(python_files)
