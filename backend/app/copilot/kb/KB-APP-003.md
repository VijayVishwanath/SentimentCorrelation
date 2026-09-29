---
id: KB-APP-003
title: Outlook mail profile corruption
category: Application Crash
subcause: Mail profile corruption
tags: outlook profile corruption ost repair rebuild mail crash
---
# KB-APP-003 - Outlook mail profile corruption

## Symptoms
Outlook crashes on start or while syncing; persists across reboots and reinstalls; often a repeat contact.

## Telemetry signature
Crash tickets mentioning Outlook with repeat contacts; hang count elevated only while Outlook runs.

## Diagnosis steps
1. Start Outlook in safe mode (outlook.exe /safe) to rule out add-ins.
2. Run the Inbox Repair Tool (scanpst) against the OST.
3. Check OST size (>50 GB is a risk factor).

## Remediation
1. Create a new mail profile from Control Panel > Mail > Show Profiles.
2. Rename the old OST so a clean cache is rebuilt.
3. Re-add shared mailboxes and calendars.
4. Confirm no crashes for 5 working days before closing.

## Expected outcome
Repairing the profile removes the cause that a plain reinstall misses, preventing the repeat-contact loop.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
