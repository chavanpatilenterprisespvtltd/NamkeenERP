# Namkeen ERP — Code Change Documentation Standard

**Status:** Mandatory for all new and modified ERP code files
**Purpose:** Make every code file self-explanatory and fast to troubleshoot directly in GitHub, without depending on a separate changelog or `git blame`.

## 1. File path — first line, always

The first line of every new or modified code file must identify its complete repository destination path.

Use the comment syntax native to that language. Examples:

```javascript
// FILE PATH: backend/src/agents/currentAffairsAgent.js
```

```python
# FILE PATH: app/v90gw_completion_audit.py
```

```sql
-- FILE PATH: migrations/273_v90gw_completion_audit.sql
```

```html
<!-- FILE PATH: web/v90gw_completion_audit.html -->
```

The rule is about the **first line and full path**; the comment marker changes with the file language.

## 2. Version header — immediately after the file path

Immediately after the path line, add:

`<Component name> v<major>.<minor> (Session <N> — <one-line summary of this version's change>)`

Example:

```javascript
// FILE PATH: backend/src/agents/currentAffairsAgent.js
// ─── Current Affairs Agent v1.7 (Session 93 — 8 of 10 category queries returning zero results, fixed) ─
```

The component version is local to the file/component. Do not invent a new ERP release merely to bump a file version.

## 3. Detailed changelog for the current version — before code

Every new version entry must be placed before the implementation and must contain this internal shape:

```text
[Session N] FIX/FEATURE — ALL-CAPS ONE-LINE HEADLINE OF WHAT WAS WRONG/ADDED.
Confirmed live this session via <exact method: direct DB query, raw HTTP fetch,
live diagnostic script, etc.> — <specific evidence found>.

ROOT CAUSE (if a fix): <why it was actually happening — the underlying mechanism>.

THE FIX: <what changed, scoped precisely — function/mechanism and affected
lines/section where practical, plus what was explicitly NOT touched>.
<Follow-up verification step for next time, when applicable>.
```

### Mandatory evidence habit

Do not write only "fixed" or "tested." State **how** it was confirmed and what the evidence showed.

Good:

> Confirmed live this session via a direct database query against the staging PostgreSQL instance — the expected row existed with status `READY` and the API returned HTTP 200.

Not sufficient:

> Confirmed working.

If live confirmation was not possible, say so explicitly and state the check that actually was performed. Never claim a live DB/API/device/deployment check that was not run.

## 4. State the blast radius

Every fix entry must identify what was changed and what was explicitly unaffected.

Example:

> THE FIX: Updated `calculate_availability()` to use the completed downtime interval; the OEE schema, stock ledger, production posting, and maintenance workflow were not changed.

This prevents future troubleshooting from reopening unrelated areas.

## 5. Preserve all older versions inside the same file

Never delete an older version's changelog from a file being modified.

Keep the complete history in the same file, with the newest entry at the top and older entries below it. Older entries must remain intact.

Example:

```javascript
// ─── Current Affairs Agent v1.7 ... ─────────────────────────────────────
// [Session 93] FIX ...
// ...full current entry...

// ─── v1.6 HEADER (preserved) ─────────────────────────────────────────────
// [Session 91] FIX — ...full old entry, untouched...
```

The file itself must therefore remain useful even when viewed outside GitHub history.

## 6. Inline comments at changed code

Near the actual changed implementation, add a short pointer to the session/header:

```javascript
// [Session 93] FIX — see file header. The category queries now each contain a real anchor term.
const CATEGORY_QUERIES = [ ... ];
```

Keep inline comments short. The full explanation belongs in the header changelog.

## 7. Delivery rule — complete file only

For every code fix, delivery must be a **complete file**, never a diff, patch, or isolated snippet.

Before the code block, prominently state the exact destination path:

`FILE PATH: app/v90gw_completion_audit.py`

Then provide the complete ready-to-paste/overwrite file.

This is the default delivery format even for a one-line change.

## 8. Do not rewrite historical files only to retrofit this standard

The consolidated Production Candidate preserves historical source and release records. Existing historical files do not need to be rewritten solely to add these headers.

When a historical file is actually modified for a real bug fix or feature, bring that file into this standard as part of that modification and preserve its existing history.

## 9. Session numbering

Use the actual project/session number supplied by the ongoing work. Do not fabricate a session number. If the session number is not known, explicitly identify that limitation before delivery rather than silently inventing one.

## 10. Verification language

Every delivery must distinguish:

- **RUN / VERIFIED:** the check was actually executed and evidence was observed.
- **NOT RUN:** the environment did not permit the check.
- **BLOCKED:** an external dependency, credential, service, device, or connection prevented the check.
- **FAILED:** the check ran and failed.
- **PRE-EXISTING FAILURE:** the failure was reproduced or already documented and is not attributable to the current change.

Never convert NOT RUN, BLOCKED, or FAILED into PASS by inference.

## 11. GitHub troubleshooting workflow

GitHub's web editor supports direct file editing and committing, and `github.dev` provides a browser-based editor with source control. This standard is designed so a developer can open one file and immediately see its path, current component version, exact session evidence, root cause, fix, and preserved prior history.

For a changed file, the preferred troubleshooting order is:

1. Open the file in GitHub.
2. Read the first-line path and current version header.
3. Read the newest changelog entry.
4. Check the stated live evidence and root cause.
5. Read the inline `[Session N]` pointer at the changed implementation.
6. Review older in-file history before changing the file again.
7. Make the next change as a complete-file update using this same convention.

## 12. ERP-wide rule

This standard applies to backend Python, migrations/SQL, web JavaScript/HTML/CSS where comments are supported, Android/mobile source, scripts, configuration-as-code, and future ERP code components where a comment header is syntactically valid.

For formats that do not permit comments, preserve the same metadata in the format's supported metadata/documentation location and do not break the file's syntax merely to force a comment.
