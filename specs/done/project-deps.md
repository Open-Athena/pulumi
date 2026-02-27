# Per-project dependency installation

## Problem

The reusable workflow installs dependencies from `deps-directory` (shared deps like `pulumi-aws`), but some Pulumi projects need additional packages (e.g. `oa-ci-gha` needs `pulumi-gcp`). Currently there's no way for a project to declare its own extra deps.

## Current behavior

The "Install dependencies" step runs in `deps-directory` (falling back to `working-directory`):

```bash
if [ -f pyproject.toml ]; then
  uv pip install --system -e .
elif [ -f requirements.txt ]; then
  uv pip install --system -r requirements.txt
fi
```

This installs the shared deps but ignores any project-specific requirements.

## Proposed change

After installing shared deps, also check `working-directory` for a `requirements.txt`:

```bash
# Install shared deps (from deps-directory)
if [ -f pyproject.toml ]; then
  uv pip install --system -e .
elif [ -f requirements.txt ]; then
  uv pip install --system -r requirements.txt
fi

# Install project-specific deps (from working-directory, if different)
if [ "$DEPS_DIR" != "$WORK_DIR" ] && [ -f "$WORK_DIR/requirements.txt" ]; then
  uv pip install --system -r "$WORK_DIR/requirements.txt"
fi
```

The `!= WORK_DIR` guard avoids double-installing when `deps-directory` and `working-directory` are the same (or when `deps-directory` is unset and defaults to `working-directory`).

## Caller usage

In `Open-Athena/ops`, `aws/oa-ci-gha/requirements.txt` would contain:

```
pulumi-gcp>=7.0.0,<8.0.0
```

No changes needed to the caller workflow — the reusable workflow picks it up automatically.

## Scope

This is a one-line addition to the "Install dependencies" step. No new inputs required.
