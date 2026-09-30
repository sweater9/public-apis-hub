---
title: "Payment Rails Overview"
slug: "payment-rails-overview"
tags: ["payments", "rails", "ach", "wire", "sepa", "rtp", "fednow"]
category: "fintech"
---

# Payment Rails Overview

A **payment rail** is the network and rulebook that moves money between accounts.

Common rails:
- **Wire (SWIFT / Fedwire / CHAPS)** — high-value, usually same-day, higher fees; often used for treasury and B2B
- **ACH (US)** — batch electronic transfers; cheap; settlement often next business day (same-day ACH exists)
- **SEPA Credit Transfer / Instant (EU)** — euro transfers across the SEPA zone
- **Cards (Visa/Mastercard networks)** — authorization, clearing, then settlement between issuer and acquirer
- **RTP / FedNow (US)** — real-time account-to-account payments
- **FPS (UK)** — Faster Payments for near-instant GBP transfers

Fintech products usually sit **on top of** these rails (via banks or licensed partners), not replace them entirely.
