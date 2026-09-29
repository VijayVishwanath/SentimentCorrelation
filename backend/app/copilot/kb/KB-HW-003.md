---
id: KB-HW-003
title: Thermal / fan failure
category: Hardware
subcause: Thermal / fan failure
tags: overheating fan loud noise thermal
---
# KB-HW-003 - Thermal / fan failure

## Symptoms
Laptop is overheating and the fan is very loud.

## Telemetry signature
Hardware health trending down; thermal events in vendor telemetry.

## Diagnosis steps
1. Check thermal logs and fan RPM via the vendor tool.
2. Inspect vents for dust.

## Remediation
1. Clean or replace the fan assembly.
2. Update thermal firmware / BIOS.
3. Validate temperatures under load.

## Expected outcome
Restores performance lost to thermal throttling.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
