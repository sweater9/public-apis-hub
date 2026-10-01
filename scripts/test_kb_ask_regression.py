#!/usr/bin/env python3
"""Minimal regression checks for KB ask question-type answers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kb.engine_core import ensure_index  # noqa: E402
from kb.ask_engine import ask  # noqa: E402


def _ok(cond: bool, msg: str, failures: list[str]) -> None:
    if not cond:
        failures.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:  ", msg)


def main() -> int:
    ensure_index()
    failures: list[str] = []

    r = ask("What is Bitcoin?")
    ans = (r.get("answer") or "").lower()
    primary = (r.get("sources") or [{}])[0].get("slug")
    _ok(primary == "bitcoin-basics", f"Bitcoin primary is bitcoin-basics (got {primary})", failures)
    _ok(
        ans.startswith("bitcoin") and "cryptocurrency" in ans and "2009" in ans,
        "Bitcoin answer opens with a definition from basics",
        failures,
    )
    _ok(
        "210,000" not in ans[:120] and "halves" not in ans.split(".")[0],
        "Bitcoin definition is not the halving blurb",
        failures,
    )

    r2 = ask("How does Bitcoin halving work?")
    primary2 = (r2.get("sources") or [{}])[0].get("slug")
    ans2 = (r2.get("answer") or "").lower()
    _ok(primary2 == "bitcoin-halving", f"Halving how-to primary is bitcoin-halving (got {primary2})", failures)
    _ok("210,000" in ans2 or "halves" in ans2, "Halving how-to mentions subsidy halving", failures)

    r3 = ask("What is proof of work?")
    primary3 = (r3.get("sources") or [{}])[0].get("slug")
    _ok(primary3 == "proof-of-work", f"PoW primary is proof-of-work (got {primary3})", failures)

    r4 = ask("What is Ethereum?")
    ans4 = (r4.get("answer") or "").lower()
    _ok(ans4.startswith("ethereum") and "smart contract" in ans4, "Ethereum opens with a definition", failures)

    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print("\nAll KB ask regressions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
