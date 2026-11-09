#!/usr/bin/env python3
"""Reproduce the local checks. Requires Fe 26.5.0 and a system C linker."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FE = os.environ.get("FE", str(ROOT / ".tools/fe"))


def run(label, args):
    print(f"Running {label}", flush=True)
    result = subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180)
    (ROOT / "target" / f"{label}.log").write_text(result.stdout)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise SystemExit(f"{label} failed with exit {result.returncode}")
    return result.stdout


def main():
    (ROOT / "target").mkdir(exist_ok=True)
    version = run("version", [FE, "--version"]).strip()
    if not re.match(r"^fe 26\.5\.0(?:\s|$)", version):
        raise SystemExit(f"Expected Fe 26.5.0, found {version}")
    run("format-library", [FE, "fmt", "--check"])
    run("format-demo", [FE, "fmt", "examples/demo", "--check"])
    native = run("native-tests", [FE, "test", "--backend", "native"])
    evm = run("evm-tests", [FE, "test", "--backend", "sonatina"])
    run("build-demo", [FE, "build", "examples/demo", "--backend", "native",
                       "--out-dir", "target", "--emit", "executable"])
    run("oracle", [sys.executable, "scripts/verify.py"])
    report = {"status": "passed", "toolchain": version,
              "native": re.search(r"test result:.*", native).group(0),
              "evm": re.search(r"test result:.*", evm).group(0),
              "oracle": json.loads((ROOT / "target/verification.json").read_text())}
    (ROOT / "target/checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print("All checks passed. Evidence: target/checks.json")


if __name__ == "__main__":
    main()
