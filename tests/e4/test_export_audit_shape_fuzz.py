"""B2: expected_review.audit 형태 퍼징 — 내보내기는 어떤 audit 형태에도 500을 내지 않는다.

정책(export.py `_sanitize_audit`·`package_limit_refusal`):
- audit 자체가 객체가 아니면 422(기존 정책).
- 알려진 필드는 형태를 확인한 값만 싣고, 틀린 형태·모르는 필드는 값을 버리고 이름만 audit.dropped_keys에 남긴다.
- 요청 JSON 중첩이 MAX_PACKAGE_JSON_DEPTH단을 넘으면 조립 전에 422(package_limits).
mock·오프라인. 실제 API 호출 없음.
"""

from __future__ import annotations

import copy
import io
import json
import math
import random
import zipfile
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import export
from neumann.api.signing import sign_result
from tests.fixtures.loader import load_fixtures

COUNT_KEYS = {"gen", "pass", "drop", "no_evidence", "generated", "passed"}
TEXT_KEYS = {"gate", "note", "dropped_text"}
MAP_KEYS = {"dropped_reasons", "reasons"}
LIST_KEYS = {"no_evidence_reasons", "dropped_keys"}
ALLOWED_OUT = COUNT_KEYS | TEXT_KEYS | MAP_KEYS | LIST_KEYS | {"linked_rate"}
FUZZ_KEYS = sorted(ALLOWED_OUT | {"dropped", "dropped_detail", "zzz", "x" * 200, "메모", "a@b.example"})
SENTINEL = "VAL#SENTINEL#"  # 코드 모양이 아니다('#'). 버린 값이 ZIP 어디에도 나오면 실패
N_CASES = 300


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(export.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def base() -> dict[str, Any]:
    return load_fixtures().premortem_result.model_dump(mode="json")


def _unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist()}


def _report_review(files: dict[str, bytes]) -> dict[str, Any]:
    """neumann_report.md의 예상 심사평 JSON 블록을 읽는다(\\u003c 등 이스케이프는 json이 되돌린다)."""
    report = files["neumann_report.md"].decode("utf-8")
    section = report.split("## 예상 심사평", 1)[1]
    block = section.split("```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(block)


def _deep(depth: int, leaf: Any) -> Any:
    value = leaf
    for i in range(depth):
        value = [value] if i % 2 else {"k": value}
    return value


def _value(rng: random.Random, i: int, level: int = 0) -> Any:
    """중첩 dict/list/int/str/None/거대 값 조합. 문자열 표식은 컨테이너 안에만 넣는다."""
    kind = rng.randrange(16 if level < 3 else 11)
    if kind == 11:
        return [_value(rng, i, level + 1) for _ in range(rng.randint(0, 3))] + [f"{SENTINEL}{i}"]
    if kind == 12:
        return {f"{SENTINEL}{i}": _value(rng, i, level + 1), "missing_citation": _value(rng, i, level + 1)}
    if kind == 13:
        return [["missing_citation", f"{SENTINEL}{i}"], [f"{SENTINEL}{i}", "x"], 1, [], {"reason": f"{SENTINEL}{i}"}]
    if kind == 14:
        return _deep(rng.choice([10, 40, 70, 300]), [f"{SENTINEL}{i}"])
    if kind == 15:
        return [f"{SENTINEL}{i}"] * rng.choice([2, 5_000])
    return [None, 0, -1, True, 1.5, 10 ** rng.choice([9, 10, 30, 300]), "missing_citation", "s" * 50_000,
            float("inf"), [], {}][kind]


def _case(rng: random.Random, base: dict[str, Any], i: int) -> tuple[dict[str, Any], Any]:
    data = copy.deepcopy(base)
    if rng.random() < 0.05:
        audit: Any = rng.choice([1, [1], "audit", True, [["missing_citation", "x"]]])
    else:
        audit = {k: _value(rng, i) for k in rng.sample(FUZZ_KEYS, rng.randint(1, 6))}
        if rng.random() < 0.3:  # 정상 필드와 섞는다
            audit.update({"gen": 3, "pass": 1, "drop": 2, "gate": "grounding@v1"})
    review: dict[str, Any] = {"audit": audit}
    if rng.random() < 0.5:  # 근거 게이트가 문장을 빼는 경로(감사 기록 갱신)도 돈다
        review["weakness"] = [{"t": "근거 없는 문장", "c": []}, "형식이 틀린 문장"]
    data["expected_review"] = review
    body: dict[str, Any] = {"result": data}
    if rng.random() < 0.5:
        try:
            body["result_sig"] = sign_result(data)
        except Exception:  # noqa: BLE001 - 계약상 서명할 수 없는 값(inf 등)은 서명 없이 보낸다
            pass
    return body, audit


def _post_raw(client: TestClient, body: dict[str, Any]):
    """httpx json=은 inf·NaN을 거부한다. 실제 클라이언트처럼 Infinity 토큰까지 원문 바이트로 보낸다."""
    return client.post("/premortem/package", content=json.dumps(body).encode(),
                       headers={"content-type": "application/json"})


def _assert_shape(audit: dict[str, Any]) -> None:
    assert set(audit) <= ALLOWED_OUT, set(audit) - ALLOWED_OUT
    for key, value in audit.items():
        if key in COUNT_KEYS:
            assert type(value) is int and 0 <= value <= export.AUDIT_MAX_COUNT, key
        elif key in TEXT_KEYS:
            assert isinstance(value, str) and len(value) <= export.AUDIT_MAX_TEXT_CHARS, key
        elif key in MAP_KEYS:
            assert isinstance(value, dict) and len(value) <= export.AUDIT_MAX_CODES, key
            assert all(isinstance(k, str) and len(k) <= 64 and type(n) is int for k, n in value.items()), key
        elif key in LIST_KEYS:
            assert isinstance(value, list) and all(isinstance(x, str) and len(x) <= 64 for x in value), key
        else:
            assert value is None or (isinstance(value, float | int) and math.isfinite(value) and 0 <= value <= 1)


def test_reported_nested_dropped_reasons_int_list_no_longer_500(client, base):
    """재현: audit.dropped_reasons가 1·[1]이고 drop이 있으면 이전에는 HTTP 500(TypeError)."""
    for bad in (1, [1], "abc", {"missing_citation": "x"}, {"a b": 1}):
        data = copy.deepcopy(base)
        data["expected_review"]["audit"] = {"drop": 1, "dropped_reasons": bad}
        response = client.post("/premortem/package", json={"result": data, "result_sig": sign_result(data)})
        assert response.status_code == 200, (bad, response.text[:200])
        assert response.headers["x-neumann-result-origin"] == "server_signed"
        files = _unzip(response.content)
        audit = _report_review(files)["audit"]
        assert audit["dropped_keys"] == ["dropped_reasons"] and audit["dropped_reasons"] == {}
        assert audit["drop"] == 1
        assert "audit.dropped_keys" in files["neumann_report.md"].decode("utf-8")  # 주의 문구


@pytest.mark.parametrize("dropped", [5, "x", {"a": 1}, [[{"deep": 1}, "x"]]])
def test_nested_dropped_not_list_or_bad_pair_no_500(client, base, dropped):
    data = copy.deepcopy(base)
    data["expected_review"]["audit"] = {"drop": 1, "dropped": dropped}
    response = client.post("/premortem/package", json={"result": data})
    assert response.status_code == 200, response.text[:200]
    assert "dropped" in _report_review(_unzip(response.content))["audit"]["dropped_keys"]


def test_valid_pipeline_audit_preserved_without_dropped_keys(client, base):
    audit = {"gen": 4, "pass": 2, "drop": 2, "no_evidence": 1, "gate": "grounding@v1", "linked_rate": 0.5,
             "reasons": {"missing_citation": 1, "fabricated_number": 1},
             "dropped": [["missing_citation", "빠진 문장 원문"], ["fabricated_number", "R² 0.9"]],
             "dropped_detail": [{"reason": "missing_citation", "text": "빠진 문장 원문"}]}
    data = copy.deepcopy(base)
    data["expected_review"]["audit"] = audit
    response = client.post("/premortem/package", json={"result": data, "result_sig": sign_result(data)})
    assert response.status_code == 200
    files = _unzip(response.content)
    out = _report_review(files)["audit"]
    assert "dropped_keys" not in out
    assert {k: out[k] for k in ("gen", "pass", "drop", "no_evidence", "gate", "linked_rate", "reasons")} == {
        k: audit[k] for k in ("gen", "pass", "drop", "no_evidence", "gate", "linked_rate", "reasons")}
    assert out["dropped_reasons"] == {"missing_citation": 1, "fabricated_number": 1}
    assert not any("빠진 문장 원문" in blob.decode("utf-8", "replace") for blob in files.values())
    assert "audit.dropped_keys" not in files["neumann_report.md"].decode("utf-8")
    # 두 번 거쳐도 같은 모양(리포트 렌더링이 게이트 결과를 다시 읽는다)
    again, dropped = export._review_for_report_with_drops({"audit": out})
    assert dropped == [] and again["audit"] == out


def test_json_depth_guard_boundary_and_serving_hook(client, base):
    assert not export.json_depth_exceeds(_deep(export.MAX_PACKAGE_JSON_DEPTH - 1, 1))
    assert export.json_depth_exceeds(_deep(export.MAX_PACKAGE_JSON_DEPTH + 1, 1))
    assert not export.json_depth_exceeds({"result": base})
    data = copy.deepcopy(base)
    data["expected_review"] = {"audit": {}, "zzz": _deep(80, 1)}
    refusal = export.package_limit_refusal({"result": data})  # 서빙 미들웨어도 같은 함수를 부른다
    assert refusal is not None and refusal[:2] == (422, "package_limits")
    # 앱 파서는 받지만 이전에는 리포트 JSON 직렬화에서 RecursionError → 500이던 깊이
    data["expected_review"] = {"audit": {"zzz": "__DEEP__"}}
    raw = json.dumps({"result": data}).replace('"__DEEP__"', "[" * 1500 + "1" + "]" * 1500)
    response = client.post("/premortem/package", content=raw.encode(), headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "package_limits"


def test_audit_shape_fuzz_300_no_500(client, base):
    rng = random.Random(20261001)
    statuses: dict[int, int] = {}
    dropped_cases = depth_refusals = root_refusals = gate_path = 0
    for i in range(N_CASES):
        body, audit = _case(rng, base, i)
        response = _post_raw(client, body)
        statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
        assert response.status_code != 500, (i, response.text[:200])
        too_deep = export.json_depth_exceeds(body)
        if not isinstance(audit, dict):
            root_refusals += 1
            assert response.status_code == 422, (i, response.text[:200])
            continue
        if too_deep:
            depth_refusals += 1
            assert response.status_code == 422 and response.json()["detail"]["error_code"] == "package_limits"
            continue
        assert response.status_code == 200, (i, response.text[:300])
        files = _unzip(response.content)
        out = _report_review(files)["audit"]
        _assert_shape(out)
        names = set(out.get("dropped_keys", []))
        dropped_cases += bool(names)
        gate_path += "weakness" in body["result"]["expected_review"]
        for key, value in audit.items():
            if key == "dropped_detail":
                continue
            if key == "dropped":
                if value is not None and not isinstance(value, list):
                    assert "dropped" in names, i
                continue
            if key not in out:
                assert export._audit_key_name(key) in names, (i, key)
        for name, blob in files.items():
            assert SENTINEL not in blob.decode("utf-8", "replace"), (i, name)
    assert statuses.get(500, 0) == 0 and sum(statuses.values()) == N_CASES
    # 퍼징이 실제로 각 경로를 지나갔는지(항상 통과하는 검사가 아니게)
    assert dropped_cases >= 100 and depth_refusals >= 5 and root_refusals >= 5 and gate_path >= 50, (
        statuses, dropped_cases, depth_refusals, root_refusals, gate_path)
