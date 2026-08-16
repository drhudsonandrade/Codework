.PHONY: check test smoke catalog serve package docker-build docker-run

check:
	python -m genoma_policy ruleset-check

test:
	python -m unittest discover -s tests -v

smoke:
	python -m genoma_policy smoke

catalog:
	python -m genoma_policy catalog --output genoma-ruleset-catalog.json

serve:
	python -m genoma_policy serve --host 127.0.0.1 --port 8787

package:
	python -m pip install --no-build-isolation --no-deps .

docker-build:
	docker build -f Dockerfile -t genoma-policy-engine:0.2.0 ..

docker-run:
	docker compose -f docker-compose.yml up --build
