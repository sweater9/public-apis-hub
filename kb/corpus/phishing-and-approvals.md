---
title: "Phishing and Token Approvals"
slug: "phishing-and-approvals"
tags: ["phishing", "approvals", "erc20", "security"]
category: "security"
---

# Phishing and Token Approvals

ERC-20 tokens use **allowances**: you authorize a spender contract to move tokens. Attackers trick users into approving a malicious spender, then drain balances.

Defenses: use official bookmarks, read wallet simulation warnings, approve limited amounts when possible, revoke unused approvals (via reputable revoke tools), and prefer hardware wallets for high-value accounts.
