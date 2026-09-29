# Update-plan CAS: `preview` saves plan, `up` applies it

## Problem

When we dispatch `pulumi up` from a PR to mutate real infrastructure, we currently have no compare-and-swap check between "diff we reviewed in the preview comment" and "diff the engine applies at `up` time". A drift window between preview and up — an out-of-band change, a merge of another PR, a mutation in the console — can silently widen the applied delta.

Concrete trigger: Open-Athena/ops#66 A/B-tests dropping `sts:GetServiceBearerToken` from an IAM policy. The reviewer wants to see the preview diff, then have `up` apply *exactly that diff and nothing more*. Two-step `preview` → read → `up` is a mitigation but not a guarantee.

Pulumi's engine supports this natively via **update plans** (`--save-plan` / `--plan`), gated behind `PULUMI_EXPERIMENTAL=true`. This spec wires that through the reusable workflow.

## Goal

Add a `plan-source` input to the reusable workflow. When `cmd=up` and `plan-source` is provided, the workflow downloads the plan artifact from an earlier `preview` run, verifies it against the current checkout, and passes it to `pulumi up --plan=...`. The engine then CAS-checks each planned step against what it would do now, and errors out if they differ.

## Non-goals

- **Reconstructing a plan from the preview comment's diff-fence.** The rendered diff in the PR comment is a human-readable summary; the plan file is structured JSON with full URNs, before/after property values, dependency ordering, and provider version pins. Round-tripping comment → plan is lossy. The plan artifact is the source of truth; the comment is the discovery mechanism.
- **Making update plans the default `up` mode.** Opt-in via `plan-source`, since (a) update plans are marked experimental by Pulumi, and (b) not every stack needs CAS.

## Design

### 1. Preview always saves a plan (artifact)

In the `preview` branch of the case in `Run Pulumi`:

```bash
preview)
  PULUMI_EXPERIMENTAL=true pulumi preview --patch --non-interactive \
    --save-plan=plan.json 2>&1 | tee pulumi-output.txt
  ;;
```

After the step, upload `plan.json` as an artifact:

```yaml
- name: Upload plan artifact
  if: inputs.cmd == 'preview' && steps.pulumi.outcome == 'success'
  uses: actions/upload-artifact@v4
  with:
    name: pulumi-plan-${{ inputs.project || 'default' }}-${{ inputs.stack }}
    path: ${{ inputs.working-directory }}/plan.json
    retention-days: 30
```

**Why save every preview:** artifacts are cheap (plans are KB–low-MB JSON), and the alternative (opt-in) means you can't retroactively decide to CAS-up a preview you already ran. One extra step in preview, no semantic change to output.

### 2. Comment embeds a plan marker

In the "Summary and PR comment" step, when `cmd=preview`, append a machine-readable HTML comment identifying the artifact:

```html
<!-- pulumi-plan: run_id=<GITHUB_RUN_ID> sha=<GITHUB_SHA> project=<project> stack=<stack> pulumi_sha=<PULUMI_FORK_SHA> -->
```

Rendered comments never show this. `up` uses it to resolve `plan-source: pr:<N>` to a specific run.

### 3. Up consumes the plan

New input:

```yaml
plan-source:
  description: |
    Source of a saved preview plan to CAS against. Accepts:
      - <run_id>       — GitHub Actions run id of a prior preview
      - pr:<N>         — latest preview comment on PR #N matching this project+stack
      - comment:<id>   — specific comment id whose marker to use
    Requires cmd=up.
  required: false
  type: string
plan-source-force:
  description: 'Skip the SHA/pulumi-version match check on the resolved plan (dangerous)'
  required: false
  default: false
  type: boolean
```

Resolution logic (new step before `Run Pulumi`, when `cmd=up` and `plan-source` non-empty):

1. Parse `plan-source`:
   - Numeric → treat as `run_id`
   - `pr:<N>` → `gh api repos/{owner}/{repo}/issues/<N>/comments` → for each comment posted by this workflow (identify via the `<!-- pulumi-plan: … -->` marker), filter to matching `project` + `stack`, pick the most recent, extract `run_id`
   - `comment:<id>` → fetch that comment, extract marker
2. Validate: current `github.sha` matches the marker's `sha` (unless `plan-source-force`). Same for `pulumi_sha`.
3. `gh run download <run_id> --name pulumi-plan-<project>-<stack> --dir "${{ inputs.working-directory }}"` → gets `plan.json`.

In the `up` branch:

```bash
up)
  PLAN_FLAG=""
  if [ -f plan.json ]; then
    PLAN_FLAG="--plan=plan.json"
    export PULUMI_EXPERIMENTAL=true
  fi
  pulumi up --yes --non-interactive $PLAN_FLAG 2>&1 | tee pulumi-output.txt
  ;;
```

If the engine's re-computed plan diverges from `plan.json`, it exits non-zero with a diff — that's the CAS failure, and it surfaces in the PR comment via the existing "Summary and PR comment" step. Good default; no extra plumbing needed.

## Open questions

1. **Plan-file version stability across Pulumi engine versions.** Should the marker include the Pulumi version and refuse `up` on a different one? Leaning: yes — record `pulumi_sha` (the `PULUMI_FORK_SHA` env we already have) in the marker, refuse mismatches unless `plan-source-force`. Provider versions (`pulumi-aws` etc.) also matter but are harder to pin from the workflow; the checkout SHA covers them if `pyproject.toml` pins are exact.
2. **Provider determinism.** Do our providers emit fully deterministic plans given identical state? `aws.iam.*` (our current use case): almost certainly yes. `aws.s3.*` / `gcp.storage.*` with server-side defaults filled in on refresh: possibly not — worth a smoke test before we recommend CAS-up for those stacks. Not a blocker for shipping the feature.
3. **Multi-project PRs.** A single PR could touch multiple projects (`oa-ci` and `oa-management`) → two plan artifacts, two markers in two separate comments (already how existing preview comments work). `pr:<N>` resolution has to filter on (project, stack) — the marker includes both. Confirmed unambiguous.
4. **Artifact retention.** GitHub artifacts default to 90 days; I set `retention-days: 30` above since a plan stale by a month is almost certainly wrong to apply. Tunable, but 30d is a safer default. Expired artifact → `gh run download` fails, `up` fails — feature not bug.
5. **`refresh` before `up`.** If someone runs `refresh` between the `preview` and the CAS-`up`, refresh changes stack state → plan mismatches → CAS fails. That's correct behavior (state changed underneath us), but worth documenting.
6. **First-preview-on-a-PR before `plan-source` was wired.** `pr:<N>` resolution should tolerate old preview comments without a marker (just skip them, keep looking).

## Testing plan

1. In a scratch stack:
   - Dispatch `cmd=preview` → verify `plan.json` artifact appears, marker embedded in comment.
   - Dispatch `cmd=up plan-source=<that run id>` → verify plan is downloaded and applied.
   - Make a config change to that stack out-of-band (in another PR, or console).
   - Dispatch `cmd=up plan-source=<original run id>` again → verify CAS failure surfaces.
2. Verify `plan-source: pr:<N>` picks the *latest* matching preview when the PR has multiple.
3. Multi-project: two projects, two previews, two `up`s each pointing at their own `pr:<N>` → both apply cleanly.
4. `plan-source-force=true` skips the SHA check → confirmed by manually mismatching SHAs.

## BC

- Default behavior unchanged: no `plan-source` → `up` runs as today (no `--plan`, no `PULUMI_EXPERIMENTAL`).
- `preview` gains a `--save-plan` invocation and an artifact upload. If `PULUMI_EXPERIMENTAL` gating causes any unexpected output-format change, we roll back that half separately.

## Rollout

1. Land the `preview`-side changes (`--save-plan`, artifact upload, marker in comment) first.
2. Verify markers appear + artifacts download cleanly on an existing PR.
3. Land the `up`-side changes.
4. Test end-to-end on Open-Athena/ops#66 (the trigger).

## Immediate consumer

Open-Athena/ops#66 wants to dispatch `up` on the `oa-ci` stack with CAS. After this ships:

```
gh workflow run pulumi.yml -R Open-Athena/ops --ref u/jder/ecr-login \
  -f project=oa-ci -f stack=dev -f cmd=preview
# review the diff in the PR comment
gh workflow run pulumi.yml -R Open-Athena/ops --ref u/jder/ecr-login \
  -f project=oa-ci -f stack=dev -f cmd=up -f plan-source=pr:66
```
