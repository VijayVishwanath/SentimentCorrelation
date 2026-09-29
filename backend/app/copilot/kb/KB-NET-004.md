---
id: KB-NET-004
title: Collaboration traffic QoS
category: Network
subcause: Collaboration traffic QoS
tags: video calls freezing teams meeting qos audio
---
# KB-NET-004 - Collaboration traffic QoS

## Symptoms
Video calls freeze and drop; general browsing is fine.

## Telemetry signature
Latency spikes during meeting hours; call-quality complaints.

## Diagnosis steps
1. Check the Teams call-quality dashboard for the user.
2. Confirm QoS DSCP markings are applied on the device.

## Remediation
1. Push the QoS network profile for Teams media.
2. Prefer wired or 5GHz during meetings.

## Expected outcome
Improves meeting reliability, the most visible part of the employee day.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
