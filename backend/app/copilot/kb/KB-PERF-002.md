---
id: KB-PERF-002
title: Disk degradation
category: Performance
subcause: Disk degradation
tags: disk ssd smart degradation slow storage
---
# KB-PERF-002 - Disk degradation

## Symptoms
General sluggishness, slow file opens, long boot; may precede hardware failure.

## Telemetry signature
disk_health_pct below 70 (warn) or 55 (critical).

## Diagnosis steps
1. Run manufacturer SSD diagnostics and read SMART attributes.
2. Confirm free space above 15%.

## Remediation
1. Back up user data.
2. Replace the SSD if SMART reports reallocated or pending sectors.
3. Reimage onto the new disk and validate boot time.

## Expected outcome
Replacing a degraded disk restores boot and app-launch times and pre-empts data loss.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
