---
id: KB-AUTH-001
title: Compliance policy drift
category: Login/Auth
subcause: Compliance policy drift
tags: compliant compliance policy intune re-enroll login blocked
---
# KB-AUTH-001 - Compliance policy drift

## Symptoms
Cannot log in - the device is reported as not compliant.

## Telemetry signature
policy_compliant = false; Login/Auth tickets occur in ~28% of non-compliant device-weeks vs ~0% of compliant ones.

## Diagnosis steps
1. Open the device compliance report and identify the failing setting (encryption, OS version, AV).
2. Check the last successful MDM check-in.

## Remediation
1. Push the compliance policy update and trigger a sync.
2. If sync fails, re-enroll the device in MDM.
3. Confirm compliant state and a successful sign-in.

## Expected outcome
Across 9 historical policy remediations, repeat contacts fell to ~0% once compliance was restored.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
