.PHONY: run daily test

run:
	python -m app run --profile default

daily:
	python -m app daily --profile default

test:
	python -m pytest -q
