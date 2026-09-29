---
id: KB-HW-004
title: Display / input peripheral fault
category: Hardware
subcause: Display / input peripheral fault
tags: screen flickers trackpad unresponsive display cable
---
# KB-HW-004 - Display / input peripheral fault

## Symptoms
Screen flickers and the trackpad is unresponsive.

## Telemetry signature
Hardware health warning without software-side anomalies.

## Diagnosis steps
1. Test with an external monitor and mouse to isolate the component.
2. Update display and HID drivers.

## Remediation
1. Replace the display cable or trackpad assembly.
2. Swap the device if the repair SLA exceeds 2 days.

## Expected outcome
Hardware swaps close these tickets with high first-time-fix rates.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
