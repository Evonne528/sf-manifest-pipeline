---
name: sf-manifest-pipeline
description: Use when a tech leader needs to initialize a local Salesforce metadata review workspace, generate full or history-guided manifests, retrieve org metadata, analyze changes against project-specific standards, and maintain metadata change-frequency history for teams without a central repository.
---

# SF Manifest Pipeline

## Purpose

Use this skill for multi-person Salesforce projects where developers exchange code outside a centralized repository and the leader needs a local, reviewable snapshot of project-relevant metadata.

The workflow assumes the user has a local project folder. If it is not under Git, initialize Git before retrieving or analyzing metadata. Keep all plugin state under `.leader-review/` so it can travel with the local project when desired.

## Required Local Files

- `.leader-review/metadata-standards.md`: project-specific code and metadata standards. Create it if missing. Its initial content may be empty; update it only when the user gives standards, review feedback, or recurring risk rules.
- `.leader-review/config.json`: retrieve and analysis configuration.
- `.leader-review/history/metadata-change-history.jsonl`: append-only change history.
- `.leader-review/manifests/`: generated full and scoped package manifests.
- `.leader-review/reports/`: review reports.

## Subflows

Prefer these subflows when the user describes a leader workflow in natural language.

1. One-time bootstrap:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py once --org <alias-or-username> --max-members 500
```

Use this only for initial setup. It initializes local Git/state, generates a full org manifest, splits it into chunks, and retrieves each chunk unless `--skip-retrieve` is passed.

2. Refresh snapshot:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py snapshot --org <alias-or-username>
```

Use this for normal recurring refreshes. It generates a history-guided smart manifest and retrieves only that scoped snapshot.

3. Review after refresh:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py review
```

Use this after `snapshot`. It analyzes current Git changes, writes a review report, and appends change records to history.

4. Occasional churn analysis:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py churn --lookback-days 120 --top 20
```

Use this when the leader wants to know which metadata changes frequently.

5. Codify findings as standards:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py codify --rule "Flow changes must document trigger conditions and rollback plan."
```

Use this when the user confirms a review finding should become a project-specific standard.

## Low-Level Commands

1. Initialize the workspace:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py init
```

This ensures Git exists and creates the local leader-review state files.

2. First use: generate a full org manifest, then split it into chunks:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py full-manifest --org <alias-or-username> --max-members 500
```

The script uses `sf project generate manifest --from-org` and splits the resulting manifest into chunk files to keep each retrieve manageable.

3. Retrieve metadata by chunk:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py retrieve --org <alias-or-username>
```

4. Analyze local metadata changes and update history:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py analyze
```

The report must mention project-standard matches, changed metadata by type, frequently changed components, and risk prompts for leader review.

5. Subsequent use: generate a history-guided manifest:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py smart-manifest --org <alias-or-username>
```

This uses prior history and config to choose metadata types/components that are likely relevant to the project. Stable, never-changed, and explicitly ignored metadata should not be retrieved unless the user asks for a full refresh.

## Agent Behavior

- Treat first use and subsequent use differently. First use needs broad discovery and chunked retrieve. Later use should favor history-guided precision.
- Do not overwrite `.leader-review/metadata-standards.md` if it exists.
- When the user provides feedback such as "以后这种算高风险" or "这个对象不用再拉", update `.leader-review/config.json` or `.leader-review/metadata-standards.md` accordingly.
- Before analysis, inspect `git status` and `git diff` instead of relying only on timestamps.
- When reporting findings, prioritize business and maintainability risks: trigger/flow coupling, permission changes, object model changes, destructive or deleted metadata, hardcoded values, test coverage gaps, and divergence from `metadata-standards.md`.
- Preserve unrelated local changes. Never reset or discard user changes.

## Script Reference

The bundled script is intentionally transparent and local-only:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py --help
```
