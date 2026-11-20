.PHONY: setup dev reset senso verify keepalive smoke scenarios

setup:            ## create venv, install deps, browsers, frontend packages
	python3 -m venv .venv
	.venv/bin/pip install -q fastapi "uvicorn[standard]" pydantic-settings httpx pyyaml jinja2 python-multipart singlestoredb anthropic playwright pillow numpy python-dotenv
	.venv/bin/playwright install chromium
	cd frontend && npm install
	@test -f .env || cp .env.example .env

dev:              ## run mock world :8001, backend :8000, frontend :5173
	./scripts/dev.sh

reset:            ## reset + stage the demo via the running backend (falls back to a plain seed)
	@curl -sf -X POST localhost:8000/api/demo/reset | python3 -m json.tool || .venv/bin/python -W ignore -m scripts.seed

senso:            ## load policy docs into Senso and run a test query
	.venv/bin/python -W ignore -m scripts.load_senso

verify:           ## health + audit chain check against a running backend
	@curl -s localhost:8000/api/health | python3 -m json.tool
	@curl -s localhost:8000/api/audit/verify

keepalive:        ## ping SingleStore every 4 min so the workspace doesn't auto-suspend
	.venv/bin/python -W ignore -m scripts.keepalive

smoke:            ## end-to-end smoke test against the running stack
	.venv/bin/python -W ignore -m scripts.smoke

scenarios:        ## run tests/scenarios/*.yaml and print the pass rate
	.venv/bin/python -W ignore -m scripts.run_scenarios
