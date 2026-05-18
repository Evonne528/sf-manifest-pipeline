# SF Manifest Pipeline Plugin

This package contains a local Codex plugin for Salesforce project leaders working without a centralized shared repository.

The plugin provides one skill, `sf-manifest-pipeline`, and a companion script:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py --help
```

Primary subflows:

1. `once`: one-time bootstrap. Initializes local Git/state, generates a full manifest, splits it into chunks, and retrieves metadata.
2. `snapshot`: recurring snapshot refresh. Generates a history-guided smart manifest and retrieves scoped metadata.
3. `review`: review after refresh. Analyzes Git changes, writes a report, and updates change history.
4. `churn`: occasional churn analysis. Reports frequently changed metadata types and components.
5. `codify`: turns confirmed review findings into project standards.

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py once --org <alias-or-username> --max-members 500
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py snapshot --org <alias-or-username>
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py review
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py churn --lookback-days 120 --top 20
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py codify --rule "Flow changes must document trigger conditions and rollback plan."
```

Low-level commands:

1. `init`: enable local Git when missing and create `.leader-review/`.
2. `full-manifest`: first-use full org manifest generation with chunked package XML output.
3. `retrieve`: retrieve metadata by generated chunk manifests.
4. `analyze`: analyze local metadata changes against `.leader-review/metadata-standards.md` and update history.
5. `smart-manifest`: use prior change history and config to generate a narrower retrieve manifest for future runs.

The project-specific standards file starts empty by design and should be updated from leader feedback over time.
