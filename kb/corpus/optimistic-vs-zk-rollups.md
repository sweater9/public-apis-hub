---
title: "Optimistic Rollups vs ZK Rollups"
slug: "optimistic-vs-zk-rollups"
tags: ["rollups", "optimistic", "zk", "l2"]
category: "layer2"
---

# Optimistic Rollups vs ZK Rollups

**Optimistic rollups** assume transactions are valid unless challenged during a dispute window. Withdrawals to L1 can take days unless a fast bridge/liquidity provider is used.

**ZK rollups** post validity proofs (zero-knowledge style) that transactions were executed correctly. Withdrawals can be faster once proofs are verified, with different proving costs and complexity.

Both still need careful bridge security and operator honesty assumptions that evolve over time.
