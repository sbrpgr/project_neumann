"""검증 러너. main 병합·push 전에 반드시 통과해야 한다(계획서 §6).

    python scripts/verify.py              전체: 보안 + 계약 + 테스트
    python scripts/verify.py --security   보안만(추적·미추적 파일 + 커밋 메시지). pre-push 훅
    python scripts/verify.py --staged     스테이징된 내용만 보안 검사. pre-commit 훅
    python scripts/verify.py --message F  커밋 메시지 파일 검사. commit-msg 훅

보안 검사는 표준 라이브러리만 쓴다. 찾은 비밀값은 절대 출력하지 않고 위치와 종류만 알린다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 5 * 1024 * 1024

# 패턴 문자열을 쪼개 써서 이 파일 자체가 검사에 걸리지 않게 한다.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI 키", re.compile(r"\bs" r"k-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("Anthropic 키", re.compile(r"\bs" r"k-ant-[A-Za-z0-9_\-]{20,}")),
    ("GitHub 토큰", re.compile(r"\b(?:gh" r"[pousr]_[A-Za-z0-9]{30,}|github" r"_pat_[A-Za-z0-9_]{30,})")),
    ("Hugging Face 토큰", re.compile(r"\bh" r"f_[A-Za-z0-9]{30,}")),
    ("AWS 액세스 키", re.compile(r"\bAK" r"IA[0-9A-Z]{16}\b")),
    ("Google API 키", re.compile(r"\bAI" r"za[0-9A-Za-z_\-]{35}\b")),
    ("Slack 토큰", re.compile(r"\bxo" r"x[abprs]-[A-Za-z0-9\-]{10,}")),
    ("개인 키", re.compile(r"-----BEGIN" r" (?:[A-Z]+ )?PRIVATE KEY-----")),
    (
        "비밀값 대입",
        re.compile(
            r"(?i)\b[A-Z0-9_]*(?:api[_\-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?"
            r"(?=[A-Za-z0-9_\-/+=]*\d)(?=[A-Za-z0-9_\-/+=]*[a-z])[A-Za-z0-9_\-/+=]{24,}"
        ),
    ),
]

# 올리면 안 되는 경로. .env.example만 예외다.
FORBIDDEN_PATH = re.compile(
    r"(?i)(^|/)("
    r"\.env(\..+)?"
    r"|[^/]*\.(pem|key|p12|pfx|parquet|arrow|feather|npy|npz|faiss|sqlite3?|db|safetensors|pt|pth|ckpt|onnx|gguf)"
    r"|id_(rsa|ed25519)[^/]*"
    r"|credentials[^/]*\.json|service-account[^/]*\.json"
    r")$"
    r"|(^|/)data/"
)
ALLOWED_PATH = re.compile(r"(^|/)\.env\.example$")

SECRET_NAME = re.compile(r"(?i)(KEY|SECRET|TOKEN|SALT|PASSWORD|PASSWD)")
EXTRA_ENV_SECRETS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "HF_TOKEN")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ROOT, capture_output=True, check=check)


def git_paths(*args: str) -> list[str]:
    out = git(*args).stdout.decode("utf-8", "replace")
    return [p for p in out.split("\0") if p]


def has_head() -> bool:
    return git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def load_real_secrets() -> dict[str, str]:
    """.env와 환경변수에 든 실제 비밀값. 이 문자열이 어디에든 나오면 유출이다."""
    found: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip().removeprefix("export ").strip()
            value = value.strip().strip("'\"")
            if SECRET_NAME.search(name) and len(value) >= 8:
                found[f".env:{name}"] = value
    for name in EXTRA_ENV_SECRETS:
        value = os.environ.get(name, "")
        if len(value) >= 16:
            found[f"환경변수:{name}"] = value
    return found


def scan_text(label: str, data: bytes, secrets: dict[str, str], problems: list[str]) -> None:
    for name, value in secrets.items():
        if value.encode() in data:
            problems.append(f"[유출] {label}: 실제 비밀값({name})이 들어 있다")
    if b"\0" in data[:8192]:
        return
    text = data.decode("utf-8", "replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                problems.append(f"[비밀값] {label}:{lineno}: {kind} 형태의 문자열")


def check_path(path: str, size: int, problems: list[str]) -> None:
    if FORBIDDEN_PATH.search(path) and not ALLOWED_PATH.search(path):
        problems.append(f"[금지 파일] {path}: 비밀값·데이터·가중치 파일은 올리지 않는다")
    if size > MAX_FILE_BYTES:
        problems.append(f"[대용량] {path}: {size / 1024 / 1024:.1f}MB (상한 {MAX_FILE_BYTES // 1024 // 1024}MB)")


def check_env_example(data: bytes, problems: list[str]) -> None:
    for lineno, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if SECRET_NAME.search(name) and value.strip().strip("'\""):
            problems.append(f"[견본] .env.example:{lineno}: {name.strip()} 값은 비워 둔다")


def check_gitignore(problems: list[str]) -> None:
    for probe in (".env", ".env.local", "data/x.parquet"):
        if git("check-ignore", "-q", "--no-index", probe, check=False).returncode != 0:
            problems.append(f"[gitignore] {probe} 가 무시되지 않는다")


def security_worktree(problems: list[str]) -> int:
    """추적 파일 + 무시되지 않은 미추적 파일(곧 add될 수 있는 것) + 커밋 메시지."""
    secrets = load_real_secrets()
    paths = git_paths("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for path in paths:
        full = ROOT / path
        if not full.is_file():
            continue
        data = full.read_bytes()
        check_path(path, len(data), problems)
        scan_text(path, data, secrets, problems)
        if path == ".env.example":
            check_env_example(data, problems)
    if has_head():
        log = git("log", "--all", "--format=%H%n%B%x00").stdout
        for entry in log.split(b"\0"):
            entry = entry.strip()
            if entry:
                sha, _, body = entry.partition(b"\n")
                scan_text(f"커밋 {sha[:8].decode()} 메시지", body, secrets, problems)
    check_gitignore(problems)
    return len(paths)


def security_staged(problems: list[str]) -> int:
    secrets = load_real_secrets()
    paths = git_paths("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    for path in paths:
        data = git("show", f":{path}").stdout
        check_path(path, len(data), problems)
        scan_text(f"{path} (스테이징)", data, secrets, problems)
        if path == ".env.example":
            check_env_example(data, problems)
    return len(paths)


def check_contracts(problems: list[str]) -> str:
    files = sorted((ROOT / "contracts").glob("*.json"))
    try:
        from jsonschema.validators import validator_for
    except ImportError:
        validator_for = None
    for f in files:
        try:
            schema = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"[계약] {f.name}: JSON 파싱 실패 ({exc})")
            continue
        if validator_for is not None:
            try:
                validator_for(schema).check_schema(schema)
            except Exception as exc:  # jsonschema.SchemaError
                problems.append(f"[계약] {f.name}: 스키마 오류 ({str(exc).splitlines()[0]})")
    note = "" if validator_for else " (jsonschema 없음: 파싱만)"
    return f"{len(files)}개{note}"


def run_tests(problems: list[str]) -> str:
    tests = [p for p in (ROOT / "tests").rglob("test_*.py")] if (ROOT / "tests").is_dir() else []
    if not tests:
        return "건너뜀(테스트 없음)"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    if result.returncode != 0:
        problems.append(f"[테스트] pytest 실패 (exit {result.returncode})")
        return "실패"
    return "통과"


def warn_hooks() -> None:
    hooks = git("config", "--get", "core.hooksPath", check=False).stdout.decode().strip()
    if hooks != ".githooks":
        print("주의: git 훅이 꺼져 있다. 켜려면  git config core.hooksPath .githooks")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--security", action="store_true")
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--message", metavar="FILE")
    args = parser.parse_args()

    problems: list[str] = []
    if args.message:
        scan_text("커밋 메시지", Path(args.message).read_bytes(), load_real_secrets(), problems)
    elif args.staged:
        print(f"보안(스테이징): 파일 {security_staged(problems)}개")
    else:
        print(f"보안: 파일 {security_worktree(problems)}개")
        if not args.security:
            warn_hooks()
            print(f"계약: {check_contracts(problems)}")
            print(f"테스트: {run_tests(problems)}")

    if problems:
        print(f"\nverify 실패 {len(problems)}건:")
        for p in problems:
            print(f"  {p}")
        return 1
    if not args.message:
        print("verify 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
