# SF Manifest Pipeline Plugin

This package contains a local Codex plugin for Salesforce project leaders working without a centralized shared repository.

The plugin provides one skill, `sf-manifest-pipeline`, and a companion script:

```bash
python3 plugins/sf-manifest-pipeline/scripts/sf_manifest_pipeline.py --help
```

Core workflow:

1. `init`: enable local Git when missing and create `.leader-review/`.
2. `full-manifest`: first-use full org manifest generation with chunked package XML output.
3. `retrieve`: retrieve metadata by generated chunk manifests.
4. `analyze`: analyze local metadata changes against `.leader-review/metadata-standards.md` and update history.
5. `smart-manifest`: use prior change history and config to generate a narrower retrieve manifest for future runs.

The project-specific standards file starts empty by design and should be updated from leader feedback over time.
