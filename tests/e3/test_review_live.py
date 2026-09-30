"""실제 astra로 예상 심사평 1회 생성 (E3-L1a 완료 기준 2). `NEUMANN_LIVE_TESTS=1`일 때만 돈다.

E3-L0의 llm.py가 main에 없을 때를 위한 **임시 llm_call**: openai SDK를 직접 부른다(과제 지시문이 허락).
키는 SDK가 환경변수에서 읽는다. 키·헤더를 출력하지 않는다. 결과 JSON은 `-s`로 돌리면 표준 출력에 나온다.

    NEUMANN_LIVE_TESTS=1 python -m pytest tests/e3/test_review_live.py -s -q
"""

from __future__ import annotations

import json
import os

import pytest

from neumann.analyze.gate import verify_expected_review
from neumann.analyze.review import generate_expected_review
from tests.fixtures.loader import load_fixtures

LIVE = os.getenv("NEUMANN_LIVE_TESTS") == "1"
MODEL = os.getenv("NEUMANN_LLM_MODEL") or "gpt-6-astra"

pytestmark = pytest.mark.skipif(not LIVE, reason="NEUMANN_LIVE_TESTS=1일 때만 실제 API를 부른다")


class OpenAIDirectCall:
    """임시 llm_call: Responses API(strict json_schema) → 로컬 재검증. 실패면 None."""

    generator = "astra"

    def __init__(self, model: str = MODEL, timeout_s: float = 120.0) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.last_error: str | None = None
        self.usage: dict[str, int] = {}

    def __call__(self, schema: dict, instructions: str, input: str, *, effort: str) -> dict | None:  # noqa: A002
        import jsonschema
        from openai import OpenAI

        client = OpenAI(max_retries=0, timeout=self.timeout_s)
        try:
            resp = client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input,
                reasoning={"effort": effort},
                text={"format": {"type": "json_schema", "name": "expected_review", "schema": schema, "strict": True}},
                store=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {str(getattr(exc, 'message', ''))[:200]}"
            return None
        usage = getattr(resp, "usage", None)
        self.usage = {k: getattr(usage, k) for k in ("input_tokens", "output_tokens") if isinstance(getattr(usage, k, None), int)}
        try:
            data = json.loads(resp.output_text)
        except (TypeError, ValueError) as exc:
            self.last_error = f"json_invalid: {exc}"
            return None
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(data))
        if errors:
            self.last_error = f"schema_invalid: {errors[0].message[:160]}"
            return None
        return data


def test_live_astra_expected_review_on_fixture():
    assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY가 없다"
    result = load_fixtures().premortem_result
    call = OpenAIDirectCall()
    review = generate_expected_review(result, call, effort="medium")

    print("\n[E3-L1a live] usage=", call.usage, "last_error=", call.last_error)
    print(json.dumps({k: v for k, v in review.items() if k != "attempts"}, ensure_ascii=False, indent=1))
    print("attempts=", json.dumps(review["attempts"], ensure_ascii=False))

    assert review["generator"] == "astra", review["reason"]
    assert review["model"] == MODEL
    assert review["status"] == "ok"
    assert review["audit"]["pass"] >= 1
    assert review["weakness"], "약점 문장이 1개 이상이어야 한다"
    # 통과 문장을 결과에 대고 다시 검사해도 전부 통과한다(근거 없는 문장 0)
    recheck = verify_expected_review(review, result)
    assert not recheck.dropped, recheck.reasons()
    assert len(recheck.passed) == review["audit"]["pass"]
