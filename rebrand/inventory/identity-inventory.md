# Identity Inventory Summary

- Source branch SHA at scan time: `703869ebaa299a3c77817b20c5f57bbfa433f365`
- Identity occurrences: **91,743**
- Legacy-identity path-component occurrences: **1,484**
- Hermes/NousResearch URL occurrences: **1,854**
- Total deterministic records: **95,081**

The complete generated JSON is intentionally not committed because it is
17,893,274 bytes and is reproducible from tracked source. Its verified backup
is:

`/home/tutou/backups/tutou-agent/20260829_153810-pre-total-rebrand/inventory-full/identity-inventory-703869e.json`

SHA-256:

`961fc591fd9254ede196396c04bc646f04969656a4367fa55a11b23ebb5cb5fc`

Regenerate from the repository root:

```bash
python3 scripts/rebrand/inventory.py \
  --root . \
  --output /tmp/tutou-agent-identity-inventory.json
```

The curated, commit-sized inventories are:

- `url-authorities.json` — URL authority classification and replacements.
- `path-renames.json` — tracked path rename/regeneration classification.
- `identity-map.yaml` — canonical replacement contract.
- `allowed-legacy-identities.yaml` — strict legal/provenance/model/migration exceptions.
