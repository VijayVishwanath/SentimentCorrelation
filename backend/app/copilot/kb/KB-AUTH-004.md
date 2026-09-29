---
id: KB-AUTH-004
title: VPN certificate / authentication
category: Login/Auth
subcause: VPN certificate / authentication
tags: vpn authentication certificate failing cert expired
---
# KB-AUTH-004 - VPN certificate / authentication

## Symptoms
VPN authentication keeps failing.

## Telemetry signature
Auth failures at VPN connect; device certificate near or past expiry.

## Diagnosis steps
1. Check the device certificate expiry and chain.
2. Confirm the VPN auth profile version.

## Remediation
1. Renew the device certificate via MDM.
2. Reissue the VPN authentication profile.

## Expected outcome
Restores remote access immediately for affected users.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
