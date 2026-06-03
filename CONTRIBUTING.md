# Contributing

This is a solo project, but it follows a disciplined workflow on purpose — the process is part of what's graded, and a clean history makes the work defensible. These are the rules `CLAUDE.md` encodes, written for a human reader.

## Workflow: one phase, one branch, one PR

Work is organized into sections and phases tracked in `Checklist.md`. Each phase is:

1. A branch off `main`, named `feat/<NN>-<slug>` (e.g. `feat/03-python-tooling`).
2. Small, frequent commits using **conventional commits** (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
3. One PR into `main`, opened with the template in `.github/pull_request_template.md`.
4. Merged via **squash** once CI is green.
5. Ticked off in `Checklist.md`, with `CLAUDE.md §2` status updated.

Don't bleed scope across phases. If new work appears mid-phase, open a new branch or log a deferral in `deliverables/DECISIONS.md`.

## Before you push

Run the local gates from `backend/` — all must be green:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

`pytest` skips the eval gates by default (they're marked `-m eval` / `-m redteam`). Run the RAG gate manually before merging changes to `app/rag/`; the red-team gate runs automatically on PRs touching `app/guardrails/`.

## Decisions and deliverables

- Every meaningful choice goes in `deliverables/DECISIONS.md` as a `D-NNN`, **backed by a number**. Numbers that don't exist yet are marked `PENDING (measure)` — never guessed.
- Open questions live as `P-NNN` and graduate to a `D-NNN` (with a number) in the phase that resolves them.
- Update the relevant `deliverables/` file **in the same PR** as the code that changes it — not at the end.
- No secrets in Git. Application secrets resolve from Vault at runtime; `.env` holds only bootstrap values and is gitignored.

## Conventions

- `uv` for Python packaging; commit `uv.lock` after dependency changes.
- Pin every `# type: ignore` to a specific error code.
- Don't write `# TODO: figure out later` — finish the phase or log the deferral.
- Don't push directly to `main` (it's protected); everything flows through a `feat/*` branch and a PR.