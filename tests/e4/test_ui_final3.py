"""Stage UI contract regression; real local HTTP with fixture corpus and mock provider."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def test_final3_static_preserves_merge_and_compatibility():
    html = Path('src/neumann/webui/index.html').read_text(encoding='utf-8')
    assert not any(marker in html for marker in ('<<<<<<<', '=======\n', '>>>>>>>'))
    assert "sandbox: '제한 실행'" not in html
    assert "fetch('premortem/revise/' + 'finalize'" in html
    assert 'final_text:C.res.final_text' in html
    assert 'finalization:C.res.raw.finalization || C.res.raw' in html
    assert '반영 안 된 수정 ' in html
    assert 'U.genLabel(cd.gen, cd.genl)' in html
    assert 'excludedReview' in html and 'excludedCheck' in html
    assert 'result_sig: d.result_sig || null' in html


@pytest.mark.skipif(os.getenv('NEUMANN_UI_TESTS') != '1', reason='Explicit headless local HTTP test')
def test_final3_real_mock_http(tmp_path):
    from tests.e3.corpus import build_backend
    from tests.e4.revise_mock_data import build_mock_final
    from tests.e4.ui_shots import stop_server
    from playwright.sync_api import sync_playwright
    root = Path.cwd()
    backend = build_backend()
    corpus = tmp_path / 'corpus.json'
    corpus.write_text(json.dumps({'works':[w.model_dump(mode='json', by_alias=True) for w in backend.works.values()],
        'reviews':[r.model_dump(mode='json', by_alias=True) for rows in backend.reviews.values() for r in rows]}), encoding='utf-8')
    env = dict(os.environ)
    for key in ('OPENAI_API_KEY', 'NEUMANN_PSEUDONYM_SALT', 'NEUMANN_LIVE_LLM_OK', 'NEUMANN_LIVE_TESTS'):
        env.pop(key, None)
    env.update(NEUMANN_LLM_PROVIDER='mock', NEUMANN_EVIDENCE_BACKEND='fixture', NEUMANN_FIXTURE_CORPUS=str(corpus),
        NEUMANN_DATA_DIR=str(tmp_path/'data'), NEUMANN_RESULT_CACHE='0', NEUMANN_EXTRACT_CACHE='0',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONPATH='src;.', PYTHONUTF8='1')
    base='http://127.0.0.1:8178'
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','neumann.api.main:app','--host','127.0.0.1','--port','8178','--log-level','warning','--no-access-log'], cwd=root, env=env)
    try:
        for _ in range(100):
            try:
                if httpx.get(base+'/health', timeout=1).status_code == 200: break
            except httpx.HTTPError: pass
            time.sleep(.2)
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':900}, accept_downloads=True)
            errors=[]; requests=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def package_status(response):
                if response.url.endswith('/premortem/package') and response.status != 200:
                    payload=response.json()
                    print('package rejected',response.status,[(x.get('type'),x.get('loc'),x.get('msg')) for x in payload.get('detail',[]) if isinstance(x,dict)] if isinstance(payload.get('detail'),list) else payload.get('message') or payload.get('detail'))
            page.on('response',package_status)
            page.on('request',lambda r:requests.append((r.url,r.post_data_json)) if r.method=='POST' else None)
            page.goto(base,wait_until='networkidle')
            page.fill('#ta',build_mock_final()['plan_text'])
            page.click('#btnStart')
            page.wait_for_selector('#faNext',timeout=120000)
            view=page.evaluate('window.NeumannUI.D()')
            assert view['result_sig'] and view['cards']
            page.click('#faNext')
            page.wait_for_selector('#fdDoc',timeout=120000)
            assert page.evaluate("window.NeumannRevise.state().asm.source") == 'server'
            edited='연구자가 확정한 문안: 유사 조성의 중복을 제거한 뒤 그룹 단위로 데이터를 분할합니다.'
            page.locator('#fdDoc .fd-p.chg p').first.click()
            page.fill('.fd-ta',edited)
            page.locator('.fd-ta').press('Control+Enter')
            assert edited in page.inner_text('#fdDoc')
            page.click('#fdNext')
            page.wait_for_function("window.NeumannFinal.check().status !== 'running'",timeout=120000)
            assert page.evaluate("window.NeumannFinal.check().status") == 'done', page.inner_text('#fin-check')
            page.click('#fcNext')
            server_text=page.evaluate('window.NeumannFinal.check().res.raw.final_text')
            assert server_text
            assert edited in server_text
            with page.expect_download() as download:
                page.click('#fzDocx')
            assert Path(download.value.path()).stat().st_size > 0
            package=next(body for url,body in requests if url.endswith('/premortem/package'))
            assert package['result_sig'] == view['result_sig']
            assert package['final_text'] == server_text
            assert package['finalization']
            assert any(url.endswith('/premortem/revise') for url,_ in requests)
            assert any(url.endswith('/premortem/revise/assemble') for url,_ in requests)
            assert any(url.endswith('/premortem/revise/finalize') for url,_ in requests)
            final_request=next(body for url,body in requests if url.endswith('/premortem/revise/finalize'))
            assert edited in final_request['confirmed_text']
            assert not errors
            page.screenshot(path='docs/reports/UI-FINAL_shots/UI-FINAL-3_real_mock_done.png',full_page=True)
            browser.close()
    finally:
        stop_server(proc,8178)
