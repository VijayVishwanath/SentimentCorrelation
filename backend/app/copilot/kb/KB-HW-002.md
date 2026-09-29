---
id: KB-HW-002
title: Disk failure risk
category: Hardware
subcause: Disk failure risk
tags: disk failure smart replace backup
---
# KB-HW-002 - Disk failure risk

## Symptoms
Device is slow, with occasional freezes or file errors.

## Telemetry signature
disk_health_pct below 70 (warn) or 55 (critical).

## Diagnosis steps
1. Read SMART data and run vendor diagnostics.
2. Ensure OneDrive / backup is current.

## Remediation
1. Replace the disk and restore user data.
2. Re-run diagnostics to confirm.

## Expected outcome
Prevents data loss and an unplanned outage for the employee.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
