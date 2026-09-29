# Update-plan CAS: `preview` saves plan, `up` applies it

## Problem

When we dispatch `pulumi up` from a PR to mutate real infrastructure, we currently have no compare-and-swap check between "diff we reviewed in the preview comment" and "diff the engine applies at `up` time". A drift window between preview and up — an out-of-band change, a merge of another PR, a mutation in the console — can silently widen the applied delta.

Concrete trigger: Open-Athena/ops#66 A/B-tests dropping `sts:GetServiceBearerToken` from an IAM policy. The reviewer wants to see the preview diff, then have `up` apply *exactly that diff and nothing more*. Two-step `preview` → read → `up` is a mitigation but not a guarantee.

Pulumi's engine supports this natively via **update plans** (`preview --save-plan` / `up --plan`). Both flags are marked experimental, but upstream only *hides* them when `PULUMI_EXPERIMENTAL` is unset; they work without it (verified on v3.265.0 + our `--patch` commits). Setting `PULUMI_EXPERIMENTAL=true` would also enable unrelated experimental engine behavior, so we don't. This spec wires update plans through the reusable workflow.

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
  pulumi preview --patch --non-interactive \
    --save-plan=plan.json 2>&1 | tee pulumi-output.txt
  ;;
```

After the step, write trusted metadata next to the plan, and upload both as one artifact:

```yaml
- name: Prepare plan artifact
  id: plan-meta
  if: inputs.cmd == 'preview' && steps.pulumi.outcome == 'success'
  working-directory: ${{ inputs.working-directory }}
  env:
    PROJECT: ${{ inputs.project }}
    STACK: ${{ inputs.stack }}
  run: |
    jq -n --arg project "$PROJECT" --arg stack "$STACK" \
      --arg sha "$GITHUB_SHA" --arg pulumi_sha "$PULUMI_FORK_SHA" \
      '{project: $project, stack: $stack, sha: $sha, pulumi_sha: $pulumi_sha}' > plan-meta.json
    # Stacks may be fully qualified (`org/project/stack`), and artifact names can't contain `/`
    key=$(printf '%s' "${PROJECT:-default}--$STACK" | sed 's/[^A-Za-z0-9._-]/_/g')
    echo "name=pulumi-plan-$key" >> "$GITHUB_OUTPUT"

- name: Upload plan artifact
  id: plan-artifact
  if: steps.plan-meta.outcome == 'success'
  uses: actions/upload-artifact@v4
  with:
    name: ${{ steps.plan-meta.outputs.name }}
    path: |
      ${{ inputs.working-directory }}/plan.json
      ${{ inputs.working-directory }}/plan-meta.json
    retention-days: 30
    overwrite: true
```

**`plan-meta.json` is the trusted metadata.** Once `up` has verified the artifact came from a preview run of this repo's Pulumi workflow (step 3), its contents are as trustworthy as the plan itself. So all validation (commit SHA, Pulumi version, project/stack) reads from it, whichever way `plan-source` was given, including previews that posted no PR comment. The artifact name is only a lookup key; the raw `project`/`stack` live in the metadata.

**`overwrite: true` is required:** one workflow run can preview the same project+stack more than once (`e2e.yml` does, three times), and `upload-artifact@v4` fails on a duplicate name within a run. The name can't be disambiguated per call, since in a reusable workflow `github.job` is always the callee's job id (`pulumi`). Instead, the marker (below) records the upload's `artifact-id` output, and `up` downloads by id. An overwritten artifact's old id is deleted, so a CAS-`up` against a superseded preview fails loudly.

**Secrets:** the plan file encrypts secret values with the stack's secrets provider (verified: `SerializePlan` takes an `Encrypter`, and plans contain no plaintext secrets). Non-secret inputs are plaintext, a similar exposure to the preview comment itself. Never combine `--save-plan` with `--show-secrets`, which writes secrets in plaintext.

**Why save every preview:** artifacts are cheap (plans are KB–low-MB JSON), and the alternative (opt-in) means you can't retroactively decide to CAS-up a preview you already ran. One extra step in preview, no semantic change to output.

### 2. Comment embeds a plan marker

In the "Summary and PR comment" step, when `cmd=preview`, append a machine-readable HTML comment identifying the artifact:

```html
<!-- pulumi-plan: run_id=<GITHUB_RUN_ID> artifact_id=<steps.plan-artifact.outputs.artifact-id> project=<project> stack=<stack> -->
```

Rendered comments never show this. `up` uses it only to *locate* a plan (resolve `plan-source: pr:<N>` to a run and artifact); `project`/`stack` are there to pick the right comment on multi-project PRs. Nothing in it is trusted for validation; see step 3.

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
  description: 'Skip the commit-SHA and Pulumi-version match checks on the resolved plan (dangerous). Provenance checks always run.'
  required: false
  default: false
  type: boolean
```

Resolution logic (new step before `Run Pulumi`, when `cmd=up` and `plan-source` non-empty). All inputs reach the script via `env`, never `${{ }}` interpolation.

1. Locate `(run_id, artifact_id)`:
   - Numeric → `run_id`; list `gh api repos/{owner}/{repo}/actions/runs/<run_id>/artifacts` and take the one named with this call's sanitized `project`/`stack` key (same `sed` as the preview side)
   - `pr:<N>` → `gh api repos/{owner}/{repo}/issues/<N>/comments` → keep only comments by `github-actions[bot]` that carry a `<!-- pulumi-plan: … -->` marker, filter to matching `project` + `stack`, pick the most recent, extract `run_id` + `artifact_id`. The author filter matters on public repos, where anyone can post a comment containing a forged marker. Comments without a marker (from before this feature) are skipped.
   - `comment:<id>` → fetch that comment (same author check), extract marker
2. Verify provenance. These checks always run; `plan-source-force` does not skip them:
   - `gh api repos/{owner}/{repo}/actions/runs/<run_id>`: the run belongs to this repository, and ran the same caller workflow file as the current run (its `path` matches the current run's)
   - `gh api repos/{owner}/{repo}/actions/artifacts/<artifact_id>`: `workflow_run.id == run_id`, `name` equals the expected sanitized name, and `expired == false`. This ties the artifact to the verified run, so a marker can't pair a trusted run with some other run's artifact.
3. Download by id: `gh api repos/{owner}/{repo}/actions/artifacts/<artifact_id>/zip > plan.zip && unzip plan.zip -d "$WORKING_DIRECTORY"` → gets `plan.json` + `plan-meta.json`. Needs `actions: read`, which the workflow already requests.
4. Validate against `plan-meta.json`:
   - Always: `project` and `stack` equal this call's inputs (exact, unsanitized)
   - Unless `plan-source-force`: `sha == github.sha` and `pulumi_sha == PULUMI_FORK_SHA`

   The `github.sha` comparison is meaningful because callers dispatch `pulumi.yml` via `workflow_dispatch` (e.g. ops), so preview and `up` both run on the branch head. A `pull_request`-triggered preview would run on the merge commit and never match.

In the `up` branch:

```bash
up)
  PLAN_FLAG=""
  if [ -f plan.json ]; then
    PLAN_FLAG="--plan=plan.json"
  fi
  pulumi up --yes --non-interactive $PLAN_FLAG 2>&1 | tee pulumi-output.txt
  ;;
```

If the engine's re-computed plan diverges from `plan.json`, it exits non-zero naming the violating resource, e.g. `violates plan: properties changed: ~~length[{12}!={16}]`. That's the CAS failure, and it surfaces in the PR comment via the existing "Summary and PR comment" step. No extra plumbing needed.

**Never add `--skip-preview` alongside `--plan`.** `up --plan` runs its own preview phase first, and that is where plan violations are caught. In a local test, a drifted `up --plan` failed during that phase with nothing applied, not even the valid, planned replacement of another resource (stack history showed no update). With `--skip-preview`, violations are detected only as steps execute, which can leave a partial apply. Drift that only shows at apply time (e.g. a provider returning different values than it predicted) can still fail mid-apply; that is inherent to the engine.

## Open questions

1. **Plan-file version stability across Pulumi engine versions.** Resolved: `plan-meta.json` records `pulumi_sha` (the `PULUMI_FORK_SHA` env we already have), and `up` refuses mismatches unless `plan-source-force`. Provider versions (`pulumi-aws` etc.) also matter but are harder to pin from the workflow; the checkout SHA covers them if `pyproject.toml` pins are exact.
2. **Provider determinism.** Do our providers emit fully deterministic plans given identical state? `aws.iam.*` (our current use case): almost certainly yes. `aws.s3.*` / `gcp.storage.*` with server-side defaults filled in on refresh: possibly not — worth a smoke test before we recommend CAS-up for those stacks. Not a blocker for shipping the feature.
3. **Multi-project PRs.** A single PR could touch multiple projects (`oa-ci` and `oa-management`) → two plan artifacts, two markers in two separate comments (already how existing preview comments work). `pr:<N>` resolution has to filter on (project, stack) — the marker includes both, and `plan-meta.json` re-checks them. Confirmed unambiguous.
4. **Artifact retention.** GitHub artifacts default to 90 days; I set `retention-days: 30` above since a plan stale by a month is almost certainly wrong to apply. Tunable, but 30d is a safer default. Expired artifact → the provenance check (`expired == false`) fails, `up` fails — feature not bug.
5. **`refresh` before `up`.** If someone runs `refresh` between the `preview` and the CAS-`up`, refresh changes stack state → plan mismatches → CAS fails. That's correct behavior (state changed underneath us), but worth documenting.
6. **First-preview-on-a-PR before `plan-source` was wired.** `pr:<N>` resolution should tolerate old preview comments without a marker (just skip them, keep looking).

## Testing plan

0. Done locally (rebased fork binary, file backend, YAML program with `random` resources): `preview --save-plan` → change a resource input → `up --plan` fails with `violates plan`, nothing applied → revert the change → `up --plan` succeeds.
1. In `e2e.yml` (which already previews one stack three times per run, exercising `overwrite: true`):
   - Dispatch `cmd=preview` → verify `plan.json` artifact appears, marker embedded in comment.
   - Dispatch `cmd=up plan-source=<that run id>` → verify plan is downloaded and applied.
   - Make a config change to that stack out-of-band (in another PR, or console).
   - Dispatch `cmd=up plan-source=<original run id>` again → verify CAS failure surfaces.
2. Verify `plan-source: pr:<N>` picks the *latest* matching preview when the PR has multiple.
3. Multi-project: two projects, two previews, two `up`s each pointing at their own `pr:<N>` → both apply cleanly.
4. `plan-source-force=true` skips the SHA check → confirmed by manually mismatching SHAs.

## BC

- Default behavior unchanged: no `plan-source` → `up` runs as today (no `--plan`, no `PULUMI_EXPERIMENTAL`).
- `preview` gains a `--save-plan` invocation and an artifact upload. With `PULUMI_EXPERIMENTAL` left unset, preview output is unchanged apart from two trailing lines: "Update plan written to 'plan.json'" and a hint to run `pulumi up --plan`.

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
