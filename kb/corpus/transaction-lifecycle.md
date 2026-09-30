---
title: "Crypto Transaction Lifecycle"
slug: "transaction-lifecycle"
tags: ["transactions", "mempool", "confirmations"]
category: "basics"
---

# Crypto Transaction Lifecycle

1. Create and sign a transaction with your wallet
2. Broadcast to nodes / mempool
3. A block producer includes it in a block
4. Additional blocks add confirmations
5. Application treats it as final after enough depth

Pending transactions may be replaced (if allowed) by bumping fees. On some chains, MEV searchers reorder mempool transactions for profit — another reason slippage and private relay options matter for large swaps.
