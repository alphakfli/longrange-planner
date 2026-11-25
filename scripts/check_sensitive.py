"""Scan the repository for things that should not be published: secrets, personal data, local paths,
real company names, and author metadata inside Excel files.

    python scripts/check_sensitive.py              # scan the repo, exit 1 if anything is found
    python scripts/check_sensitive.py --verbose    # also list what was checked

Put words that must never appear (your employer, real suppliers or customers, colleague names) one per line in
a file called ``.sensitive-words`` in the repo root. That file is git-ignored, so the list itself stays private.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist", "output",
             ".mypy_cache", "node_modules", "site"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc", ".whl"}
MAX_BYTES = 5_000_000

PATTERNS = {
    "Private key": r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_\-]{35}\b",
    "OpenAI / Anthropic key": r"\bsk-(ant-)?[A-Za-z0-9_\-]{24,}\b",
    "Password or secret assignment": r"(?i)\b(password|passwd|pwd|secret|api_key|apikey|access_token|client_secret)\b\s*[:=]\s*['\"][^'\"\s]{6,}['\"]",
    "Connection string": r"(?i)\b(Server|Data Source)=[^;\n]+;.*(Password|Pwd)=",
    "Email address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "Phone number": r"(?<![\w.])(\+?1[ .-]?)?\(?\b[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}\b",
    "Windows user path": r"(?i)\b[A-Z]:\\Users\\(?!Public\b|Default\b|<)[A-Za-z0-9._-]+",
    "Home directory path": r"/(home|Users)/(?!runner\b|<|user\b|you\b)[a-z][a-z0-9._-]+/",
    "Private IP address": r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
    "SAP system / client id": r"(?i)\bclient\s*[:=]\s*\d{3}\b|\bsap[_-]?(user|password|host)\b\s*[:=]",
}
ALLOW_EMAIL = re.compile(r"(?i)(noreply@|@example\.(com|org)|@users\.noreply\.github\.com|@anthropic\.com)")
# The author name in LICENSE / pyproject is intentional; listed so it is reported as info, not as a finding.
AUTHOR_FILES = {"LICENSE", "pyproject.toml"}


def files():
    """Every file in the repo, without walking into virtual environments, caches or build folders."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for f in filenames:
            p = Path(dirpath) / f
            if f in (".sensitive-words",) or p.suffix.lower() in SKIP_SUFFIX:
                continue
            yield p


def text_of(p: Path) -> list[tuple[str, str]]:
    """(label, text) pieces. Office files are unzipped so cell text and document properties are checked too."""
    if p.suffix.lower() in (".xlsx", ".xlsm", ".docx", ".pptx"):
        out = []
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith(".xml"):
                    out.append((f"{p.name}:{n}", z.read(n).decode("utf-8", "ignore")))
        return out
    if p.suffix.lower() == ".pdf":
        return [(p.name, p.read_bytes().decode("latin-1", "ignore"))]
    try:
        return [(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8"))]
    except UnicodeDecodeError:
        return []


def office_author(text: str) -> list[str]:
    hits = re.findall(r"<(dc:creator|cp:lastModifiedBy)\b[^>]*>([^<]+)</", text)
    return [f"{k}={v}" for k, v in hits if v.strip().lower() not in ("openpyxl", "python", "")]


def main() -> int:
    verbose = "--verbose" in sys.argv
    words = []
    wf = ROOT / ".sensitive-words"
    if wf.exists():
        words = [w.strip() for w in wf.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]
    findings, checked = [], 0
    me = Path(__file__).resolve()
    for p in files():
        checked += 1
        if p.stat().st_size > MAX_BYTES:
            findings.append((str(p.relative_to(ROOT)), "Large file", f"{p.stat().st_size / 1e6:.1f} MB"))
        if p.resolve() == me:
            continue
        for label, txt in text_of(p):
            for name, pat in PATTERNS.items():
                for m in re.finditer(pat, txt):
                    val = m.group(0)
                    if name == "Email address" and ALLOW_EMAIL.search(val):
                        continue
                    if name == "Phone number" and re.fullmatch(r"\d{3}[ .-]\d{3}[ .-]\d{4}", val) and "phone" not in txt[max(0, m.start() - 40):m.start()].lower():
                        # bare 10-digit groups inside data (PO numbers etc.) are not phone numbers
                        continue
                    findings.append((label, name, val[:80]))
            for a in office_author(txt):
                findings.append((label, "Document author metadata", a))
            for w in words:
                if re.search(rf"(?i)\b{re.escape(w)}\b", txt):
                    findings.append((label, "Word from .sensitive-words", w))
    print(f"Checked {checked} files in {ROOT.name}" + (f" against {len(words)} private words" if words else
                                                       " (no .sensitive-words file: real company names not checked)"))
    for f in sorted(AUTHOR_FILES):
        if (ROOT / f).exists() and verbose:
            print(f"  info: {f} names the author on purpose")
    if findings:
        print(f"\n{len(findings)} possible issue(s):")
        for loc, kind, val in findings:
            print(f"  {kind:32s} {loc}: {val}")
        return 1
    print("No sensitive data found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
