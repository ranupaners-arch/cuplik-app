.DEFAULT_GOAL := help
.PHONY: help doctor install install-transcription dev test lint build e2e types migrate sample eval eval-fixtures update-ytdlp validate-ingest
help:
	@printf '%s\n' \
	  'Cuplik — perintah lokal' \
	  '  make doctor          Periksa dependensi lokal tanpa menjalankan aplikasi' \
	  '  make install         Pasang dependensi backend dan web' \
	  '  make dev             Jalankan aplikasi, API, worker, dan Redis' \
	  '  make lint            Periksa Python dan TypeScript' \
	  '  make test            Tes backend, termasuk render FFmpeg' \
	  '  make e2e             Uji browser dan workflow lengkap' \
	  '  make build           Build produksi web' \
	  '  make sample          Buat video sintetis untuk uji unggah' \
	  '  make types           Perbarui OpenAPI dan tipe frontend' \
	  '  make eval            Evaluasi dataset beranotasi jika tersedia'
doctor:
	python3 scripts/check_setup.py
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
