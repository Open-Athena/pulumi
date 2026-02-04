# Pulumi Preview: Patch-Style Output Format

## Problem

`pulumi preview --diff` outputs a custom format that's not compatible with standard diff/patch tools or GitHub's diff syntax highlighting:

```
    ~ aws:cloudwatch/logGroup:LogGroup: (update)
      ~ retentionInDays: 0 => 90
      + tags           : {
          + ManagedBy: "Pulumi"
        }
    + aws:iam/role:Role: (create)
        name: "github-actions-role-2"
```

This makes it difficult to:
1. Get proper syntax highlighting in GitHub PR comments/issues
2. Use standard diff tools (`patch`, `delta`, `diff-so-fancy`)
3. Integrate with CI systems that expect unified diff format

**Critical issue**: GitHub's diff syntax highlighting requires `+`/`-` markers at **column 0** (line start). Pulumi's current output has markers after indentation, so no highlighting occurs.

## Proposed Solution

Add a `--patch` flag to `pulumi preview` that outputs GitHub-compatible diff format:

```bash
pulumi preview --patch
```

### Output Format Requirements

**CRITICAL**: Markers MUST be at column 0 (start of line), not after indentation.

- `+` at column 0 for additions (resources being created, properties being added)
- `-` at column 0 for deletions (resources being deleted, properties being removed)
- ` ` (space) at column 0 for context lines
- Value changes (`old => new`) expanded to `-`/`+` line pairs
- Original indentation preserved AFTER the marker

Example - WRONG (current behavior, markers after indent):
```
    ~ aws:cloudwatch/logGroup:LogGroup: (update)
        - retentionInDays: 0
        + retentionInDays: 90
```

Example - CORRECT (markers at column 0):
```diff
~     aws:cloudwatch/logGroup:LogGroup: (update)
-         retentionInDays: 0
+         retentionInDays: 90
```

### Key Behaviors

1. **Markers at column 0**: All `+`/`-`/`~`/` ` markers must be the first character of the line
2. **Value changes**: Lines with ` => ` should be expanded to two lines:
   - `retentionInDays: 0 => 90` becomes:
     ```diff
     -         retentionInDays: 0
     +         retentionInDays: 90
     ```
3. **Provider version changes**: `[provider: old => new]` lines should also be expanded:
   - `[provider=pulumi:providers:aws 6.65.0 => 6.66.0]` becomes:
     ```diff
     -         [provider=pulumi:providers:aws 6.65.0]
     +         [provider=pulumi:providers:aws 6.66.0]
     ```
4. **Block propagation**: When a resource is created (`+`) or deleted (`-`), all nested properties inherit that marker
5. **Updates (`~`)**: Resource-level updates use `~` marker; property-level changes within use `+`/`-`
6. **Context lines**: Unchanged content uses ` ` (space) at column 0
7. **ANSI colors**: When combined with `--color always`, output ANSI-colored diff (green/red/yellow)

## Test Cases

### Test Case 1: Resource Update with Property Changes

**Input** (current `--diff` output):
```
Previewing update (dev)

View in Browser (Conditions API): https://app.pulumi.com/...

     Type                             Name                                  Plan       Info
     pulumi:pulumi:Stack              oa-ci-dev
 ~   └─ aws:cloudwatch:LogGroup       github-runners                        update     [diff: ~retentionInDays]

Resources:
    ~ 1 to update
    9 unchanged

---outputs:---
...

Resources:
    ~ 1 to update
    9 unchanged

Do you want to perform this update?
  yes
> no
  details
```

**Expected output** (`--patch`):
```diff
  Previewing update (dev)

  View in Browser (Conditions API): https://app.pulumi.com/...

       Type                             Name                                  Plan       Info
       pulumi:pulumi:Stack              oa-ci-dev
~      └─ aws:cloudwatch:LogGroup       github-runners                        update     [diff: ~retentionInDays]

  Resources:
      ~ 1 to update
      9 unchanged
```

### Test Case 2: Property Value Change with `=>`

**Input** (from detailed diff view):
```
    ~ aws:cloudwatch/logGroup:LogGroup: (update)
        [id=/aws/ec2/github-runners]
        [urn=urn:pulumi:dev::oa-ci::aws:cloudwatch/logGroup:LogGroup::github-runners]
        [provider=pulumi:providers:aws::default_6_66_0::a1b2c3d4]
      ~ retentionInDays: 0 => 90
```

**Expected output** (`--patch`):
```diff
~     aws:cloudwatch/logGroup:LogGroup: (update)
          [id=/aws/ec2/github-runners]
          [urn=urn:pulumi:dev::oa-ci::aws:cloudwatch/logGroup:LogGroup::github-runners]
          [provider=pulumi:providers:aws::default_6_66_0::a1b2c3d4]
-         retentionInDays: 0
+         retentionInDays: 90
```

### Test Case 3: Provider Version Change

**Input**:
```
    ~ aws:iam/role:Role: (update)
        [id=github-actions-role-0]
        [urn=urn:pulumi:dev::oa-ci::aws:iam/role:Role::github-actions-role-0]
        [provider: pulumi:providers:aws 6.65.0 => 6.66.0]
```

**Expected output** (`--patch`):
```diff
~     aws:iam/role:Role: (update)
          [id=github-actions-role-0]
          [urn=urn:pulumi:dev::oa-ci::aws:iam/role:Role::github-actions-role-0]
-         [provider: pulumi:providers:aws 6.65.0]
+         [provider: pulumi:providers:aws 6.66.0]
```

### Test Case 4: New Resource Creation

**Input**:
```
    + aws:iam/role:Role: (create)
        name: "github-actions-role-2"
        assumeRolePolicy: "{...}"
```

**Expected output** (`--patch`):
```diff
+     aws:iam/role:Role: (create)
+         name: "github-actions-role-2"
+         assumeRolePolicy: "{...}"
```

### Test Case 5: Resource Deletion

**Input**:
```
    - aws:iam/role:OldRole: (delete)
        [id=old-role-id]
        name: "old-role"
```

**Expected output** (`--patch`):
```diff
-     aws:iam/role:OldRole: (delete)
-         [id=old-role-id]
-         name: "old-role"
```

### Test Case 6: Mixed Changes

**Input**:
```
Previewing update (dev)

     Type                             Name                Plan       Info
     pulumi:pulumi:Stack              oa-ci-dev
 +   ├─ aws:iam:Role                  new-role            create
 ~   ├─ aws:cloudwatch:LogGroup       github-runners      update     [diff: ~retentionInDays]
 -   └─ aws:iam:Role                  old-role            delete

---outputs:---
...
```

**Expected output** (`--patch`):
```diff
  Previewing update (dev)

       Type                             Name                Plan       Info
       pulumi:pulumi:Stack              oa-ci-dev
+      ├─ aws:iam:Role                  new-role            create
~      ├─ aws:cloudwatch:LogGroup       github-runners      update     [diff: ~retentionInDays]
-      └─ aws:iam:Role                  old-role            delete

  ---outputs:---
  ...
```

## Use Case: GitHub Actions PR Comments

With native `--patch` support:
```yaml
- name: Run Pulumi preview
  run: |
    pulumi preview --patch --non-interactive 2>&1 | tee pulumi-output.txt

- name: Comment on PR
  run: |
    gh pr comment --body "$(cat <<'EOF'
    ## Pulumi Preview

    \`\`\`diff
    $(cat pulumi-output.txt)
    \`\`\`
    EOF
    )"
```

## Implementation Notes

The diff output is generated in:
- `pkg/backend/display/` - display/rendering logic
- `pkg/backend/display/object_diff.go` - object/property diff formatting

Key areas to modify:
1. Add `--patch` flag to preview command (`pkg/cmd/pulumi/operations/preview.go`)
2. Modify diff rendering to output markers at column 0 (`pkg/backend/display/object_diff.go`)
3. Expand `=>` patterns to `-`/`+` line pairs

### Column 0 Transformation

The core transformation is:
```
BEFORE: "    + property: value"     (marker after indent)
AFTER:  "+     property: value"     (marker at column 0, indent preserved after)
```

This can be done by:
1. Detecting lines with leading whitespace followed by `+`/`-`/`~`
2. Extracting: (indent, marker, rest)
3. Outputting: marker + indent + rest

## Alternatives Considered

1. **Post-processing scripts** - fragile, doesn't handle all edge cases, requires maintenance
2. **JSON output + external tool** - `--json` exists but requires separate formatting tool
3. **ANSI-to-HTML conversion** - preserves colors but not widely supported in markdown

## References

- [GitHub diff syntax highlighting]
- [Unified diff format]

[GitHub diff syntax highlighting]: https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-and-highlighting-code-blocks#syntax-highlighting
[Unified diff format]: https://en.wikipedia.org/wiki/Diff#Unified_format
