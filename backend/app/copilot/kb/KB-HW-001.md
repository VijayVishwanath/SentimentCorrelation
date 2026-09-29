---
id: KB-HW-001
title: Battery degradation
category: Hardware
subcause: Battery degradation
tags: battery drains charge charging degradation
---
# KB-HW-001 - Battery degradation

## Symptoms
Battery drains within an hour or does not charge properly.

## Telemetry signature
battery_health_pct below 60 (warn) or 45 (critical); hardware health trending down.

## Diagnosis steps
1. Run the battery report (powercfg /batteryreport).
2. Compare design vs. full-charge capacity.

## Remediation
1. Replace the battery.
2. Update BIOS / firmware power management.
3. Validate battery health above 80%.

## Expected outcome
Across 5 historical hardware remediations, ticket rate fell and repeat contacts dropped to ~0%.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
