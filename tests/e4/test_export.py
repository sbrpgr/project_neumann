"""내보내기 패키지(ZIP 9파일) — E4-L2a.

fixture 결과로 ZIP을 만들어: 9파일, manifest sha256, 인용 = evidence = 원문[start:end], 카드 0장·강등 처리,
생성 방식 정직 표기, 계획서 마스킹, 결정적 출력, API 라우트를 잰다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import types
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export
from neumann.api.export import FILE_NAMES, build_package, build_package_files, router
from neumann.models import PremortemResult, sha256_text
from tests.fixtures.loader import load_fixtures, plan_text

EXPECTED_FILES = [
    "README.md",
    "manifest.json",
    "risk_cards.json",
    "evidence_pack.json",
    "similar_works.csv",
    "plan_annotated.md",
    "neumann_report.md",
    "ai_context.md",
    "decision_log.json",
]
T1 = datetime(2026, 9, 30, 10, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 30, 11, 30, 0, tzinfo=UTC)


def fixture_result() -> PremortemResult:
    return load_fixtures().premortem_result


def variant(**changes: Any) -> PremortemResult:
    """fixture 결과를 dict로 바꿔 고친 뒤 다시 검증한다(불변식·status 자동 강등이 다시 돈다)."""
    data = fixture_result().model_dump(mode="json")
    data.update(changes)
    return PremortemResult.model_validate(data)


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        return {info.filename: zf.read(info) for info in zf.infolist()}


def text(files: dict[str, bytes], name: str) -> str:
    return files[name].decode("utf-8")


def as_json(files: dict[str, bytes], name: str) -> Any:
    return json.loads(files[name].decode("utf-8"))


# ── 9파일·manifest ────────────────────────────────────────────────────────


def test_zip_has_exactly_nine_files_in_order() -> None:
    files = unzip(build_package(fixture_result()))
    assert list(files) == EXPECTED_FILES
    assert list(FILE_NAMES) == EXPECTED_FILES
    assert all(len(b) > 0 for b in files.values())


def test_manifest_sha256_and_sizes_match_zip_members() -> None:
    files = unzip(build_package(fixture_result()))
    manifest = as_json(files, "manifest.json")
    listed = [f["path"] for f in manifest["files"]]
    assert listed == [n for n in EXPECTED_FILES if n != "manifest.json"]
    for entry in manifest["files"]:
        data = files[entry["path"]]
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), entry["path"]
        assert entry["bytes"] == len(data), entry["path"]
    assert manifest["schema_version"] == "1"
    assert manifest["cards_by_generator"] == {"astra": 0, "rule": 0, "mock": 2}
    assert manifest["counts"]["risk_cards"] == 2
    assert manifest["counts"]["evidence"] == 8
    assert manifest["result"]["plan_id"] == fixture_result().plan_id
    assert datetime.fromisoformat(manifest["created_at"]).tzinfo is not None


def test_manifest_detects_tampering() -> None:
    """manifest 해시가 실제로 내용을 가리키는지: 한 글자 바꾸면 불일치."""
    files = unzip(build_package(fixture_result()))
    manifest = as_json(files, "manifest.json")
    entry = next(f for f in manifest["files"] if f["path"] == "risk_cards.json")
    tampered = files["risk_cards.json"].replace(b"card-fx-leak", b"card-fx-lEak", 1)
    assert hashlib.sha256(tampered).hexdigest() != entry["sha256"]


# ── 근거 인용 ─────────────────────────────────────────────────────────────


def test_evidence_pack_quotes_equal_evidence_and_source_slice() -> None:
    fx = load_fixtures()
    result = fixture_result()
    by_id = {ex.excerpt_id: ex for ex in result.evidence}
    files = unzip(build_package(result))
    pack = as_json(files, "evidence_pack.json")

    assert pack["reverification"]["status"] == "not_reverified"
    assert [c["card_id"] for c in pack["cards"]] == [c.card_id for c in result.risk_cards]
    n = 0
    for card_json, card in zip(pack["cards"], result.risk_cards, strict=True):
        assert [e["excerpt_id"] for e in card_json["evidence"]] == card.evidence
        for e in card_json["evidence"]:
            ex = by_id[e["excerpt_id"]]
            assert e["text"] == ex.text
            assert (e["start"], e["end"], e["source_url"]) == (ex.start, ex.end, ex.source_url)
            assert e["text_sha256"] == sha256_text(e["text"]) == ex.text_sha256
            source = fx.source_text(ex)  # fixture 원문을 다시 잘라 글자 단위로 대조
            assert source[e["start"] : e["end"]] == e["text"]
            assert e["source_sha256"] == sha256_text(source)
            assert e["source_url"].startswith("https://")
            n += 1
    assert n == 8
    assert pack["unlinked_evidence"] == []


def test_report_and_ai_context_quote_evidence_verbatim() -> None:
    result = fixture_result()
    files = unzip(build_package(result))
    report = text(files, "neumann_report.md")
    ai = text(files, "ai_context.md")
    for ex in result.evidence:
        assert f"> {ex.text}" in report, ex.excerpt_id
        assert ex.source_url in report
        assert ex.excerpt_id in ai
        assert json.dumps(ex.text, ensure_ascii=False) in ai
    for card in result.risk_cards:
        assert card.card_id in report and card.card_id in ai


def test_risk_cards_json_round_trips_to_contract() -> None:
    result = fixture_result()
    files = unzip(build_package(result))
    cards = as_json(files, "risk_cards.json")["risk_cards"]
    assert cards == [c.model_dump(mode="json") for c in result.risk_cards]


def test_similar_works_csv() -> None:
    result = fixture_result()
    files = unzip(build_package(result))
    raw = files["similar_works.csv"]
    assert raw.startswith(b"\xef\xbb\xbf")  # 엑셀용 BOM
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert [r["work_id"] for r in rows] == [w.work_id for w in result.similar_works]
    assert rows[0]["rank"] == "1" and float(rows[0]["similarity"]) == pytest.approx(0.82)
    assert rows[0]["cited_by_cards"] == "card-fx-leak;card-fx-seed"
    assert rows[1]["cited_by_cards"] == "card-fx-leak"


# ── 계획서 주석·마스킹 ───────────────────────────────────────────────────


def test_plan_annotated_marks_card_lines() -> None:
    files = unzip(build_package(fixture_result()))
    md = text(files, "plan_annotated.md")
    assert "16 [C1] | We randomly split the dataset into 80/10/10 train/validation/test sets." in md
    assert "17 [C1] | 조성이 거의 동일한" in md
    assert "22 [C2] | We do not report error bars" in md
    assert "21      | holdout test set" in md  # 카드 없는 줄은 표시 없이
    assert "| C1 | `card-fx-leak` | R3 데이터 누출·분할 오염 |" in md


def test_plan_annotated_without_plan_lists_line_numbers_only() -> None:
    result = variant(plan=None)
    files = unzip(build_package(result))
    md = text(files, "plan_annotated.md")
    assert "줄 번호만" in md
    assert "| 16 | C1 |" in md and "| 17 | C1 |" in md and "| 22 | C2 |" in md
    assert "We randomly split" not in md  # 본문은 없다
    assert as_json(files, "manifest.json")["counts"]["plan_lines"] is None


def test_plan_text_is_masked_when_result_has_no_plan() -> None:
    body = plan_text("plan.md") + "\n문의: researcher.kim@example.ac.kr / ORCID 0000-0002-1825-0097\n"
    result = variant(plan=None)
    data = build_package(result, plan_text=body)
    assert b"researcher.kim@example.ac.kr" not in data
    files = unzip(data)
    for name, content in files.items():
        assert b"researcher.kim@example.ac.kr" not in content, name
        assert b"0000-0002-1825-0097" not in content, name
    md = text(files, "plan_annotated.md")
    assert "[EMAIL]" in md and "[ORCID]" in md
    assert "16 [C1] | We randomly split" in md
    manifest = as_json(files, "manifest.json")
    assert manifest["plan_source"].startswith("plan_text")
    assert manifest["warnings"]  # 본문 해시가 결과 plan_id와 달라진 것을 알린다


def test_plan_text_matching_result_has_no_warning() -> None:
    files = unzip(build_package(variant(plan=None), plan_text=plan_text("plan.md")))
    assert as_json(files, "manifest.json")["warnings"] == []


def test_package_contains_no_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = "neumann-fake-value-for-leak-test-7c1f2e"
    monkeypatch.setenv("OPENAI_API_KEY", fake)
    monkeypatch.setenv("NEUMANN_PSEUDONYM_SALT", fake + "-salt")
    data = build_package(fixture_result())
    for content in unzip(data).values():
        assert fake.encode() not in content


# ── 카드 0장·강등·생성 방식 ───────────────────────────────────────────────


def test_zero_cards_does_not_crash_and_states_reason() -> None:
    reason = "입력이 연구계획서로 보이지 않는다(검색 최고 유사도 0.12 < 하한 0.45)"
    result = variant(risk_cards=[], evidence=[], similar_works=[], notices=[reason])
    files = unzip(build_package(result))
    assert list(files) == EXPECTED_FILES
    readme = text(files, "README.md")
    report = text(files, "neumann_report.md")
    assert "위험카드 0장" in readme and reason in readme
    assert "위험카드 0장" in report and reason in report
    assert "카드 0장" in text(files, "ai_context.md")
    assert as_json(files, "decision_log.json")["decisions"] == []
    assert as_json(files, "risk_cards.json")["risk_cards"] == []
    assert as_json(files, "evidence_pack.json")["cards"] == []
    rows = list(csv.reader(io.StringIO(files["similar_works.csv"].decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0][0] == "rank"  # 머리행만
    assert as_json(files, "manifest.json")["cards_by_generator"] == {"astra": 0, "rule": 0, "mock": 0}


def test_zero_cards_without_any_reason_says_so() -> None:
    result = variant(risk_cards=[], evidence=[], notices=[])
    readme = text(unzip(build_package(result)), "README.md")
    assert "결과에 따로 적힌 사유는 없다" in readme


def test_degraded_stages_and_rule_cards_are_labelled_honestly() -> None:
    base = fixture_result().model_dump(mode="json")
    cards = base["risk_cards"]
    cards[0]["generator"] = "rule"
    cards[1]["generator"] = "astra"
    cards[1]["model"] = "gpt-6.1-sol"
    stages = base["stages"]
    stages[1].update(status="degraded", reason="astra 호출 시간 초과 → 규칙 태거", impl="fallback:rule_tagger")
    stages[2].update(status="error", reason="카드 합성 스키마 검증 실패")
    result = variant(risk_cards=cards, stages=stages)
    assert result.status == "degraded"  # 계약이 자동으로 강등한다

    files = unzip(build_package(result))
    readme = text(files, "README.md")
    report = text(files, "neumann_report.md")
    for doc in (readme, report):
        assert "**degraded**" in doc
        assert "LLM 호출 시간 초과 → 규칙 태거" in doc  # 계약 이름 astra는 사람용 문서에서 LLM(DISP-1)
        assert "카드 합성 스키마 검증 실패" in doc
        assert "**비상 규칙** 1장: 규칙(비상 경로" in doc and "LLM 결과가 아니다" in doc
        assert "**LLM (gpt-6.1-sol)** 1장: 제품 LLM(OpenAI, 모델은 manifest 참조)" in doc
    assert "- C1 `card-fx-leak` — 비상 규칙" in readme
    assert "- C2 `card-fx-seed` — LLM (gpt-6.1-sol)" in readme
    assert "| extract | degraded | fallback:rule_tagger |" in readme
    assert "| cards | error |" in readme
    # 규칙 카드를 LLM 카드로 적지 않는다
    rule_line = next(ln for ln in report.splitlines() if "카드 `card-fx-leak`" in ln)
    assert "비상 규칙" in rule_line and "LLM" not in rule_line and "astra" not in rule_line
    manifest = as_json(files, "manifest.json")
    assert manifest["cards_by_generator"] == {"astra": 1, "rule": 1, "mock": 0}
    assert [s["name"] for s in manifest["not_ok_stages"]] == ["extract", "cards"]
    ai = text(files, "ai_context.md")
    assert "생성: 비상 규칙" in ai and "정상이 아닌 단계: extract: degraded" in ai


def test_status_error_without_cards() -> None:
    stages = [{"name": "pipeline", "status": "error", "reason": "분석 파이프라인 미연결", "phase": "api"}]
    result = variant(risk_cards=[], evidence=[], stages=stages, status="error", notices=[])
    files = unzip(build_package(result))
    readme = text(files, "README.md")
    assert "**error**" in readme
    assert "분석이 오류로 끝났다(status=error)" in readme
    assert "pipeline: error — 분석 파이프라인 미연결" in readme


# ── 결정 로그 ─────────────────────────────────────────────────────────────


def test_decision_log_records_and_masks() -> None:
    decisions = [
        {"card_id": "card-fx-leak", "decision": "채택", "note": "scaffold split 추가. 문의 a.b@lab.org"},
        {"card_id": "card-fx-seed", "decision": "hold"},
    ]
    files = unzip(build_package(fixture_result(), decisions=decisions))
    log = as_json(files, "decision_log.json")
    assert [d["decision"] for d in log["decisions"]] == ["adopt", "hold"]
    assert log["decisions"][0]["note"] == "scaffold split 추가. 문의 [EMAIL]"
    assert log["choices"] == {"adopt": "채택", "hold": "보류", "reject": "기각"}
    assert "`card-fx-leak`: 채택" in text(files, "neumann_report.md")


def test_decision_log_rejects_unknown_card_and_identity_fields() -> None:
    with pytest.raises(ValueError, match="card_id"):
        build_package(fixture_result(), decisions=[{"card_id": "nope", "decision": "adopt"}])
    with pytest.raises(ValueError):
        build_package(fixture_result(), decisions=[{"card_id": "card-fx-leak", "decision": "adopt", "reviewer_name": "x"}])
    with pytest.raises(ValueError):
        build_package(fixture_result(), decisions=[{"decision": "adopt"}])  # 대상 없음
    with pytest.raises(ValueError):
        build_package(fixture_result(), decisions=[{"card_id": "card-fx-leak", "decision": "maybe"}])
    with pytest.raises(ValueError, match="item_id"):
        build_package(fixture_result(), decisions=[{"item_id": "A9", "decision": "adopt"}])  # 체크리스트에 없음


def test_checklist_items_render_and_accept_item_decisions() -> None:
    cards = {c.card_id: c for c in fixture_result().risk_cards}
    checklist = [
        {"id": "A1", "text": "scaffold 기반 분할 추가", "card_id": "card-fx-leak", "plan_lines": [16], "generator": "rule",
         "evidence": cards["card-fx-leak"].evidence[:1]},
        {"id": "A2", "t": "5회 반복 실험 평균±표준편차 보고", "r": "R2", "s": "보류", "m": "GPU 예산 확인",
         "card_id": "card-fx-seed", "evidence": cards["card-fx-seed"].evidence[:1]},
    ]
    result = variant(checklist=checklist)
    decisions = [{"item_id": "A2", "card_id": "card-fx-seed", "decision": "보류", "note": "GPU 예산 확인 후"}]
    files = unzip(build_package(result, decisions=decisions))
    report = text(files, "neumann_report.md")
    assert "- [A1] scaffold 기반 분할 추가 (카드 card-fx-leak · 계획서 줄 16 · 생성 비상 규칙)" in report
    assert "- [A2] 5회 반복 실험 평균±표준편차 보고 (R2 · 카드 card-fx-seed) — 결정: 보류 — GPU 예산 확인" in report
    assert "카드 `card-fx-seed` · 행동 `A2`: 보류 — GPU 예산 확인 후" in report
    log = as_json(files, "decision_log.json")
    assert log["checklist_item_ids"] == ["A1", "A2"]
    assert log["decisions"][0]["item_id"] == "A2" and log["decisions"][0]["decision"] == "hold"


# ── 결정성 ────────────────────────────────────────────────────────────────


def test_deterministic_output_except_created_at() -> None:
    a = build_package_files(fixture_result(), created_at=T1)
    b = build_package_files(fixture_result(), created_at=T2)
    for name in EXPECTED_FILES:
        if name != "manifest.json":
            assert a[name] == b[name], name
    ma, mb = json.loads(a["manifest.json"]), json.loads(b["manifest.json"])
    assert ma.pop("created_at") == "2026-09-30T10:00:00Z"
    assert mb.pop("created_at") == "2026-09-30T11:30:00Z"
    assert ma == mb
    # 같은 created_at이면 ZIP 바이트 전체가 같다
    assert build_package(fixture_result(), created_at=T1) == build_package(fixture_result(), created_at=T1)
    # 기본값(지금)으로 두 번 만들어도 manifest 밖은 같다
    c, d = unzip(build_package(fixture_result())), unzip(build_package(fixture_result()))
    assert {k: v for k, v in c.items() if k != "manifest.json"} == {k: v for k, v in d.items() if k != "manifest.json"}


def test_different_input_changes_output() -> None:
    """결정성 검사가 항상 통과하는 검사가 아님을 보인다: 입력이 바뀌면 파일도 바뀐다."""
    a = build_package_files(fixture_result(), created_at=T1)
    b = build_package_files(variant(notices=["다른 알림"]), created_at=T1)
    assert a["README.md"] != b["README.md"]
    assert a["risk_cards.json"] == b["risk_cards.json"]


# ── API ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_package_from_result(client: TestClient) -> None:
    body = {"result": fixture_result().model_dump(mode="json")}
    resp = client.post("/premortem/package", json=body)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"] and ".zip" in resp.headers["content-disposition"]
    assert resp.headers["x-neumann-status"] == "ok"
    assert resp.headers["x-neumann-cards"] == "2"
    files = unzip(resp.content)
    assert list(files) == EXPECTED_FILES
    manifest = as_json(files, "manifest.json")
    for entry in manifest["files"]:
        assert entry["sha256"] == hashlib.sha256(files[entry["path"]]).hexdigest()


def test_api_accepts_bare_result_and_decisions(client: TestClient) -> None:
    resp = client.post("/premortem/package", json=fixture_result().model_dump(mode="json"))
    assert resp.status_code == 200
    body = {
        "result": fixture_result().model_dump(mode="json"),
        "decisions": [{"card_id": "card-fx-seed", "decision": "기각"}],
    }
    resp = client.post("/premortem/package", json=body)
    assert resp.status_code == 200
    assert as_json(unzip(resp.content), "decision_log.json")["decisions"][0]["decision"] == "reject"


def test_api_rejects_bad_input(client: TestClient) -> None:
    assert client.post("/premortem/package", json={}).status_code == 422
    assert client.post("/premortem/package", json={"plan_text": "   "}).status_code == 422
    broken = fixture_result().model_dump(mode="json")
    broken["risk_cards"][0]["evidence"] = ["ex_does_not_exist"]
    assert client.post("/premortem/package", json={"result": broken}).status_code == 422
    body = {"result": fixture_result().model_dump(mode="json"), "decisions": [{"card_id": "nope", "decision": "adopt"}]}
    assert client.post("/premortem/package", json=body).status_code == 422
    assert client.post("/premortem/package", json={"result": {}, "extra": 1}).status_code == 422


def test_api_plan_text_only_is_rejected_without_running_pipeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-1 S-02: plan_text만 오면 파이프라인을 돌리지 않고 422 + 사용자 문구(내보내기는 결과만 받는다)."""
    calls: list[str] = []

    def fake_run_premortem(text_in: str, *, session_id: str | None = None) -> PremortemResult:
        calls.append(text_in)
        return fixture_result()

    module = types.ModuleType("neumann.pipeline")
    module.run_premortem = fake_run_premortem  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "neumann.pipeline", module)
    resp = client.post("/premortem/package", json={"plan_text": plan_text("plan.md")})
    assert resp.status_code == 422
    assert calls == []
    assert "분석 결과가 필요합니다" in resp.text
    assert "We randomly split" not in resp.text  # 입력을 되돌려 보내지 않는다
    assert not hasattr(export, "_run_pipeline")  # 파이프라인 실행 경로 자체가 없다


def test_api_result_with_plan_text_still_packages(client: TestClient) -> None:
    """result가 있으면 plan_text는 계획서 줄 번호용으로만 쓴다(파이프라인 실행 없음)."""
    body = {"result": variant(plan=None).model_dump(mode="json"), "plan_text": plan_text("plan.md")}
    resp = client.post("/premortem/package", json=body)
    assert resp.status_code == 200
    assert "16 [C1] | We randomly split" in text(unzip(resp.content), "plan_annotated.md")
