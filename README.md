# Pulumi Reusable Workflow

A GitHub Actions reusable workflow for running Pulumi with nice PR comments and diff highlighting.

## Features

- **Diff highlighting**: Uses `--patch` flag for GitHub-compatible diff output (markers at column 0)
- **PR comments**: Automatically posts Pulumi output as collapsible PR comments with deep links
- **Caching**: Caches the Pulumi binary build across runs
- **Flexible auth**: Supports GCP (for Pulumi backend) and AWS (for resources)

## Usage

```yaml
name: Infrastructure

on:
  workflow_dispatch:
    inputs:
      cmd:
        description: 'Pulumi command'
        required: true
        default: 'preview'
        type: choice
        options: [preview, up, refresh]
      stack:
        description: 'Pulumi stack'
        required: true
        default: 'dev'

permissions:
  id-token: write
  contents: read
  pull-requests: write
  actions: read

jobs:
  pulumi:
    uses: Open-Athena/pulumi/.github/workflows/pulumi.yml@v1
    with:
      cmd: ${{ inputs.cmd }}
      stack: ${{ inputs.stack }}
      working-directory: infra  # optional, defaults to repo root
    secrets: inherit
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `cmd` | Yes | - | Pulumi command: `preview`, `up`, `refresh`, `destroy`, `init` (`pulumi stack init`), or `stack-rm` (`pulumi stack rm --force`) |
| `stack` | Yes | - | Pulumi stack name |
| `project` | No | - | Project name, shown in job summaries and PR comments |
| `working-directory` | No | `.` | Directory containing Pulumi project |
| `deps-directory` | No | `working-directory` | Directory containing `pyproject.toml` or `requirements.txt` |
| `deps-extras` | No | - | Comma-separated `pyproject.toml` extras to install (e.g. `gha,dev`) |
| `python-version` | No | `3.11` | Python version |
| `aws-region` | No | `us-east-1` | AWS region |
| `aws-role` | No | - | AWS role ARN (overrides `PULUMI_AWS_ROLE` var) |
| `comment-on-pr` | No | `true` | Post output as PR comment |
| `pulumi-sha` | No | (pinned fork commit) | Commit of the [Pulumi fork] to build |
| `secrets-provider` | No | - | Secrets provider for `init` (e.g. `gcpkms://projects/.../cryptoKeys/...`) |
| `expect-no-changes` | No | `false` | For `preview`: fail if any changes are proposed |

## Required Variables

Set these as repository or organization variables:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: GCP Workload Identity provider (if using GCS backend)
- `GCP_SERVICE_ACCOUNT`: GCP service account (if using GCS backend)
- `PULUMI_AWS_ROLE`: AWS role ARN for Pulumi to assume

## Secrets

- `PULUMI_ACCESS_TOKEN`: Pulumi Cloud access token (if using Pulumi Cloud backend)
- `PULUMI_CONFIG_PASSPHRASE`: passphrase for stack encryption (if using the passphrase secrets provider; unset means an empty passphrase)

## About

This workflow uses a [Pulumi fork](https://github.com/Open-Athena/pulumi) that adds a `--patch` flag
for unified diff format output. This enables proper syntax highlighting in GitHub PR comments.

See [patch-output-spec.md](./patch-output-spec.md) for the spec.

[Pulumi fork]: https://github.com/Open-Athena/pulumi
