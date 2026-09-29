---
id: KB-APP-004
title: Add-in / plugin conflict
category: Application Crash
subcause: Add-in / plugin conflict
tags: add-in plugin conflict crm connector save teams excel
---
# KB-APP-004 - Add-in / plugin conflict

## Symptoms
Crash when saving or when a specific integration (CRM connector, PDF add-in) runs.

## Telemetry signature
Crashes correlated to a specific action (save, send) rather than time; normal hang counts otherwise.

## Diagnosis steps
1. List COM add-ins and their load times (File > Options > Add-ins).
2. Disable non-essential add-ins and retest the failing action.
3. Check the CRM connector version against the supported matrix.

## Remediation
1. Disable or remove the conflicting add-in centrally via policy.
2. Update the CRM connector to the supported version.
3. Re-enable required add-ins one at a time to confirm the culprit.

## Expected outcome
Resolves save-time crashes without a full reinstall; typically first-contact resolution.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
