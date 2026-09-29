---
id: KB-PERF-003
title: Aging hardware (end of refresh cycle)
category: Performance
subcause: Aging hardware (end of refresh cycle)
tags: aging old device refresh lifecycle age
---
# KB-PERF-003 - Aging hardware (end of refresh cycle)

## Symptoms
Persistent slowness on devices 36+ months old despite software fixes.

## Telemetry signature
age_months 36+ with borderline boot, battery and disk health.

## Diagnosis steps
1. Confirm the device against the refresh schedule.
2. Check whether a previous reimage only gave temporary relief.

## Remediation
1. Prioritise the device in the next refresh wave.
2. As an interim step apply the KB-PERF-001 startup clean-up.

## Expected outcome
Refreshing chronic-problem devices first gives the largest experience recovery per dollar.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
