---
id: KB-APP-002
title: Memory leak / resource exhaustion
category: Application Crash
subcause: Memory leak / resource exhaustion
tags: memory leak freeze sheets lags resource exhaustion ram
---
# KB-APP-002 - Memory leak / resource exhaustion

## Symptoms
Application freezes when larger workloads are opened (many sheets, long meetings); gets worse over the day.

## Telemetry signature
Rising app_hang_count trend (+2 or more over 4 weeks); freezes reported rather than hard crashes.

## Diagnosis steps
1. Review hang trend; a steady climb suggests a leak rather than a corrupt install.
2. Capture working-set memory of the process over a session (Performance Monitor).
3. Check add-ins loaded into the process (see KB-APP-004).

## Remediation
1. Apply the vendor memory hotfix / latest channel build.
2. Set add-in memory caps and disable hardware graphics acceleration if implicated.
3. Deploy a nightly restart / session recycle policy for affected users.
4. Consider a RAM upgrade for devices under 16 GB running heavy analytics.

## Expected outcome
Hang counts typically return below the warn threshold within one week when a leak hotfix is applied.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
