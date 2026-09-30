---
title: "Private Keys and Seed Phrases"
slug: "private-keys-seed-phrases"
tags: ["keys", "seed phrase", "security"]
category: "security"
---

# Private Keys and Seed Phrases

A **private key** is a large secret number. From it you derive a public key and address. Signing with the private key proves you authorized a transaction without revealing the key itself.

A **seed phrase** (BIP-39 mnemonic) is a human-readable backup that generates a tree of keys (hierarchical deterministic wallets). Treat the seed as the master key to every account derived from it.

Best practices:
- Generate seeds offline when possible
- Never enter a seed on a phishing site "to sync" or "verify"
- Prefer hardware wallets for significant balances
- Consider passphrase (25th word) only if you understand recovery complexity
- Plan inheritance carefully — lost keys mean permanently lost funds
