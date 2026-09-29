---
id: KB-NET-001
title: Wi-Fi adapter / driver instability
category: Network
subcause: Wi-Fi adapter / driver instability
tags: wifi wi-fi drop adapter driver wlan
---
# KB-NET-001 - Wi-Fi adapter / driver instability

## Symptoms
Wi-Fi keeps dropping, especially during calls.

## Telemetry signature
network_latency_ms above 90 (warn) or 160 (critical); packet loss above 1.5%.

## Diagnosis steps
1. Check the latency and packet-loss trend in DEX Sentinel.
2. Verify the WLAN driver version against the approved baseline.
3. Compare against other devices on the same site / access point.

## Remediation
1. Update the WLAN driver; if unresolved, replace the Wi-Fi adapter.
2. Push the QoS network profile.
3. Validate latency below 50ms over 3 days.

## Expected outcome
Across 11 historical network remediations, average latency fell and repeat contacts dropped to ~0%.

## Verify
Close only when the primary telemetry signal is back below its warn threshold and no repeat contact is logged for 7 days (see KB-GEN-001).
