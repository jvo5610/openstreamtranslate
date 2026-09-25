.PHONY: remote-sync remote-start remote-stop tunnel up down logs smoke acceptance stress

remote-sync:
	./scripts/remote-sync.sh

remote-start:
	./scripts/remote-start.sh

remote-stop:
	./scripts/remote-stop.sh

tunnel:
	./scripts/tunnel.sh

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f app

smoke:
	./scripts/smoke-test.sh

acceptance:
	./scripts/acceptance-check.sh

stress:
	./scripts/stress-test.sh
