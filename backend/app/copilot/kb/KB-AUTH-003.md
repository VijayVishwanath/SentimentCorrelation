---
id: KB-AUTH-003
title: Account lockout (stale cached credentials)
category: Login/Auth
subcause: Account lockout (stale cached credentials)
tags: locked out account lockout password cached credentials
---
# KB-AUTH-003 - Account lockout (stale cached credentials)

## Symptoms
User keeps getting locked out of their account.

## Telemetry signature
Repeated lockouts after a password change; multiple devices or sessions.

## Diagnosis steps
1. Identify the lockout source in directory logs.
2. Check for stale credentials in Credential Manager, mapped drives and mobile mail.

## Remediation
1. Clear cached credentials on all devices.
2. Unlock the account and confirm sign-in.
3. Update the password on mobile mail clients.

## Expected outcome
Stops the repeat-lockout loop that drives escalations.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
