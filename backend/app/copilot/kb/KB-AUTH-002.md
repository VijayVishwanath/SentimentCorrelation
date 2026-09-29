---
id: KB-AUTH-002
title: MFA token / authenticator desync
category: Login/Auth
subcause: MFA token / authenticator desync
tags: mfa code rejected authenticator token clock
---
# KB-AUTH-002 - MFA token / authenticator desync

## Symptoms
MFA keeps rejecting the user even with the right code.

## Telemetry signature
Login/Auth tickets without non-compliance; often repeat contacts.

## Diagnosis steps
1. Check sign-in logs for the failure reason (invalid code vs. clock skew).
2. Verify device and phone time sync.

## Remediation
1. Re-register the MFA method.
2. Resync the device clock (w32tm /resync).
3. Issue a temporary access pass if the user is blocked.

## Expected outcome
Typically resolved on first contact once re-registered.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
