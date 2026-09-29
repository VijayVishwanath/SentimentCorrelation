---
id: KB-PERF-004
title: Post-login policy / script processing
category: Performance
subcause: Post-login policy / script processing
tags: after login freezes minutes gpo intune script policy
---
# KB-PERF-004 - Post-login policy / script processing

## Symptoms
Computer freezes for minutes right after login, then recovers.

## Telemetry signature
Normal boot time but slow post-login; may coincide with policy changes or non-compliance.

## Diagnosis steps
1. Review login script and policy processing time (gpresult / Intune diagnostics).
2. Check for large synchronous scripts or mapped drives.

## Remediation
1. Convert synchronous login scripts to asynchronous.
2. Stagger update / scan tasks away from login.
3. Re-sync compliance policy if the device is drifting.

## Expected outcome
Removes the first-10-minutes lag without a hardware change.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
