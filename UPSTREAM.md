# Upstream provenance

Tutou Agent is developed by 兔投科技 and is derived from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent),
which is distributed under the MIT License.

## Imported baseline

- Upstream repository: `https://github.com/NousResearch/hermes-agent.git`
- Upstream branch: `main`
- Imported commit: `ee742fe1bc828f6456659f67d27bdbeacdebbdd4`
- Import commit in this repository: `d12d66708b02de61b9b34654e0fe0a3fd0c3ee38`
- Verification: all 10,630 upstream paths matched the upstream Git blob and
  mode exactly at import time.
- Pre-existing Tutou file retained separately: `github-ssh-test.txt`.

The upstream `LICENSE` file and copyright notice remain unchanged. Tutou Agent
changes and additions are maintained in subsequent commits.

## Compatibility policy

The initial goal is feature parity with the imported Hermes Agent baseline.
Rebranding is incremental and compatibility-first:

- `tutou`, `tutou-agent`, and `tutou-acp` are the new command names.
- `hermes`, `hermes-agent`, and `hermes-acp` remain compatibility aliases.
- Existing Hermes state/configuration paths remain in use until a tested,
  reversible migration is introduced.
- Internal Python module names are not renamed merely for appearance; each
  internal rename must preserve import and plugin compatibility.

## Synchronizing future upstream changes

The local clone uses a read-only `upstream` remote. Future updates should be
reviewed and ported deliberately rather than applied with a destructive reset:

```bash
git fetch upstream main
```

For every upstream synchronization:

1. Record the old and new upstream SHAs.
2. Review the upstream diff for conflicts with Tutou-specific commits.
3. Apply the update on a dedicated branch.
4. Run the canonical Python and JavaScript test suites relevant to the diff.
5. Preserve the upstream MIT attribution and this provenance record.
6. Merge only after the resulting remote commit and CI state are verified.
