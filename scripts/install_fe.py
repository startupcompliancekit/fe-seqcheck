#!/usr/bin/env python3
"""Fetch the pinned official Linux x86-64 release; verify before chmod."""
import hashlib
import platform
from pathlib import Path
import urllib.request

VERSION = "26.5.0"
SHA256 = "3732fbe8a6e9d2ea3925d02d0e3a1478bc1e01d742c2be75d3ea7300c46c45f0"
URL = f"https://github.com/argotorg/fe/releases/download/v{VERSION}/fe_linux_amd64"


def main():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This installer supports Linux x86-64 only. See README for other platforms.")
    dest = Path(__file__).resolve().parents[1] / ".tools/fe"
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == SHA256:
        print(f"Already verified Fe {VERSION}: {dest}")
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(100_000_001)
    if len(data) > 100_000_000 or hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Release size/digest mismatch; nothing installed.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_suffix(".download")
    staging.write_bytes(data)
    staging.chmod(0o755)
    staging.replace(dest)
    print(f"Verified and installed Fe {VERSION}: {dest}")


if __name__ == "__main__":
    main()
