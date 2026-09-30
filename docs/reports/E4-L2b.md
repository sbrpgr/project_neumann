# E4-L2b 보고서 — MCP 서버(도구 3종, 읽기 전용)

- 빌더: Claude Opus 5.5 · 브랜치 `task/E4-L2b` · 2026-09-30
- 결과: 완료 기준 3개 모두 충족. 실제 색인 예시는 두 경로로 쟀다: (a) 이 브랜치 그대로(E2·E1-L2가 main에 없어 얇은 어댑터가 돈다), (b) E2-L0·E1-L2 모듈을 얹은 임시 트리(하이브리드 검색·E1 조회 모듈이 돈다).

## 무엇을 했나

1. 공식 Python SDK 설치: `uv pip install --python C:/Users/User/.venvs/neumann/Scripts/python.exe mcp`
   (venv에 pip가 없어 `python -m pip` 대신 uv를 썼다. 새로 추가만 됐고 기존 패키지 업그레이드는 없다 — `--dry-run`으로 먼저 확인)
   - 설치: **mcp 2.2.0**, mcp-types 2.2.0, sse-starlette 3.5.0, pyjwt 2.15.1, cryptography 50.0.1, cffi 2.1.1, pycparser 3.0, opentelemetry-api 1.45.0, pywin32 312
   - 주의: mcp 2.x는 v1과 API가 다르다. `FastMCP`가 `mcp.server.mcpserver.MCPServer`로 바뀌었고 v1 코드는 import에서 실패한다.
2. `src/neumann/api/mcp_server.py` — stdio MCP 서버 `python -m neumann.api.mcp_server`
   - `search_similar_works(query, k=10)` → 논문 id·제목·원문 URL(`url`, `source_url`)·점수(`score`·`dense`·`lexical`, 0~1)·`matched_query`, 그리고 검색 `backend`·`degraded`·`reason`
   - `get_review_records(work_id)` → 논문 참조, 심사평(`kind`·`rating`·`confidence`·`created`)·저자 답변(`review_id` 연결)·결정(`outcome`·`outcome_raw`). 레코드마다 `url`(딥링크)·`source_url`(provenance)·`text_chars`·`text_head`(원문 앞 600자 글자 그대로)·`truncated`·`text_sha256`
   - `get_post_status(doi)` → 원논문 DOI 정규화 뒤 사후상태 레코드(`kind`·`notice_doi`·`notice_url`=`https://doi.org/<공지 DOI>`·`reason_codes` 원문·`source_url`·`snapshot`), 데이터셋 `citation`·`dataset_url`·`license`
   - 읽기 전용: 세 도구 모두 `readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False`. 쓰기·외부 네트워크 호출 없음(HF도 오프라인 기본값)
   - 계획서 본문 거부: 검색어 300자 초과면 `is_error`로 "계획서 본문은 보내지 않는다"를 돌려준다
   - 신원 정보 없음: 리뷰어 가명(`reviewer_pseudonym`)도 내보내지 않는다. 출력 모델을 `NeumannModel`로 만들어 신원 토큰이 들어간 필드 이름은 정의 시점에 막힌다(그래서 저자 답변 목록 키가 `author_responses`가 아니라 `responses`다)
   - 강등 표기: 임베딩 없이 돌면 `degraded=True`와 사유. 파일이 없어 모르는 것(답변·결정)은 `notes`에 "0건은 '없음'이 아니라 '모름'"으로 적는다. 사후상태 파일이 없으면 `no_record`로 속이지 않고 오류를 낸다
   - 얇은 어댑터: `neumann.index.search`·`store`(E2-L0)와 `neumann.sources.retraction`(E1-L2)을 불러올 수 있으면 그대로 쓰고, 없으면 공유 데이터 파일을 직접 읽는다(아래 "결정" 2). 어느 쪽인지 결과의 `backend`에 남는다
   - 시작 때 백그라운드 스레드로 색인·bge-m3를 미리 읽는다(`--no-warmup`으로 끔). stdout은 MCP 채널이라 로그는 stderr로만
3. `tests/e4/test_mcp_server.py` — 11개. 공식 SDK 클라이언트(`mcp.Client` + `stdio_client`)로 서버를 **실제 하위 프로세스로 띄워** 도구 목록 3개·annotations·입출력 스키마, 도구별 결과 형식, 없는 work_id·없는 DOI·잘못된 DOI·계획서 본문·k=0·빈 검색어를 검사한다. 프로세스 안 연결(`Client(server)`)로 리뷰어 가명 비노출, 데이터 파일 누락 표기, 파일 어댑터 검색, DOI 정규화를 검사한다. 데이터는 공용 fixture로 만든 임시 폴더(가짜 DOI `10.9999/...`)이고 실제 색인·API를 부르지 않는다. 임시 색인은 E2 모듈이 있으면 `IndexStore.from_corpus(...).save()`(임베딩 없이)로, 없으면 E2 디스크 형식으로 직접 쓴다 — 기대 `backend`도 그에 맞춰 정확히 검사한다(두 경우 모두 통과 확인, 아래 1-b).

## 완료 기준별 측정

### 1. `python -m pytest tests/e4 -q -k mcp` 통과

(a) 이 브랜치(main 병합 뒤, E2·E1-L2 미병합 → 어댑터 경로)

```
$ C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4 -k mcp -v
tests/e4/test_mcp_server.py::test_mcp_lists_three_read_only_tools PASSED
tests/e4/test_mcp_server.py::test_mcp_search_result_shape PASSED
tests/e4/test_mcp_server.py::test_mcp_search_default_k_and_input_rejections PASSED
tests/e4/test_mcp_server.py::test_mcp_review_records_shape PASSED
tests/e4/test_mcp_server.py::test_mcp_review_records_unknown_id PASSED
tests/e4/test_mcp_server.py::test_mcp_post_status_shape_and_missing PASSED
tests/e4/test_mcp_server.py::test_mcp_outputs_have_no_identity_keys PASSED
tests/e4/test_mcp_server.py::test_mcp_pseudonym_never_leaves_server PASSED
tests/e4/test_mcp_server.py::test_mcp_missing_sources_are_reported_not_hidden PASSED
tests/e4/test_mcp_server.py::test_mcp_file_adapter_search PASSED
tests/e4/test_mcp_server.py::test_mcp_normalize_doi_rule PASSED
11 passed, 57 deselected in 3.26s
```

(b) 병합 뒤 모양 미리 보기: 이 브랜치 HEAD + `task/E2-L0`(427dcb0)의 `src/neumann/index/` + `task/E1-L2`(64b597d)의 `retraction.py`를 스크래치 폴더에 풀어 같은 테스트를 돌렸다(저장소에는 넣지 않음). 이때 검색은 E2 `search`(`backend=lexical_only`), 사후상태는 E1 모듈(`backend=neumann.sources.retraction`)이 돈다.

```
$ (overlay) python -m pytest tests/e4 -q -k mcp -p no:cacheprovider
11 passed, 57 deselected in 3.59s
```

### 2. 실제 색인으로 도구 3개 호출 예시

공유 데이터 폴더(`C:/Users/User/Desktop/project_neumann/data`, 색인 1,128편·심사평 5,366건, RW 66,737건)를 쓰고, SDK 클라이언트가 stdio로 서버를 띄워 불렀다(스크래치 스크립트 `demo_stdio.py`, 저장소 밖). 서버 인자는 `--data-dir .../data`, 환경변수 `NEUMANN_EMBED_MODEL=.../bge-m3`, 시작 워밍업 켬.

**(b) E2·E1-L2 모듈 경로(병합 뒤 모양) — 하이브리드 검색**

연결 1.76초. `list_tools` → 3개, 모두 `read_only_hint=True`.

`search_similar_works("graph neural network molecular property prediction", k=5)` — 첫 호출 15.84초(워밍업: 색인 적재 + bge-m3 적재를 기다림), `backend=hybrid`, `degraded=False`

| work_id | score | dense | lexical | 제목 | url |
|---|---|---|---|---|---|
| researcharcade_hf:Mtlt3RQTXJ | 0.809 | 0.682 | 1.000 | Bi-level Contrastive Learning for Knowledge Enhanced Molecule Representations | https://openreview.net/forum?id=Mtlt3RQTXJ |
| researcharcade_hf:OIvg3MqWX2 | 0.807 | 0.683 | 0.991 | A Theoretically-Principled Sparse, Connected, and Rigid Graph Representation … | https://openreview.net/forum?id=OIvg3MqWX2 |
| researcharcade_hf:uqPnesiGGi | 0.793 | 0.654 | 1.000 | Motif-aware Attribute Masking for Molecular Graph Pre-training | https://openreview.net/forum?id=uqPnesiGGi |
| researcharcade_hf:4S2L519nIX | 0.786 | 0.644 | 1.000 | Pushing the Limits of All-Atom Geometric Graph Neural Networks … | https://openreview.net/forum?id=4S2L519nIX |
| researcharcade_hf:Nue5iMj8n6 | 0.779 | 0.631 | 1.000 | Equivariant Masked Position Prediction for Efficient Molecular Representation | https://openreview.net/forum?id=Nue5iMj8n6 |

`search_similar_works("단백질 구조 예측을 위한 확산 모델", k=5)` — 0.26초, `backend=hybrid`. 한국어 질의가 임베딩으로 단백질·확산 논문을 찾는다(lexical 0)

| work_id | score | dense | 제목 |
|---|---|---|---|
| researcharcade_hf:DP4NkPZOpD | 0.355 | 0.592 | Bridging Sequence and Structure: Latent Diffusion for Conditional Protein … |
| researcharcade_hf:FuXtwQs7pj | 0.349 | 0.582 | A diffusion model on toric varieties with application to protein loop modeling |
| researcharcade_hf:C5u71ph75Q | 0.348 | 0.580 | Internal-Coordinate Density Modelling of Protein Structure … |
| researcharcade_hf:wCwz1F8qY8 | 0.341 | 0.568 | Prediction of Protein-protein Contacts with Structure-aware Single-sequence … |
| researcharcade_hf:UYZRaUCLAg | 0.338 | 0.564 | Solving Inverse Problems in Protein Space Using Diffusion-Based Priors |

`get_review_records("researcharcade_hf:Mtlt3RQTXJ")` — 0.91초(첫 호출에 답변·결정 파일 적재 포함). 심사평 5·저자 답변 20·결정 1. 발췌(보고서용으로 `text_head`를 160자에서 줄였다. 실제 출력은 600자):

```json
{
  "work": {"work_id": "researcharcade_hf:Mtlt3RQTXJ", "title": "Bi-level Contrastive Learning for Knowledge Enhanced Molecule Representations",
           "url": "https://openreview.net/forum?id=Mtlt3RQTXJ", "source_url": "https://openreview.net/forum?id=Mtlt3RQTXJ",
           "doi": null, "venue": "ICLR 2024", "year": 2024},
  "n_reviews": 5, "n_responses": 20, "n_decisions": 1,
  "reviews": [{"review_id": "researcharcade_hf:whLl3cDMpn", "kind": "official_review",
               "url": "https://openreview.net/forum?id=Mtlt3RQTXJ&noteId=whLl3cDMpn",
               "source_url": "https://openreview.net/forum?id=Mtlt3RQTXJ&noteId=whLl3cDMpn",
               "text_chars": 1553, "truncated": true,
               "text_sha256": "af11d233864bb0bf09af21552baf1d510a3d46a316132049467166b80ae25ef1",
               "text_head": "Summary:\nThis paper introduces Gode, a novel approach that integrates graph representations of individual molecules with multi-domain biomedical data from knowl…",
               "rating": "3: reject, not good enough", "confidence": "4: You are confident in your assessment,…",
               "created": "2023-10-25T03:31:24+00:00", "round": null}],
  "responses": [{"response_id": "researcharcade_hf:4xXuCXJMkS", "review_id": "researcharcade_hf:qOh4RRYBns",
                 "url": "https://openreview.net/forum?id=Mtlt3RQTXJ&noteId=4xXuCXJMkS", "text_chars": 1464, "truncated": true, "…": "…"}],
  "decisions": [{"decision_id": "researcharcade_hf:ePBzOtv5Dq", "outcome": "reject", "outcome_raw": "Rejected_Submission",
                 "url": "https://openreview.net/forum?id=Mtlt3RQTXJ&noteId=ePBzOtv5Dq", "text_chars": 0, "text_head": ""}],
  "notes": []
}
```

`get_post_status("https://doi.org/10.3389/fenvs.2025.1522528")` — 0.01초(워밍업에서 적재됨), `backend=neumann.sources.retraction`

```json
{"query": "https://doi.org/10.3389/fenvs.2025.1522528", "doi": "10.3389/fenvs.2025.1522528", "status": "found", "n_records": 1,
 "records": [{"post_status_id": "rw:73270", "kind": "retraction", "target_doi": "10.3389/fenvs.2025.1522528",
              "notice_doi": "10.3389/fenvs.2026.1953120", "notice_url": "https://doi.org/10.3389/fenvs.2026.1953120",
              "reason_codes": ["Concerns/Issues about Data", "Investigation by Journal/Publisher",
                               "Original Data and/or Images not Provided and/or not Available", "Unreliable Results and/or Conclusions"],
              "source_url": "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv",
              "snapshot": "rw-csv:2026-09-25", "accessed_at": "2026-09-28T10:26:14+00:00"}],
 "citation": "Retraction Watch Database, Crossref. https://gitlab.com/crossref/retraction-watch-data",
 "dataset_url": "https://gitlab.com/crossref/retraction-watch-data",
 "license": "undeclared: LICENSE 없음, Crossref가 인용을 요청(출처 표기 필수, CC0 아님)", "snapshot": "2026-09-25",
 "backend": "neumann.sources.retraction", "note": "원논문 DOI로만 찾는다(공지 DOI 아님). no_record는 …"}
```

오류·경계 처리(같은 실행):

| 호출 | 결과 |
|---|---|
| `get_review_records("researcharcade_hf:NOPE")` | `is_error=True`: "work_id 'researcharcade_hf:NOPE'가 색인에 없다. search_similar_works 결과의 work_id를 그대로 쓴다." |
| `get_post_status("10.48550/arXiv.2106.09685")` | `status=no_record`, `records=[]`(오류 아님) |
| `get_post_status("not-a-doi")` | `is_error=True`: "DOI 형식이 아니다: 'not-a-doi'. 예: …" |
| `search_similar_works("가"×400)` | `is_error=True`: "검색어가 400자다. 이 도구는 검색어만 받는다(300자 이하). 계획서 본문은 보내지 않는다 …" |

**(a) 이 브랜치 그대로(어댑터 경로)** — 같은 스크립트, 연결 1.45초

- 영어 검색 0.85초, `backend=adapter_token_overlap`, `degraded=True`, `reason="neumann.index를 불러올 수 없다(neumann.index): 토큰 겹침 비상 검색, 임베딩 없음"`. 상위: researcharcade_hf:AialDkY6y3 (1.0, Deep Graph Predictions using Dirac-Bianconi Graph Neural Networks), HrTGl8AhnS (1.0, PACIA … Few-Shot Molecular Property Prediction), nYPuSzGE3X (1.0, InversionGNN …)
- 한국어 검색: 0편, `degraded=True`(임베딩이 없으니 못 찾는다는 것을 그대로 드러낸다)
- `get_review_records(AialDkY6y3)` 1.35초: 심사평 6·답변 13·결정 1, `notes=["색인 모듈(E2) 대신 파일 어댑터로 읽었다."]`
- `get_post_status`: 위와 같은 레코드 `found`, `backend=adapter:processed/retraction.jsonl`, arXiv DOI `no_record`

### 3. `python scripts/verify.py` 통과

```
$ C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
194 passed, 2 skipped in 5.20s
보안: 파일 124개
계약: 2개
테스트: 통과
verify 통과
```

최종 확인 — main(E1-L0 코퍼스 병합 `ed1d1a0`까지)을 다시 받은 뒤, 보고서 커밋 직전:

```
$ C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4 -q -k mcp
11 passed, 57 deselected in 3.64s
$ C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/verify.py
231 passed, 6 skipped in 8.00s
보안: 파일 134개
계약: 2개
테스트: 통과
verify 통과
```

## MCP 서버 실행·연결

```bash
# 직접 실행(stdio, 클라이언트가 띄우는 것이 보통이다)
PYTHONPATH="src;." C:/Users/User/.venvs/neumann/Scripts/python.exe -m neumann.api.mcp_server \
  --data-dir C:/Users/User/Desktop/project_neumann/data
# 옵션: --index-dir PATH(기본 NEUMANN_INDEX_DIR 또는 {data}/index) --no-warmup --log-level INFO
```

Claude Code에 붙이기(예):

```bash
claude mcp add neumann \
  -e PYTHONPATH=C:/Users/User/Desktop/project_neumann/src \
  -e NEUMANN_EMBED_MODEL=C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3 \
  -- C:/Users/User/.venvs/neumann/Scripts/python.exe -m neumann.api.mcp_server \
     --data-dir C:/Users/User/Desktop/project_neumann/data
```

Claude Desktop·`.mcp.json` 형식(예):

```json
{"mcpServers": {"neumann": {
  "command": "C:/Users/User/.venvs/neumann/Scripts/python.exe",
  "args": ["-m", "neumann.api.mcp_server", "--data-dir", "C:/Users/User/Desktop/project_neumann/data"],
  "env": {"PYTHONPATH": "C:/Users/User/Desktop/project_neumann/src", "PYTHONIOENCODING": "utf-8",
          "NEUMANN_EMBED_MODEL": "C:/Users/User/Desktop/노이만_본선자료/공개자료/models/bge-m3"}}}}
```

- SDK stdio 클라이언트는 기본으로 PATH 등 몇 개 환경변수만 넘긴다. 그래서 `PYTHONPATH`와 `NEUMANN_EMBED_MODEL`을 `env`로 줘야 한다(`OPENAI_API_KEY`는 넘어가지 않고, 이 서버는 쓰지도 않는다).
- 첫 검색은 색인 적재 + bge-m3 적재 때문에 약 15초 걸린다(측정 15.84초). 이후 호출은 0.3초 안팎이다. 클라이언트의 도구 호출 시간 상한이 이보다 짧으면 첫 호출이 끊길 수 있다.
- 파이썬 코드에서: `async with Client(StdioServerParameters(command=..., args=["-m", "neumann.api.mcp_server", ...], env={...})) as c: await c.call_tool("search_similar_works", {"query": "...", "k": 5})`

## 바꾼 파일

- `src/neumann/api/mcp_server.py` (새 파일)
- `tests/e4/test_mcp_server.py` (새 파일)
- `docs/reports/E4-L2b.md` (이 보고서)
- venv: mcp 2.2.0 등 9개 설치(저장소 파일 아님)

`api/main.py`·`view.py`·`export.py`·`__init__.py`는 건드리지 않았다. 새 환경변수 키는 만들지 않았다(`NEUMANN_DATA_DIR`, E2의 `NEUMANN_INDEX_DIR`·`NEUMANN_EMBED_MODEL`만 읽는다).

## 결정 (스펙이 모호해서 고른 것)

1. **mcp 2.x API**: 설치된 최신이 2.2.0이라 `MCPServer`(구 FastMCP)로 썼다. 반환 타입을 pydantic 모델로 선언해 `outputSchema`와 `structuredContent`가 나가고, 같은 JSON이 텍스트 콘텐츠에도 들어간다(구조화 출력을 못 읽는 클라이언트용).
2. **얇은 어댑터**(E2·E1-L2 미병합 대응, 스펙 허용): E2 모듈이 없으면 색인 폴더의 `works.jsonl`·`reviews.jsonl`을 직접 읽고 제목+초록과 검색어의 토큰 겹침 비율로 찾는다(항상 `degraded=True`). E1-L2가 없으면 `processed/retraction.jsonl`을 같은 DOI 정규화 규칙으로 읽는다. 모듈이 들어오면 코드 변경 없이 모듈 쪽을 쓴다(overlay로 확인). 스펙 뒤로 물러난 폴백이 아니라 병합 전 대응이어서 `docs/decisions.md`(PM 소유)에는 적지 않았다.
3. **E2 저장소는 서버 자기 인스턴스**: `--index-dir`를 그대로 따르게 `IndexStore.load(index_dir)`를 한 번 읽고 `search(..., store=...)`로 넘긴다(프로세스 공용 `get_store()` 캐시는 설정의 폴더만 본다). MCP 서버는 따로 뜨는 프로세스라 메모리 중복은 없다.
4. **"요약"의 뜻**: 문장을 새로 쓰지 않고, 원문 앞부분 600자를 글자 그대로(`원문[0:len(text_head)]`) 주고 전체 길이·sha256·원문 URL을 붙였다. 전문이 필요하면 URL로 간다. 규칙·LLM 요약문을 만들지 않으므로 인용 정직성 규칙과 부딪히지 않는다.
5. **오류 규칙**: 없는 work_id·형식이 틀린 DOI·빈 검색어·300자 초과·k 범위 밖은 `is_error=True`(모델이 읽고 고칠 수 있게 이유와 예시를 적음). 형식이 맞는데 RW에 없는 DOI는 오류가 아니라 `status=no_record`(E1-L2 스펙 "없는 DOI는 빈 목록"과 같음). 데이터 파일이 없을 때 사후상태는 오류, 답변·결정은 빈 목록 + `notes`.
6. **검색어 상한 300자**: 계획서 본문을 막으려는 값. 한국어 검색어 한두 문장은 충분히 들어간다. 스키마 `maxLength` 대신 본문에서 검사해 "계획서 본문은 보내지 않는다"는 이유를 돌려준다(도구 설명에 상한을 적음).
7. **결정은 목록**: 계약상 논문당 결정이 여럿일 수 있어(eLife 라운드) `decisions: list`로 뒀다. ICLR 코퍼스는 1건씩.
8. **리뷰어 가명도 제외**: 계약상 허용 필드지만 "신원 정보 없음" 요구에 맞춰 출력하지 않는다(테스트로 확인).

## 못 한 것

- `pyproject.toml`에 `mcp` 의존성 추가(루트 파일은 PM 소유) → **제안: `"mcp>=2.2,<3"`**. 1.x를 깔면 `mcp.server.mcpserver`가 없어 import에서 실패한다.
- E2-L0·E1-L2가 아직 main에 없어, 이 브랜치의 테스트·verify는 어댑터 경로로 돈다. 모듈 경로는 스크래치 overlay(저장소 밖)에서만 확인했다(1-b, 2-b). 병합 뒤 `pytest tests/e4 -k mcp`를 한 번 다시 돌리면 기대 `backend`가 자동으로 모듈 쪽으로 바뀌어 검사된다.
- 실제 Claude Desktop·Claude Code 앱에 붙여 보지는 않았다. 공식 SDK 클라이언트의 stdio 연결로만 검증했다.
- HTTP(streamable-http) 전송은 열지 않았다(스펙은 stdio). E1-L2의 `field_failure_prior`는 도구로 열지 않았다(스펙 3종 밖).

## 다음 과제에 넘길 것

- E2-L0·E1-L2 병합 뒤: `pytest tests/e4 -k mcp` 재실행(모듈 경로 검사). 그때 어댑터(`FileIndexAdapter`, retraction 파일 읽기)는 비상 경로로 남겨 둬도 되고, 지워도 도구 동작은 같다.
- E1-L1b(eLife·Europe PMC)가 들어오면 `get_review_records`가 `editor_assessment`·`public_review` 종류와 여러 라운드 결정을 그대로 돌려준다(종류 필터 없음). 결정 `text`가 있는 소스라서 `text_head`가 채워진다.
- 발표 AI 구성도에 "MCP 서버(L2, 읽기 전용 3종)" 표시(계획서 §1.5).
