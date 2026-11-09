#!/usr/bin/env python3
"""Independent behavioral checks of the compiled Fe example; stdlib only."""
import itertools
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "target/demo"
MASK = (1 << 64) - 1
calls = 0


def invoke(*args, expected=None):
    global calls
    p = subprocess.run([str(EXE), *map(str, args)], capture_output=True, text=True, timeout=5)
    calls += 1
    assert not p.stderr, p.stderr
    result = json.loads(p.stdout)
    if expected is not None:
        assert p.returncode == expected, (args, p.returncode, result)
    else:
        assert p.returncode == (1 if result["failure"] else 0), (args, result)
    return result


def generated(seed):
    x = seed or 0x9E3779B97F4A7C15
    out = []
    for _ in range(64):
        x ^= (x << 13) & MASK
        x ^= x >> 7
        x ^= (x << 17) & MASK
        out.append(x % 16)
    return out


def oracle(words, fixed=False):
    # Track amounts from the command history, rather than the Fe struct fields.
    credits = debits = accepted = 0
    for i, word in enumerate(words, 1):
        amount = 1 + (word // 2) % 8
        if word % 2 == 0:
            credits += amount
            accepted += 1
        elif credits - debits >= amount:
            debits += amount
            accepted += 1
            if not fixed:
                return {"failure": 7, "attempted": i, "accepted": accepted}
    return {"failure": 0, "attempted": len(words), "accepted": accepted}


def check_report(result, fixed=False):
    expected = oracle(result["trace"], fixed)
    for key, value in expected.items():
        assert result[key] == value, (key, result, expected)


def candidates(words):
    for i in range(len(words)):
        yield words[:i] + words[i + 1:]
        if words[i]:
            for value in [0]:
                yield words[:i] + [value] + words[i + 1:]
            value = words[i] // 2
            while value:
                yield words[:i] + [value] + words[i + 1:]
                value //= 2


def main():
    summaries = []
    seeds = list(range(65)) + [MASK, 1 << 63, 123456789]
    for seed in seeds:
        for fixed in (False, True):
            r = invoke("fixed" if fixed else "buggy", seed, 1000)
            assert r["trace"] == generated(seed)
            check_report(r, fixed)
            assert r["evaluations"] <= r["budget"] and not r["exhausted"]
            assert oracle(r["reduced"], fixed)["failure"] == r["failure"]
            replayed = invoke("replay-fixed" if fixed else "replay", *r["reduced"])
            check_report(replayed, fixed)
            if r["failure"]:
                assert all(oracle(c)["failure"] != r["failure"] for c in candidates(r["reduced"]))
            else:
                assert r["reduced"] == r["trace"] and r["evaluations"] == 0
            if seed == 42:
                summaries.append(r)

    for budget in range(25):
        r = invoke("buggy", 42, budget)
        assert r["failure"] == 7 and r["evaluations"] <= budget
        assert oracle(r["reduced"])["failure"] == 7
        assert not r["exhausted"] or r["evaluations"] == budget

    # Exhaustive short traces test model behavior independently of generation.
    for n in range(5):
        for words in itertools.product(range(4), repeat=n):
            r = invoke("replay", *words)
            check_report(r)
    for words in ([], [MASK], [MASK - 1, MASK], [0] * 64, [1] * 64):
        for fixed in (False, True):
            check_report(invoke("replay-fixed" if fixed else "replay", *words), fixed)

    bad = [(), ("unknown",), ("buggy", "-1"), ("fixed", "1.2"),
           ("buggy", str(MASK + 1)), ("buggy", ""), ("buggy", "1", "10001"),
           ("buggy", "1", "2", "3"), ("replay", "x"), ("replay", "-1"),
           ("replay", str(MASK + 1)), ("replay", *([0] * 65))]
    for args in bad:
        assert "error" in invoke(*args, expected=2)

    # Byte-for-byte deterministic output on repeated invocations.
    assert invoke("buggy", 42, 1000) == summaries[0]
    report = {"status": "passed", "cliInvocations": calls, "seedCount": len(seeds),
              "exhaustiveShortTraces": sum(4 ** n for n in range(5)),
              "checks": ["independent replay oracle", "known deterministic stream", "failure preservation",
                         "single-deletion and zero/halving fixed point", "budget caps", "rejected inputs",
                         "fixed model", "exit codes", "u64 boundaries"], "examples": summaries}
    (ROOT / "target/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, indent=2))


if __name__ == "__main__":
    main()
