"""EXPORT-TITLE: 사용자 제목은 재렌더링에서도 보존하고 서명된 본문과 분리한다."""

from __future__ import annotations

import copy
import hashlib
import hmac
import io
import re
from urllib.parse import unquote

import pytest
from docx import Document

from neumann.analyze import revise as revise_mod
from neumann.api import signing
from neumann.api import revise as api
from neumann.api import export
from neumann.api.export_title import DEFAULT_TITLE, content_disposition, filename_title
from tests.e3.revise_fixtures import make_store
from tests.e4.test_export_pairing import chain  # noqa: F401 — 실제 mock 서명 사슬
from tests.e4.test_revise_api import client, make, run
from tests.fixtures.loader import plan_text


def test_signed_polished_custom_title_survives_zip(chain):
    title = "V core custom title"
    assembled = api.run_assembly(api.AssembleRequest(
        result=chain.result, result_sig=chain.result_sig, plan_text=plan_text(),
        revision=chain.revision, decisions=chain.decisions, title=title, polish=True,
    ), provider="mock")
    assert title in assembled["markdown"]["history"]
    payload = chain.payload()
    payload["revised_plan"] = assembled
    sent = chain.send(payload)
    assert sent.status == 200, sent.detail
    assert sent.assembly_trusted
    assert title in sent.files["revised_plan.md"].decode("utf-8")
    assert sent.files["revised_plan.md"].decode("utf-8") == (
        assembled["markdown"]["footnoted"].rstrip("\n") + "\n\n" + assembled["markdown"]["history"]
    )
    assert title in sent.readme
    assert sent.manifest["title"] == title
    assert sent.manifest["title_origin"] == "user_input_unsigned"
    assert title.replace(" ", "_") in download_name(sent.headers["content-disposition"])


def download_name(header):
    return unquote(header.split("filename*=UTF-8''", 1)[1])


@pytest.mark.parametrize("fmt", ["json", "md", "docx"])
def test_assembly_formats_preserve_title_and_safe_filename(chain, tmp_path, monkeypatch, fmt):
    monkeypatch.setattr(revise_mod, "default_record_store", lambda: make_store())
    _, app = make(tmp_path, monkeypatch)
    app.include_router(export.router)
    title = "이온전도도 연구: A/B\\C? 2026"
    payload = dict(result=chain.result, result_sig=chain.result_sig, plan_text=plan_text(),
                   revision=chain.revision, decisions=chain.decisions, polish=True, title=title, format=fmt)

    async def go():
        async with client(app) as c:
            response = await c.post(api.ASSEMBLE_PATH, json=payload)
            assert response.status_code == 200, response.text
            if fmt == "json":
                body = response.json()
                assert body["title"] == title
                assert title in body["markdown"]["history"]
            else:
                name = download_name(response.headers["content-disposition"])
                assert filename_title(title) in name and name.endswith("." + fmt)
                assert not re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]', name)
                if fmt == "md":
                    assert title in response.text
                else:
                    doc = Document(io.BytesIO(response.content))
                    assert doc.paragraphs[0].text == title

    run(go())


def test_title_override_does_not_change_signed_assembly(chain):
    payload = chain.payload()
    original = copy.deepcopy(payload["revised_plan"])
    # A title change never requires a server signature or changes body identity.
    payload["revised_plan"]["title"] = "연구자가 바꾼 제목"
    payload["revised_plan"]["markdown"]["history"] = (
        "# 연구자가 바꾼 제목 — 수정 이력과 근거\n" + original["markdown"]["history"].partition("\n")[2]
    )
    body = {k: v for k, v in payload["revised_plan"].items() if k != "revised_plan_sig"}
    assert signing.verify_payload("revised-plan", body, original["revised_plan_sig"])
    payload["title"] = "내보내기 최종 제목"
    sent = chain.send(payload)
    assert sent.status == 200 and sent.assembly_trusted
    assert sent.manifest["title"] == payload["title"]
    assert payload["title"] in sent.readme
    assert payload["title"] in sent.files["revised_plan.md"].decode()
    assert payload["revised_plan"]["revised_plan_id"] == original["revised_plan_id"]


@pytest.mark.parametrize("field", ["revised_text", "history", "footnoted", "change", "polish"])
def test_only_title_is_unsigned(chain, field):
    body = {k: copy.deepcopy(v) for k, v in chain.revised_plan.items() if k != "revised_plan_sig"}
    if field in ("history", "footnoted"):
        body["markdown"][field] += "\n변조한 근거나 이력"
    elif field == "change":
        body["changes"][0]["new_text"] += "변조"
    elif field == "polish":
        body["polish"]["applied"] = not body["polish"]["applied"]
    else:
        body[field] += "변조"
    assert not signing.verify_payload("revised-plan", body, chain.revised_plan["revised_plan_sig"])


def test_legacy_signed_title_is_preserved(chain):
    payload = chain.payload()
    plan = payload["revised_plan"]
    plan.pop("title", None)
    plan["markdown"]["history"] = "# Legacy custom title — 수정 이력과 근거\n" + plan["markdown"]["history"].partition("\n")[2]
    body = {k: v for k, v in plan.items() if k != "revised_plan_sig"}
    digest = hmac.new(signing._KEY, signing._payload_bytes("revised-plan", body, legacy=True), hashlib.sha256).hexdigest()
    plan["revised_plan_sig"] = "v1." + digest
    sent = chain.send(payload)
    assert sent.status == 200 and sent.assembly_trusted
    assert "Legacy custom title" in sent.files["revised_plan.md"].decode()
    assert sent.manifest["title"] == "Legacy custom title"
    body["revised_text"] += "변조"
    assert not signing.verify_payload("revised-plan", body, plan["revised_plan_sig"])


@pytest.mark.parametrize("title", ["../../CON:\\A?\r\n\x00\x7f<>|*", "가" * 1000, "../\\\x01", "CON", ""])
def test_download_filename_is_safe_and_bounded(title):
    header = content_disposition("neumann_package", "id/\\unsafe", title, "zip")
    filename = download_name(header)
    assert filename.endswith(".zip")
    assert not re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]', filename)
    assert ".." not in filename and len(filename.encode("utf-8")) <= 255
    assert header.isascii() and "\r" not in header and "\n" not in header


def test_package_title_without_revision_and_default(chain):
    for title in ("새 계획서 제목", None):
        payload = {"result": chain.result, "result_sig": chain.result_sig}
        if title is not None:
            payload["title"] = title
        sent = chain.send(payload)
        assert sent.status == 200
        assert len(sent.files) == 9
        assert sent.manifest["title"] == (title or DEFAULT_TITLE)


def test_title_html_is_text_and_pii_is_masked(chain):
    payload = chain.payload()
    payload["title"] = "<script>alert(1)</script> mail@example.org\r\n\x00"
    sent = chain.send(payload)
    assert sent.status == 200
    assert "mail@example.org" not in sent.readme
    assert "<script>" not in sent.readme
    assert "<script>" not in sent.files["revised_plan.md"].decode()
    assert "&lt;script&gt;" in sent.files["revised_plan.md"].decode()
    assert "[EMAIL]" in sent.manifest["title"]


def test_package_rejects_overlong_title(chain):
    payload = chain.payload()
    payload["title"] = "x" * 201
    assert chain.send(payload).status == 422
