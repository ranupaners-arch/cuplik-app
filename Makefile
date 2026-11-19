.PHONY: install install-transcription dev test lint build e2e types migrate sample eval eval-fixtures update-ytdlp validate-ingest
install:
	uv sync --locked
	npm ci --prefix web
install-transcription:
	uv sync --locked --extra transcription
validate-ingest:
	uv run --extra transcription python scripts/validate_ingest.py --video "$(VIDEO)"
dev:
	uv run python scripts/dev.py
migrate:
	uv run alembic upgrade head
sample:
	uv run python scripts/make_sample.py
eval:
	uv run python eval/evaluate.py
eval-fixtures:
	uv run python eval/evaluate.py --root eval/fixtures --require-predictions
test:
	uv run pytest
lint:
	uv run ruff check api worker scripts tests eval
	uv run ruff format --check api worker scripts tests eval
	npm run typecheck --prefix web
build:
	npm run build --prefix web
e2e:
	npm run test:e2e --prefix web
types:
	uv run python scripts/export_openapi.py
	npm exec --prefix web -- openapi-typescript docs/openapi.json -o web/src/lib/api.generated.ts
update-ytdlp:
	uv run python -m worker.pipeline.ytdlp
