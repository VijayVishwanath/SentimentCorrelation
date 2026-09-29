---
id: KB-GEN-001
title: Outcome-based ticket closure policy
category: General
subcause: Outcome verification
tags: outcome closure verification dex score repeat contact recovery
---
# KB-GEN-001 - Outcome-based ticket closure policy

## Symptoms
Guidance for closing tickets on verified recovery, not on silence.

## Telemetry signature
Post-fix telemetry back below the warn threshold and no repeat contact within the verification window.

## Diagnosis steps
1. After remediation, keep the ticket in 'Monitoring' for 7 days.
2. Check the device's primary telemetry signal in DEX Sentinel.
3. Confirm no repeat contact of the same category.

## Remediation
1. Close as 'Resolved - verified' only when telemetry has recovered.
2. If the signal is still breached, reopen and escalate to the next sub-cause.
3. Record the before/after DEX Score for outcome reporting.

## Expected outcome
Moves reporting from ticket-closure SLAs to measured experience recovery.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
