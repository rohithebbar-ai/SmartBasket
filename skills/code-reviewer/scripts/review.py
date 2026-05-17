#!/usr/bin/env python3
"""
ShopSense-oriented review helper — Python / JS / TS.
Runs bandit, ruff, mypy (optional), semgrep (optional), plus ShopSense-specific secret heuristics.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def run_command(cmd: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"


def check_security_python(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    rc, stdout, stderr = run_command(
        ["bandit", "-f", "json", "-ll", "-ii", "-r", str(file_path)]
    )
    if rc != 0 and stdout:
        try:
            data = json.loads(stdout)
            for result in data.get("results", []):
                issues.append(
                    {
                        "severity": result.get("issue_severity", "MEDIUM"),
                        "confidence": result.get("issue_confidence"),
                        "rule": result.get("test_id"),
                        "message": result.get("issue_text"),
                        "file": result.get("filename"),
                        "line": result.get("line_number"),
                        "code": result.get("code"),
                    }
                )
        except json.JSONDecodeError:
            pass
    return issues


def check_style_python(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    rc, stdout, stderr = run_command(
        ["ruff", "check", "--output-format=json", str(file_path)]
    )
    if stdout:
        try:
            data = json.loads(stdout)
            for item in data:
                issues.append(
                    {
                        "severity": "LOW",
                        "rule": item.get("code"),
                        "message": item.get("message"),
                        "file": item.get("filename"),
                        "line": item.get("location", {}).get("row"),
                        "code": item.get("code"),
                    }
                )
        except json.JSONDecodeError:
            pass
    return issues


def check_types_python(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    rc, stdout, stderr = run_command(
        ["mypy", "--show-error-codes", "--no-error-summary", str(file_path)]
    )
    if stdout:
        for line in stdout.split("\n"):
            if ":" in line and "error:" in line:
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    file_part, line_num, _, msg = parts[:4]
                    issues.append(
                        {
                            "severity": "MEDIUM",
                            "rule": "TYPE_ERROR",
                            "message": msg.strip(),
                            "file": file_part.strip(),
                            "line": int(line_num) if line_num.isdigit() else 0,
                        }
                    )
    return issues


def check_security_semgrep(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    rc, stdout, stderr = run_command(
        ["semgrep", "--config=auto", "--json", "--quiet", str(file_path)]
    )
    if stdout:
        try:
            data = json.loads(stdout)
            for result in data.get("results", []):
                issues.append(
                    {
                        "severity": result.get("extra", {}).get("severity", "MEDIUM"),
                        "rule": result.get("check_id"),
                        "message": result.get("extra", {}).get("message"),
                        "file": result.get("path"),
                        "line": result.get("start", {}).get("line"),
                        "code": result.get("extra", {}).get("lines"),
                    }
                )
        except json.JSONDecodeError:
            pass
    return issues


def shopsense_secret_patterns() -> list[tuple[str, str]]:
    """Regex + label — generic leaks plus ShopSense stack env names."""
    return [
        (r"password\s*=\s*[\"']([^\"']+)[\"']", "Hardcoded password"),
        (r"api_key\s*=\s*[\"']([^\"']+)[\"']", "Hardcoded API key"),
        (r"secret\s*=\s*[\"']([^\"']+)[\"']", "Hardcoded secret"),
        (r"token\s*=\s*[\"']([^\"']{20,})[\"']", "Hardcoded token"),
        (r"AWS_ACCESS_KEY_ID\s*=\s*[\"']([^\"']+)[\"']", "AWS key"),
        (r"PRIVATE_KEY\s*=\s*[\"']-----BEGIN", "Private key"),
        (r"GROQ_API_KEY\s*=\s*[\"']([^\"']+)[\"']", "GROQ_API_KEY literal"),
        (r"(QDRANT_(API_KEY|URL)|qdrant[_-]?api[_-]?key)\s*=\s*[\"']([^\"']+)[\"']", "Qdrant credential"),
        (r"(KAFKA_BOOTSTRAP|KAFKA_[A-Z_]*)\s*=\s*[\"']([^\"']+)[\"']", "Kafka connection secret"),
        (r"(SUPABASE_(URL|KEY|SERVICE_ROLE)|DATABASE_URL)\s*=\s*[\"']([^\"']{8,})[\"']", "DB or Supabase URL/key literal"),
        (r"(LANGCHAIN_API_KEY|LANGSMITH_API_KEY)\s*=\s*[\"']([^\"']+)[\"']", "LangSmith / LangChain key"),
    ]


def check_hardcoded_secrets(file_path: Path) -> list[dict]:
    issues: list[dict] = []
    import re

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return issues

    for pattern, msg in shopsense_secret_patterns():
        for match in re.finditer(pattern, content, re.IGNORECASE):
            line_num = content[: match.start()].count("\n") + 1
            snippet = match.group(0)
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            issues.append(
                {
                    "severity": "CRITICAL",
                    "rule": "HARDCODED_SECRET",
                    "message": f"Possible hardcoded secret: {msg}",
                    "file": str(file_path),
                    "line": line_num,
                    "code": snippet,
                }
            )
    return issues


def generate_report(target: Path, all_issues: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("SHOPSENSE CODE REVIEW")
    lines.append(f"Target: {target}")
    lines.append("=" * 70)

    if not all_issues:
        lines.append("\n✅ No issues found (or tools missing — confirm bandit/ruff/semgrep installed).")
        return "\n".join(lines)

    critical = [i for i in all_issues if i.get("severity") == "CRITICAL"]
    high = [i for i in all_issues if i.get("severity") in ["HIGH", "ERROR"]]
    medium = [i for i in all_issues if i.get("severity") in ["MEDIUM", "WARNING"]]
    low = [i for i in all_issues if i.get("severity") in ["LOW", "INFO"]]

    lines.append("\n## Summary")
    lines.append(f"- Critical: {len(critical)}")
    lines.append(f"- High: {len(high)}")
    lines.append(f"- Medium: {len(medium)}")
    lines.append(f"- Low: {len(low)}")
    lines.append(f"- Total: {len(all_issues)}")

    if critical:
        lines.append("\n## Critical")
        for issue in critical[:15]:
            lines.append(f"\n  [{issue['file']}:{issue['line']}] {issue.get('rule')}")
            lines.append(f"  → {issue['message']}")
            if issue.get("code"):
                lines.append(f"     {issue['code']}")

    if high:
        lines.append("\n## High")
        for issue in high[:15]:
            lines.append(f"\n  [{issue['file']}:{issue['line']}] {issue.get('rule')}")
            lines.append(f"  → {issue['message']}")

    if medium:
        lines.append(f"\n## Medium ({len(medium)} issues)")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="ShopSense code review")
    parser.add_argument("path", help="File or directory")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--security-only", action="store_true")
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

    all_issues: list[dict] = []
    for file in files:
        if file.suffix == ".py":
            if args.security_only:
                batch = (
                    check_security_python(file)
                    + check_security_semgrep(file)
                    + check_hardcoded_secrets(file)
                )
            else:
                batch = (
                    check_security_python(file)
                    + check_style_python(file)
                    + check_types_python(file)
                    + check_security_semgrep(file)
                    + check_hardcoded_secrets(file)
                )
            all_issues.extend(batch)
        else:
            all_issues.extend(check_security_semgrep(file))
            all_issues.extend(check_hardcoded_secrets(file))

    if args.json:
        print(json.dumps(all_issues, indent=2))
    else:
        print(generate_report(target, all_issues))

    critical_count = len([i for i in all_issues if i.get("severity") == "CRITICAL"])
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()
