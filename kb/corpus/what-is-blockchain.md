---
title: "What Is a Blockchain?"
slug: "what-is-blockchain"
tags: ["blockchain", "basics", "ledger"]
category: "basics"
---

# What Is a Blockchain?

A blockchain is an append-only ledger of transactions grouped into **blocks**, each cryptographically linked to the previous block. That chain of hashes makes tampering with old history obvious unless an attacker can rewrite many blocks and convince the network.

Typical pieces:
- **Transactions** — transfers or contract calls
- **Blocks** — batches of transactions plus a header (timestamp, previous hash, etc.)
- **Consensus** — the rules nodes use to agree which chain is valid (Proof of Work, Proof of Stake, etc.)
- **Nodes** — computers that store and verify the ledger

Public blockchains like Bitcoin and Ethereum are open for anyone to read and (with fees) write. Private or permissioned chains restrict who can validate. Blockchains trade some throughput and latency for auditability and censorship resistance.
