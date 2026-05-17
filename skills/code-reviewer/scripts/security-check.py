#!/usr/bin/env python3
"""Fast security-only pass for ShopSense repos (bandit, semgrep, secret heuristics)."""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def shopsense_secret_patterns() -> list[str]:
    return [
        r"password\s*=\s*[\"']",
        r"api_key\s*=\s*[\"']",
        r"secret\s*=\s*[\"'][^\"']{10,}",
        r"AWS_ACCESS_KEY",
        r"PRIVATE_KEY",
        r"GROQ_API_KEY\s*=",
        r"QDRANT_(API_KEY|URL)\s*=",
        r"KAFKA_BOOTSTRAP",
        r"SUPABASE_(KEY|SERVICE_ROLE)",
        r"DATABASE_URL\s*=\s*[\"']postgres",
        r"LANGSMITH_API_KEY",
    ]


def run_security_checks(file_path: Path) -> bool:
    print(f"\nSecurity check: {file_path}")
    print("=" * 70)
    passed = True

    print("\n1. Bandit (Python)...")
    result = subprocess.run(
        ["bandit", "-ll", "-ii", "-r", str(file_path)],
        capture_output=True,
        text=True,
    )
    if "No issues identified" in result.stdout:
        print("   Bandit: no issues")
    else:
        print("   Bandit reported issues:")
        print(result.stdout)
        passed = False

    print("\n2. Semgrep...")
    result = subprocess.run(
        ["semgrep", "--config=auto", "--quiet", "--error", str(file_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("   Semgrep: no issues")
    else:
        print("   Semgrep reported issues")
        tail = result.stdout[-800:] if len(result.stdout) > 800 else result.stdout
        print(tail)
        passed = False

    print("\n3. ShopSense secret heuristics...")
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        hits = []
        for pattern in shopsense_secret_patterns():
            if re.search(pattern, content, re.IGNORECASE):
                hits.append(pattern[:48])
        if hits:
            print("   Possible patterns matched (review):")
            for h in hits[:12]:
                print(f"     - {h}...")
            passed = False
        else:
            print("   No obvious secret literals")
    except OSError as e:
        print(f"   Could not read file: {e}")
        passed = False

    print("\n" + "=" * 70)
    print("PASSED" if passed else "ISSUES FOUND")
    print("=" * 70)
    return passed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    target = Path(args.path)

    if target.is_file():
        files = [target]
    else:
        files = (
            list(target.rglob("*.py"))
            + list(target.rglob("*.js"))
            + list(target.rglob("*.ts"))
            + list(target.rglob("*.tsx"))
        )

    ok = all(run_security_checks(f) for f in files)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
