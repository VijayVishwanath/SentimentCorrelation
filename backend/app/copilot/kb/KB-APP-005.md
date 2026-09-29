---
id: KB-APP-005
title: Outdated / unpatched application build
category: Application Crash
subcause: Outdated / unpatched build
tags: outdated unpatched build update version patch compliance
---
# KB-APP-005 - Outdated / unpatched application build

## Symptoms
Crashes on older devices or devices that have fallen out of compliance and missed update rings.

## Telemetry signature
Device age 36+ months or non-compliant policy state alongside crash tickets.

## Diagnosis steps
1. Compare the installed build to the current release channel.
2. Check whether the device is receiving update-ring policy (compliance state).

## Remediation
1. Force the latest build via software center / Intune.
2. Remediate compliance first if the device is non-compliant (KB-AUTH-001).
3. Validate the build number after restart.

## Expected outcome
Bringing the build current removes known crash defects fixed upstream.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
