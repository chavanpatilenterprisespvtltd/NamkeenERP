# Release Genealogy

The ERP was developed cumulatively from early prototypes through V90. The canonical Candidate 1.0 source is based on the latest cumulative V90.gw tree.

## Version families represented

- Early foundation: V2–V16
- Mobile/domain/operational growth: V17–V40
- Accounting/GST/dispatch/compliance/production depth: V41–V60
- Production/UAT/deployment/master-data hardening: V61–V90
- Lettered V90 sequence: V90.a through V90.gw (+ hotfix1–5), then V90.gx (Session CS2: security/deployment fixes, company X/Y, GST invoicing, X→Y settlement, plant registers, entry screens), with historical release notes and verification artifacts retained in this repository.

The Library inventory also contains the individual historical ZIP releases. The supplied Library snapshot shows the latest V90.gw release at the top and the historical releases down through the earliest prototypes; the inventory spans the ERP genealogy rather than representing separate competing current systems.

## Canonical source rule

`app/`, `migrations/`, `web/`, `android/`, `tests/`, `scripts/`, configuration and deployment assets in this candidate are the single current source tree. Do not merge an older ZIP over this tree because an older release contains a file that appears missing; first inspect the release genealogy and migration manifest.

## Troubleshooting rule

For a defect:

1. reproduce against the current candidate;
2. identify the current module/API/UI;
3. identify the earliest release note/checksum evidence relevant to the component;
4. identify the migration that introduced the behavior when applicable;
5. fix forward with a new controlled change;
6. never rewrite historical migrations.
