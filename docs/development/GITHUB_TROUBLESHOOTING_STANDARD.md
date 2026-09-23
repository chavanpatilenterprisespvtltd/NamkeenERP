# Namkeen ERP — GitHub Fast-Troubleshooting Standard

This document operationalizes the self-documenting code-file convention used by the ERP.

## Goal

A developer should be able to open a single changed file in GitHub and understand **where it belongs, which version changed it, what was wrong, how it was confirmed, why it happened, what was changed, and what was not changed** without searching through a separate changelog first.

## Required file order

Every new or modified code file must follow this order:

1. FILE PATH — first line.
2. Current component version header.
3. Current session changelog entry.
4. Preserved older version entries, newest-to-oldest.
5. Imports/declarations and implementation.
6. Short inline `[Session N]` pointers at changed logic.

## Required delivery order

When ChatGPT or a developer supplies a code fix:

1. State the complete destination path immediately before the code.
2. Provide the entire file.
3. Never provide only a patch/diff/snippet as the primary delivery.
4. State verification status separately from the code.
5. Never claim live evidence that was not actually obtained.

## Why this is retained in the ERP

The project has a long cumulative release history. Keeping the troubleshooting context inside the file reduces the chance of losing the reason for a fix when files are moved, copied into GitHub, or revisited months later.

GitHub remains useful for repository history and review; this convention is an additional self-contained evidence trail inside the source itself.

## Historical-source rule

The Library and consolidated release genealogy remain the source/history for the cumulative ERP. A newer source package does not justify deleting historical context or assuming an older file was irrelevant. When resolving a conflict, inspect the latest verified source and the retained historical record before deciding what to remove or replace.

## No silent history loss

Do not:

- delete an older in-file changelog entry;
- replace a complete file with a fragment;
- remove a migration because a later migration exists;
- rename a component without recording the reason;
- call an unrun test "verified";
- hide a pre-existing failure to make a release appear green.
