---
id: KB-NET-002
title: VPN tunnel instability
category: Network
subcause: VPN tunnel instability
tags: vpn tunnel disconnect packet loss split tunnel gateway
---
# KB-NET-002 - VPN tunnel instability

## Symptoms
Cannot stay connected to the VPN; drops mid-session.

## Telemetry signature
packet_loss_pct at or above 1.5% (warn) / 3.5% (critical); often remote workers.

## Diagnosis steps
1. Check VPN client logs for renegotiation events.
2. Test against the nearest gateway; confirm MTU settings.

## Remediation
1. Re-provision the VPN profile and move the user to the nearest gateway.
2. Enable split-tunnel for SaaS collaboration traffic per policy.
3. Validate stable sessions for 5 days.

## Expected outcome
Stable tunnels remove the most frustrating repeat-contact pattern for remote staff.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
