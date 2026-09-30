"""판정 봉투: 모델과 무관한 JSON 입력·출력 형식(04_평가_명세 §0.3·§0.5, 계획서 §5.7).

봉투 하나 = 논문 하나. 판정자는 봉투 JSON만 읽고 답 JSON 하나를 쓴다. Claude 서브에이전트든 `codex exec`든 같은 봉투다.

봉투(`judge-envelope-v1`, 제품 이름도 넣지 않는다):
    {"format", "envelope_id": "env_<12 hex>", "task": <판정 지시문>, "rubric": {"A","B","C"},
     "plan": <그 논문의 계획서>, "reviews": [{"review_no": 1, "text": <공식 심사평 전문>}, ...],
     "risks": [{"risk_id": "k01", "text": "<제목 — 설명>"}, ...],     # 두 시스템·두 조건을 섞어 무작위 순서
     "answer_template": {...}}
답(`judge-answer-v1`):
    {"format", "envelope_id", "judge_id": "J1", "judge_model": "<실제 모델 id>",
     "judgments": [{"risk_id": "k01", "grade": "A"|"B"|"C", "review_no": <A면 심사평 번호, 아니면 null>, "reason": "<한 줄>"}]}

사전 고정(2026-09-30):
- 봉투 = 논문 i. 계획서 i, 논문 i의 공식 심사평 전문(작성 순, 메타리뷰·저자 답변 제외), 위험 = Neumann·일반 LLM의
  진짜 조건(계획서 i) 위험과 셔플 조건(계획서 j, 같은 분야) 위험. 셔플 위험도 계획서 i의 봉투에 섞여 들어가므로
  판정자는 어느 것이 셔플인지 모른다. 위험 순서는 `random.Random("20260933|<work_id>")`로 섞는다.
- 위험 id는 제시 순서(k01…), 봉투 id는 sha256("20260933|<work_id>") 앞 12자. 둘 다 시스템과 무관하다.
- 비밀 짝 표(어느 위험이 어느 시스템·조건·순위인지)는 봉투 폴더 밖 별도 파일(`judge_key/pairing.json`).
- 시스템명·근거 인용·원문 링크·카드 번호는 위험 묶음 단계(`backtest_riskset.blind_text`)에서 지우고, 여기서 한 번 더 검사해
  흔적이 있으면 봉투를 만들지 않는다(`blind_violations`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from eval.backtest_common import SEEDS, canonical_sha256, write_json
from eval.backtest_riskset import blind_residue

ENVELOPE_FORMAT = "judge-envelope-v1"
ANSWER_FORMAT = "judge-answer-v1"
KEY_FORMAT = "judge-key-v1"
GRADES = ("A", "B", "C")
MAX_REASON_CHARS = 200

RUBRIC = {
    "A": "적중: 이 논문의 실제 심사평에 같은 사안의 지적이 있다. 같은 사안 = 같은 대상(데이터·모델·평가·주장 등)과 "
         "같은 원인(없음·부족·부적절·오류)을 지적한다. 위험 유형만 같으면 A가 아니다.",
    "B": "타당: 심사평에는 없지만 이 계획서에 맞는 지적이다.",
    "C": "오탐: 이 계획서와 무관하거나 틀린 지적이다.",
}

TASK = """너는 연구계획서의 심사 위험 예측을 채점하는 판정자다.
이 봉투(JSON)에는 연구계획서(plan), 그 연구가 실제로 받은 심사평 전문(reviews), 예측된 위험 목록(risks)이 들어 있다.
위험들은 여러 출처에서 모아 무작위 순서로 섞었다. 출처를 추측하지 말고 위험 문장 자체만 보고 판정한다.

위험마다 A·B·C 중 하나를 고른다(rubric).
- A 적중: 실제 심사평에 같은 사안의 지적이 있다. 같은 사안은 같은 대상(데이터·모델·평가·주장 중 무엇)과 같은 원인(없음·부족·부적절·오류)을 지적하는 것이다. 표현은 달라도 된다. 위험 유형(예: "평가 문제")만 같으면 A가 아니다. A라면 그 지적이 있는 심사평 번호를 review_no에 적는다. 가리킬 문장을 찾을 수 없으면 A가 아니다.
- B 타당: 심사평에는 없지만 이 계획서에 맞는 지적이다.
- C 오탐: 이 계획서와 무관하거나, 계획서 내용을 잘못 읽은 틀린 지적이다.
예: 위험 "구성 요소별 기여를 분리하는 ablation 계획이 없다" ↔ 심사평 "모듈 하나만 뺀 비교가 필요하다" → A(같은 대상·같은 원인).
반례: 위험 "비교 대상이 오래됐다" ↔ 심사평 "비교 대상의 하이퍼파라미터 튜닝이 불공정하다" → A 아님(같은 유형, 다른 사안). 계획서에 맞으면 B.

규칙:
- 위험마다 따로 판정한다. 다른 위험과 비교해 등급을 나눠 주지 않는다. A의 개수에 할당량은 없다.
- reason은 한국어 한 줄(줄바꿈 없이 200자 이내)로 근거를 적는다.
- 이 봉투 밖의 파일(다른 판정자의 답, 짝 표, 다른 봉투)을 찾거나 읽지 않는다.
- 답은 answer_template과 같은 모양의 JSON 객체 하나다. risks의 모든 risk_id를 한 번씩, 빠짐없이 판정한다."""

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["format", "envelope_id", "judge_id", "judge_model", "judgments"],
    "properties": {
        "format": {"const": ANSWER_FORMAT},
        "envelope_id": {"type": "string"},
        "judge_id": {"type": "string"},
        "judge_model": {"type": "string"},
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["risk_id", "grade", "review_no", "reason"],
                "properties": {
                    "risk_id": {"type": "string"},
                    "grade": {"enum": list(GRADES)},
                    "review_no": {"type": ["integer", "null"]},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

# 봉투의 메타데이터(계획서·심사평·위험 글 밖)에 나오면 안 되는 말: 시스템·조건·짝 정보
META_FORBIDDEN = re.compile(
    r"neumann|노이만|baseline|기준선|일반\s*llm|astra|gpt|openai|shuffle|셔플|condition|system|rank|evidence|card|work_id|plan_work",
    re.I,
)
# 위험 글에 나오면 안 되는 말(시스템 이름). "baseline" 같은 일반어는 위험 내용일 수 있어 여기서는 뺀다.
RISK_FORBIDDEN = re.compile(r"neumann|노이만|gpt-6|astra|일반\s*LLM|baseline_llm|유사\s*(?:연구|논문)의?\s*심사평", re.I)
RISK_ID = re.compile(r"^k\d{2}$")
ENV_ID = re.compile(r"^env_[0-9a-f]{12}$")


def envelope_id_for(work_id: str, seed: int = SEEDS["envelope"]) -> str:
    return "env_" + hashlib.sha256(f"{seed}|{work_id}".encode()).hexdigest()[:12]


def answer_template(envelope_id: str, risk_ids: list[str]) -> dict[str, Any]:
    return {
        "format": ANSWER_FORMAT,
        "envelope_id": envelope_id,
        "judge_id": "<판정자 자리: J1|J2|J3>",
        "judge_model": "<실제 모델 id>",
        "judgments": [{"risk_id": r, "grade": "<A|B|C>", "review_no": None, "reason": "<한 줄>"} for r in risk_ids],
    }


def build_envelopes(
    sample: dict[str, Any],
    plans: dict[str, dict[str, Any]],
    reviews_by_work: dict[str, list[str]],
    risksets: Iterable[dict[str, Any]],
    *,
    seed: int = SEEDS["envelope"],
    work_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(봉투 목록, 비밀 짝 표). 위험 묶음은 work_id(판정 논문) 기준으로 모은다."""
    by_work: dict[str, list[dict[str, Any]]] = {}
    for rs in risksets:
        by_work.setdefault(rs["work_id"], []).append(rs)
    targets = work_ids or [it["work_id"] for it in sample["items"]]
    envelopes: list[dict[str, Any]] = []
    key: dict[str, Any] = {"format": KEY_FORMAT, "seed": seed, "envelopes": {}, "risksets": []}
    for wid in targets:
        items = []
        for rs in sorted(by_work.get(wid, []), key=lambda r: (r["system"], r["condition"])):
            key["risksets"].append({
                "work_id": wid, "system": rs["system"], "condition": rs["condition"], "plan_work_id": rs["plan_work_id"],
                "status": rs["status"], "generator": rs.get("generator"), "model": rs.get("model"),
                "n_risks": len(rs["risks"]), "evidence_ok": [bool(r.get("evidence_ok")) for r in rs["risks"]],
            })
            for r in rs["risks"]:
                items.append((r["text"], {"system": rs["system"], "condition": rs["condition"], "rank": r["rank"],
                                          "plan_work_id": rs["plan_work_id"], "evidence_ok": bool(r.get("evidence_ok"))}))
        rng = random.Random(f"{seed}|{wid}")
        rng.shuffle(items)
        env_id = envelope_id_for(wid, seed)
        risks = [{"risk_id": f"k{i:02d}", "text": text} for i, (text, _) in enumerate(items, 1)]
        env = {
            "format": ENVELOPE_FORMAT,
            "envelope_id": env_id,
            "task": TASK,
            "rubric": RUBRIC,
            "plan": plans[wid]["plan_text"],
            "reviews": [{"review_no": n, "text": t} for n, t in enumerate(reviews_by_work.get(wid, []), 1)],
            "risks": risks,
            "answer_template": answer_template(env_id, [r["risk_id"] for r in risks]),
        }
        problems = blind_violations(env)
        if problems:
            raise ValueError(f"{env_id}: 블라인드 위반 {problems}")
        envelopes.append(env)
        key["envelopes"][env_id] = {
            "work_id": wid,
            "sha256": canonical_sha256(env),
            "risks": {f"k{i:02d}": meta for i, (_, meta) in enumerate(items, 1)},
        }
    return envelopes, key


def blind_violations(env: dict[str, Any]) -> list[str]:
    """봉투에 시스템 흔적이 있는가. 빈 목록이면 통과."""
    p: list[str] = []
    if not ENV_ID.match(str(env.get("envelope_id", ""))):
        p.append("envelope_id 형식")
    allowed_keys = {"format", "envelope_id", "task", "rubric", "plan", "reviews", "risks", "answer_template"}
    extra = set(env) - allowed_keys
    if extra:
        p.append(f"허용 밖 키 {sorted(extra)}")
    meta = {k: v for k, v in env.items() if k not in ("plan", "reviews", "risks", "task", "rubric")}
    meta["risk_keys"] = sorted({k for r in env.get("risks", []) for k in r})
    meta["review_keys"] = sorted({k for r in env.get("reviews", []) for k in r})
    meta_text = json.dumps(meta, ensure_ascii=False)
    if META_FORBIDDEN.search(meta_text):
        p.append(f"메타데이터에 시스템 흔적: {META_FORBIDDEN.search(meta_text).group(0)!r}")
    if META_FORBIDDEN.search(env.get("task", "") + json.dumps(env.get("rubric", {}), ensure_ascii=False)):
        p.append("지시문에 시스템 흔적")
    for r in env.get("risks", []):
        if set(r) != {"risk_id", "text"}:
            p.append(f"{r.get('risk_id')}: 위험 키 {sorted(r)}")
        if not RISK_ID.match(str(r.get("risk_id", ""))):
            p.append(f"risk_id 형식 {r.get('risk_id')!r}")
        text = str(r.get("text", ""))
        if RISK_FORBIDDEN.search(text):
            p.append(f"{r.get('risk_id')}: 시스템 이름 {RISK_FORBIDDEN.search(text).group(0)!r}")
        res = blind_residue(text)
        if res:
            p.append(f"{r.get('risk_id')}: 흔적 {res}")
    return p


def save_envelopes(envelopes: list[dict[str, Any]], key: dict[str, Any], env_dir: Path, key_path: Path) -> dict[str, Any]:
    """봉투는 env_dir/<envelope_id>.json, 목록은 env_dir/manifest.json(시스템 정보 없음), 짝 표는 key_path."""
    env_dir = Path(env_dir)
    if Path(key_path).resolve().parent == env_dir.resolve():
        raise ValueError("짝 표를 봉투 폴더에 두지 않는다")
    files = {}
    for env in envelopes:
        files[env["envelope_id"]] = write_json(env_dir / f"{env['envelope_id']}.json", env)
    manifest = {"format": ENVELOPE_FORMAT + "-manifest", "n": len(envelopes),
                "envelopes": [{"envelope_id": e, "file": f"{e}.json", "sha256": s} for e, s in files.items()],
                "n_risks": sum(len(e["risks"]) for e in envelopes)}
    write_json(env_dir / "manifest.json", manifest)
    write_json(Path(key_path), key)
    return manifest


# ── 대표 블라인드 판정(사람) ──────────────────────────────────────────────


def human_envelope(env: dict[str, Any], key: dict[str, Any], condition: str = "real") -> dict[str, Any]:
    """사람 판정용: 진짜 조건 위험만 남긴 사본(위험 id·순서는 그대로)."""
    meta = key["envelopes"][env["envelope_id"]]["risks"]
    keep = [r for r in env["risks"] if meta[r["risk_id"]]["condition"] == condition]
    out = dict(env, risks=keep, answer_template=answer_template(env["envelope_id"], [r["risk_id"] for r in keep]))
    return out


def render_markdown(env: dict[str, Any]) -> str:
    lines = [f"# 판정 봉투 {env['envelope_id']}", "", "## 판정 방법", "", env["task"], "", "## 연구계획서", "", env["plan"], "",
             "## 실제 심사평"]
    for r in env["reviews"]:
        lines += ["", f"### 심사평 {r['review_no']}", "", r["text"]]
    lines += ["", "## 위험(각각 A·B·C)", ""]
    for r in env["risks"]:
        lines += [f"- **{r['risk_id']}** {r['text']}", "  - 등급: ___  심사평 번호(A면): ___  이유: ___"]
    return "\n".join(lines) + "\n"


def human_answer_sheet(envs: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["envelope_id", "risk_id", "grade", "review_no", "reason"])
    for env in envs:
        for r in env["risks"]:
            w.writerow([env["envelope_id"], r["risk_id"], "", "", ""])
    return buf.getvalue()


def read_human_answers(path: Path) -> dict[tuple[str, str], str]:
    """대표 답 CSV → {(envelope_id, risk_id): grade}. 빈 칸·잘못된 등급은 오류."""
    out: dict[tuple[str, str], str] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh), 2):
            g = (row.get("grade") or "").strip().upper()
            if g not in GRADES:
                raise ValueError(f"{path}:{i}: 등급 {g!r}")
            out[(row["envelope_id"].strip(), row["risk_id"].strip())] = g
    return out


__all__ = [
    "ANSWER_FORMAT",
    "ANSWER_SCHEMA",
    "ENVELOPE_FORMAT",
    "GRADES",
    "KEY_FORMAT",
    "RUBRIC",
    "TASK",
    "answer_template",
    "blind_violations",
    "build_envelopes",
    "envelope_id_for",
    "human_answer_sheet",
    "human_envelope",
    "read_human_answers",
    "render_markdown",
    "save_envelopes",
]
