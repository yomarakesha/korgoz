# KörGöz — notes for AI coding sessions

Local-first video analytics platform (cameras → detection → tracking → events → analytics).
**No Docker, ever** (hard requirement of the spec).

## Start here

1. `docs/handoff.md` — current state, architecture essentials, phase-by-phase plan, known issues.
2. `docs/spec.md` — the original specification (phases 1–10, MVP checklist).
3. `README.md` — how to install/run (Linux step-by-step, Windows scripts).

Status: phases 1–10 done (foundation, cameras, YOLOX detection + live view, ByteTrack tracking,
SFace recognition + Qdrant + `/persons`, events + sessions + timeline + ontology, analytics,
React dashboard at `/ui/`, security: login sessions + argon2id + admin/user roles + audit log, optimization:
`scripts/benchmark_pipeline.py` + `docs/benchmarks.md`). Remaining work: tech debt in
`docs/handoff.md` §5. API reference: `docs/api.md`,
security: `docs/security.md`.

## Commands

```bash
source .venv/bin/activate
pytest                      # unit tests (no services needed)
pytest -m ai                # real models (python -m scripts.download_models --samples)
TEST_DATABASE_URL=... pytest -m integration   # + running Qdrant on QDRANT_URL
ruff check . && black --check . && mypy app tests scripts   # must stay clean
uvicorn app.main:app --reload    # API
python -m app.worker             # camera worker
python -m scripts.create_user admin --role admin   # first dashboard/API admin
cd frontend && npm run typecheck && npm test && npm run build   # dashboard (docs/dashboard.md)
```

## Conventions

- Work phase by phase; finish each with tests + docs. Report in the format
  STATUS / FILES CREATED / FILES MODIFIED / TESTS / HOW TO RUN / NEXT PHASE.
- The user is a Russian-speaking beginner/intermediate Python developer: explain what is
  being built and why before each phase, reply in Russian. Docs in Russian; code,
  comments and commit messages in English.
- New features plug into the worker as an `AnalysisSink` (`app/pipeline/types.py`) —
  don't rewrite the pipeline. Concrete models are created only in `app/pipeline/factory.py`.
- All settings in `app/config.py` (+ `.env.example`); secrets as `SecretStr`.
- Never log credentials or exception text that may contain URLs; use `redact()` /
  `type(exc).__name__`. Never store video, face images or raw embeddings on disk.
- Background DB writes in the worker go through the shared `DatabaseWriter`
  (`app/database/writer.py`) so tracks are written before their events.
- Every API route except `/health` and `/auth/login` needs a login: include new routers with
  `dependencies=[Depends(authorize)]` (GET = any user, writes = admin) in `app/main.py`.
  Audit changes with `record: AuditDep` before `db.commit()`; never put secrets, stream URLs
  or person names into audit `details`.
- Check model licenses (no AGPL / non-commercial weights).
