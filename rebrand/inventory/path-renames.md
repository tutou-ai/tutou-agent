# Tracked Path Rename Inventory

- Tracked paths scanned: **10656**
- Total legacy-identity paths: **1468**
- Rename required: **1436**
- Regenerate/review required: **15**
- Preserved historical fixtures: **17**
- Proposed-path collisions: **0**

## Policy

- Rename text/code paths with `git mv` in dependency-ordered batches.
- Regenerate branded binary/model assets; filename-only relabeling is forbidden.
- Preserve contributor email fixtures as historical data.
- Resolve every collision before mutation.
