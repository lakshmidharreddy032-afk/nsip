PY ?= python
CORE = services/core-api
AUTH = services/auth-service

.PHONY: help install up down seed dev test test-backend test-frontend lint typecheck eval synthetic e2e load openapi workbook clean

help:
	@echo "install | up | down | seed | dev | test | lint | typecheck | eval | synthetic | e2e | load | openapi"

install:
	$(PY) -m pip install -e "$(AUTH)[dev]" -e "$(CORE)[dev]"
	npm install

up:
	docker compose up --build -d
	@echo "Workbench: http://localhost:8080  (login at /login)"

down:
	docker compose down

seed:
	cd $(AUTH) && $(PY) -m app.seed
	cd $(CORE) && $(PY) ../../scripts/seed.py --only core --with-data

dev:  ## run all services locally without Docker (SQLite, in-process mock gateway)
	cd $(AUTH) && AUTH_COOKIE_SECURE=false $(PY) -m uvicorn app.main:app --port 8001 &
	cd $(CORE) && NSIP_AI_GATEWAY_MODE=inprocess $(PY) -m uvicorn app.main:app --port 8000 &
	npm run dev --workspace @nsip/auth-web &
	npm run dev --workspace @nsip/workbench-web

test: test-backend test-frontend

test-backend:
	cd $(AUTH) && $(PY) -m pytest --cov=app --cov-fail-under=85
	cd $(CORE) && $(PY) -m pytest --cov=app --cov-fail-under=85

test-frontend:
	npm run test --workspaces

lint:
	ruff check $(AUTH)/app $(AUTH)/tests $(CORE)/app $(CORE)/tests eval scripts
	npm run lint --workspaces

typecheck:
	cd $(AUTH) && mypy app
	cd $(CORE) && mypy app
	npm run typecheck --workspaces

synthetic:
	$(PY) eval/synthetic/generate.py --out eval/datasets/default --count 300 --seed 7

eval: ## spec section 15 acceptance report -> eval/reports/
	@test -f eval/datasets/default/labels.jsonl || $(MAKE) synthetic
	PYTHONPATH=$(CORE) $(PY) eval/run_eval.py --dataset eval/datasets/default

e2e:
	cd apps/workbench-web && npx playwright test

load:
	locust -f scripts/load_test/locustfile.py --headless -u 50 -r 10 -t 5m --host http://localhost:8080

openapi:
	cd $(CORE) && $(PY) -c "import json,app.main as m;json.dump(m.app.openapi(),open('../../docs/api/core-api.openapi.json','w'),indent=2)"
	cd $(AUTH) && $(PY) -c "import json,app.main as m;json.dump(m.app.openapi(),open('../../docs/api/auth-service.openapi.json','w'),indent=2)"

workbook:
	$(PY) $(CORE)/scripts/make_rating_workbook.py

clean:
	rm -rf $(CORE)/var $(AUTH)/var eval/reports/*.json apps/*/dist
