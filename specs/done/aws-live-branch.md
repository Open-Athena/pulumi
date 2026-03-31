# `live-branch` input: monotonic deployment pointer

## Problem

`pulumi up` can be dispatched from any branch (PR or main). Without coordination, two concurrent PRs could race — each `up`ing over the other, or a stale branch could revert a newer deployment.

## Design

The reusable workflow gets a new optional `live-branch` input. When set and `cmd == "up"`:

1. **Pre-step**: verify HEAD descends from the current `live-branch` pointer
2. **Run**: `pulumi up` as normal
3. **Post-step** (on success only): fast-forward `live-branch` to HEAD

### Ancestry check (pre-`up`)

```bash
git fetch origin "$LIVE_BRANCH" || {
  echo "::notice::live-branch '$LIVE_BRANCH' does not exist yet, skipping ancestry check"
  exit 0
}
LIVE_SHA=$(git rev-parse "origin/$LIVE_BRANCH")

if ! git merge-base --is-ancestor "$LIVE_SHA" HEAD; then
  echo "::error::Cannot up: HEAD is not a descendant of $LIVE_BRANCH ($LIVE_SHA). Rebase onto $LIVE_BRANCH first."
  exit 1
fi
```

### Update pointer (post-`up`)

```bash
git push origin "HEAD:refs/heads/$LIVE_BRANCH"
```

Fast-forward by construction (ancestry verified above). If two concurrent `up`s race, the second push fails (non-fast-forward) — desired behavior.

### `preview` and `refresh`

Unrestricted — no ancestry check, no pointer update. Any branch can `preview`.

## Changes to `pulumi.yml`

### New input

```yaml
inputs:
  live-branch:
    description: 'Branch to track last successful `up`. If set, enforces monotonic ancestry for `up` commands.'
    required: false
    type: string
    default: ''
```

### New permission

```yaml
permissions:
  contents: write  # needed to push live-branch pointer (upgrade from read)
```

Note: this is only needed when `live-branch` is set. The workflow already has `contents: read`. The caller must also grant `contents: write`.

### New steps

Add two steps around the existing "Run Pulumi" step:

1. **Before** "Run Pulumi": ancestry check (conditional on `inputs.cmd == 'up' && inputs.live-branch != ''`)
2. **After** "Run Pulumi": update pointer (conditional on same + success)

## Caller usage (in `Open-Athena/ops`)

```yaml
jobs:
  pulumi:
    uses: Open-Athena/pulumi/.github/workflows/pulumi.yml@v1
    with:
      cmd: ${{ inputs.cmd }}
      stack: ${{ inputs.stack }}
      project: ${{ inputs.project }}
      working-directory: aws/${{ inputs.project }}
      deps-directory: aws
      live-branch: aws-live
    permissions:
      contents: write
      id-token: write
```

## Bootstrap

```bash
# In Open-Athena/ops: point aws-live at the last successfully up'd commit
# (currently HEAD of rw/pulumi-test-role, which was the last `up`)
git push o <last-up-sha>:refs/heads/aws-live
```

## Open questions

- Per-stack branches (`aws-live/oa-ci/dev`) vs single `aws-live`? Start with single, split later if needed.
- Add `concurrency` key to serialize `up` invocations? Push-time rejection is probably sufficient.
