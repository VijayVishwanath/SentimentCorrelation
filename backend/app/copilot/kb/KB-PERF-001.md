---
id: KB-PERF-001
title: Startup bloat / boot degradation
category: Performance
subcause: Startup bloat / boot degradation
tags: boot slow start up startup lags reimage ssd optimization
---
# KB-PERF-001 - Startup bloat / boot degradation

## Symptoms
Laptop takes forever to start; everything lags for the first minutes after turning on.

## Telemetry signature
boot_duration_sec above 55s (warn) or 85s (critical), typically trending upward over several weeks.

## Diagnosis steps
1. Check the boot-time trend; a steady rise indicates accumulated startup load.
2. Review startup apps and services (Task Manager > Startup).
3. Check disk health (KB-PERF-002) to rule out a failing SSD.

## Remediation
1. Remove non-essential startup items via policy.
2. If boot remains above the warn threshold, reimage the device (fresh OS + SSD optimization).
3. Restore the user profile and validate boot time under 40s.

## Expected outcome
Across 13 historical boot remediations, repeat contacts fell to ~0% and ticket rate dropped sharply after reimage.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
