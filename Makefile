.PHONY: up down test logs
up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example. Put real keys in it, then run 'make up' again." && exit 1)
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000  Backend: http://localhost:8000/health"
down:
	docker compose down
test:
	cd backend && pip install -q -r requirements-dev.txt && python -m pytest -q
logs:
	docker compose logs -f
