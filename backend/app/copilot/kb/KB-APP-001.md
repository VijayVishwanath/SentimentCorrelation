---
id: KB-APP-001
title: Application crash / hang loop
category: Application Crash
subcause: Application crash / hang loop
tags: outlook excel teams crm crash hang reinstall patch
---
# KB-APP-001 - Application crash / hang loop

## Symptoms
Employee reports an application (Outlook, Excel, Teams, CRM) crashing or hanging repeatedly.

## Telemetry signature
app_hang_count above 3/week (warn) or 6/week (critical); crash-category tickets on the same device-week.

## Diagnosis steps
1. Confirm the hang count trend over the last 4 weeks in DEX Sentinel.
2. Collect the application event log (Event ID 1000/1002) for the faulting module.
3. Check the installed build against the current approved release.

## Remediation
1. Uninstall the affected application suite via software center.
2. Clear the local application cache (%LOCALAPPDATA%\Microsoft\Office\16.0).
3. Reinstall the latest approved build and apply cumulative patches.
4. Restart and monitor hang count for 7 days.

## Expected outcome
Across 8 historical Application Crash remediations, repeat contacts fell by 100% and ticket rate by ~64%.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
