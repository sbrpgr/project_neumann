# E4-L2b 검증 보고서 (검증자: Claude Sonnet 5.5)

- 대상: 브랜치 `task/E4-L2b` (HEAD `c1095de`, main `ed1d1a0` 병합 뒤), worktree `.claude/worktrees/agent-aeb015dd9c4eb6e48`, 빌더 claude-opus-5.5
- 방법: 빌더 보고서를 믿지 않고 완료 기준을 직접 실행했다. 조작 입력·변이 실험·E2/E1-L2 덮어쓰기는 스크래치 폴더(`scratchpad\v`)의 복사본에서만 했고 worktree 코드와 git은 건드리지 않았다(worktree `git status` 깨끗, 남긴 파일 없음).
- 환경: Windows Python `neumann` venv(`mcp 2.2.0`), `PYTHONPATH="src;."`, `NEUMANN_DATA_DIR`=공유 데이터 폴더. 실제 색인은 `data/index`(1,128편), 사후상태 `data/processed/retraction.jsonl`(66,737건).

## 결론

**PASS.** 병합을 막는 결함은 없다. 병합 시 PM 조치 1건과 비차단 권고 4건은 맨 아래에 있다.

## 항목별 결과

| # | 확인 항목 | 실행한 명령 / 방법 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1 | 완료 기준 1: mcp 테스트 | `python -m pytest tests/e4 -q -k mcp -p no:cacheprovider` | **11 passed**, 57 deselected, 3.67s. 서버를 실제 하위 프로세스(stdio, 공식 SDK `Client`)로 띄워 검사한다 | 통과 |
| 2 | 완료 기준 3: verify | `python scripts/verify.py` (브랜치 worktree) | **237 passed**, 보안 134개 파일, 계약 2개, `verify 통과`. (빌더 보고서의 "231 passed, 6 skipped"와 skip 수가 다른 것은 내가 `NEUMANN_RAW_DIR` 등 환경변수를 넣어 원본 필요 테스트가 돈 차이) | 통과 |
| 3 | 완료 기준 2: 실제 색인으로 도구 3개 호출 | 스크래치 스크립트로 SDK 클라이언트가 `python -m neumann.api.mcp_server --data-dir <공유 data>`를 stdio로 띄워 호출. (a) 이 브랜치 그대로, (b) `task/E2-L0`의 `src/neumann/index/`와 `task/E1-L2`의 `retraction.py`를 `git archive`로 스크래치 복사본에 얹은 병합 뒤 모양 | (a) `search`: `backend=adapter_token_overlap, degraded=True, reason` 표기, 상위 AialDkY6y3 등 5편, 한국어 질의는 0편(임베딩 없음을 숨기지 않음). `records`(AialDkY6y3): 심사평 6·답변 13·결정 1, `notes`에 "파일 어댑터로 읽었다". `post`: 철회 1건 `found`. (b) `search`: `backend=hybrid, degraded=False`, 상위 Mtlt3RQTXJ(0.809)·OIvg3MqWX2(0.807)… 빌더 보고서 수치와 같고, 한국어 질의도 단백질·확산 논문 3편. `records`: 5·20·1, `notes` 비어 있음. `post`: `backend=neumann.sources.retraction`. 첫 hybrid 검색 15.57초(모델 적재), 이후 0.2초 안팎. 덮어쓴 복사본에서도 `pytest -k mcp` 11 passed. 서버 stdout은 MCP 프레임만(stderr에 모델 적재 진행률만 나옴) | 통과 |
| 4 | 도구 3개·읽기 전용 | `list_tools`(실서버), 코드 grep | 도구는 정확히 3개: `search_similar_works`·`get_review_records`·`get_post_status`. 셋 다 `readOnlyHint=True, destructiveHint=False, openWorldHint=False`. 없는 도구 호출은 `Unknown tool`. 코드에 쓰기(`open(..,'w')`·`write_*`·`unlink`·`mkdir`·`shutil`)·네트워크(`requests`·`urllib.request`·`httpx`·`socket`)·`subprocess` 호출 없음(읽기 `open`·`read_text`뿐). 실서버 호출 전후 `data/` 파일 목록·크기·mtime 비교: `index/`·`processed/` 변화 0 (`data/cache/europepmc/`에 파일 7개가 늘었으나 같은 시각 다른 에이전트의 E1 수집 프로세스 것이고 이 서버는 `cache/`를 읽지도 않는다) | 통과 |
| 5 | 계획서 본문을 받지 않는가 | 실서버에 검색어 길이 300/301/399(공백 섞임)/100,000자, 공백 500자+짧은 검색어, 테스트의 `plan.md` fixture 전문 | 300자는 통과, **301자·399자·100,000자는 `is_error`**: "검색어가 N자다. 이 도구는 검색어만 받는다(300자 이하). 계획서 본문은 보내지 않는다". 오류 메시지는 길이만 되풀이하고 입력 본문을 되돌려주지 않는다. 앞뒤 공백은 strip 뒤 길이를 잰다(공백 500자+`protein`은 검색어 `protein`으로 처리). 도구 입력 필드는 `query`·`k`·`work_id`·`doi`뿐이라 본문을 실어 보낼 다른 인자가 없다(스키마에 없는 인자는 조용히 버려짐) | 통과 |
| 6 | 결과마다 출처 URL | 실제 데이터 전량: `get_review_records`를 1,128편 전부(레코드 19,154건)에 대해 실행, `get_post_status`는 kind 4종×(공지 DOI 유무)×3,000건 표본 | 논문·심사평·답변·결정 19,154건 + 논문 1,128건 전부 `url`·`source_url`이 http(s), **누락 0**. 사후상태는 `source_url`(RW CSV, provenance) 3,000건 표본 누락 0, 공지 DOI가 있으면 `notice_url=https://doi.org/<공지 DOI>`, `dataset_url`·`citation`·`license`도 붙음. 검색 히트는 `url`·`source_url`이 없으면 결과에서 뺀다(코드) | 통과 |
| 7 | 신원 정보 0 | 실서버·전량 출력의 키 이름 전수, `text_head` 정규식 스캔(이메일·`openreview.net/profile`·`~Name_Name`), 리뷰어 가명 주입 테스트 | 출력 키 전체: `confidence, created, decision_id, decisions, doi, head_chars, kind, n_*, notes, outcome, outcome_raw, rating, response_id, responses, review_id, reviews, round, source_url, text_chars, text_head, text_sha256, title, truncated, url, venue, work, work_id, year` — 신원 토큰(`name·email·orcid·author·affiliation·profile…`) 없음, `reviewer_pseudonym`도 안 나옴. 19,154건 `text_head` 스캔 이메일 0·프로필 링크 0. 출력 모델은 `NeumannModel`이라 신원 토큰 필드는 정의 시점에 TypeError. 가명이 든 `ReviewEvent`를 주입해도 응답 전체에 가명 문자열이 없음(테스트) | 통과 |
| 8 | 잘못된 입력 처리 | 실서버에 각각 호출 | 모두 서버가 죽지 않고 `is_error`로 이유를 돌려줌: 빈 검색어·k=0/-1/51·k="abc"·인자 누락·query=123·work_id 빈 값/`../../etc/passwd`/없는 id/100,000자·DOI 빈 값/`not-a-doi`/`…; rm -rf /`. 특수 문자·널 바이트·`'; DROP TABLE` 검색어는 그냥 검색어로 처리(0~10건). 형식은 맞지만 RW에 없는 DOI(arXiv)는 오류가 아니라 `status=no_record`(records 빈 목록, note에 "보증 아님"). 10만 자 DOI도 0.03초에 처리(정규식 지연 없음). 대소문자·`doi:`·`https://doi.org/` 접두는 정규화 | 통과 |
| 9 | 원문 오프셋 정직성 | 색인 `reviews.jsonl` 원본에서 150편·심사평 751건을 임의로 뽑아 서버 결과와 대조 | `text_head == 원문[0:len]`, `text_chars`, `text_sha256`(원문 sha256을 직접 계산), `truncated`, `rating`이 **751건 전부 일치, 불일치 0**. 요약문을 새로 쓰지 않고 앞 600자를 그대로 준다 | 통과 |
| 10 | 강등·데이터 없음 표기 | 실서버 어댑터 경로, 임시 폴더에 `processed/` 없음 | 임베딩·E2 모듈 없이 돌면 `degraded=True`와 사유가 결과에 있음. 답변·결정 파일이 없으면 `notes`에 "0건은 '없음'이 아니라 '모름'". 사후상태 파일이 없으면 `no_record`로 속이지 않고 오류. 규칙 결과를 LLM 결과로 표시하는 곳 없음(이 서버는 LLM을 부르지 않는다) | 통과 |
| 11 | 계약·소유 경로 | `git diff main...task/E4-L2b --name-status`, `git diff … -- contracts src/neumann/models.py` | 변경 3개만: `A src/neumann/api/mcp_server.py`, `A tests/e4/test_mcp_server.py`, `A docs/reports/E4-L2b.md`. 모두 소유 경로 또는 허용된 보고서. `contracts/`·`models.py`·`main.py`·`view.py`·`export.py`·`pyproject.toml` 변경 0. `data/`·비밀값·`.env` 파일 추가 0. 차분에서 키 패턴(`sk-…`, `api_key=…`) 검색 결과 없음. 환경변수 새 키 없음(기존 `NEUMANN_DATA_DIR`·`NEUMANN_INDEX_DIR`·`NEUMANN_EMBED_MODEL`만) | 통과 |
| 12 | 테스트가 항상 통과하지 않는가(변이 실험) | 스크래치 복사본의 `mcp_server.py`에 결함 9종을 하나씩 심고 `pytest tests/e4 -k mcp -x` | 9종 모두 **실패로 잡힘**: M1 검색어 상한 제거 → `test_mcp_search_default_k_and_input_rejections`, M2 `read_only_hint=False` → `test_mcp_lists_three_read_only_tools`, M3 리뷰어 가명 출력 → `test_mcp_pseudonym_never_leaves_server`, M4 히트 `source_url` 빈 문자열 → `test_mcp_search_result_shape`, M5 `text_head` 변조(`the`→`THE`) → `test_mcp_review_records_shape`, M6 강등 숨김(`degraded=False`) → `test_mcp_search_result_shape`, M7 없는 id가 빈 결과 반환 → `test_mcp_review_records_unknown_id`, M8 `no_record` 제거 → `test_mcp_post_status_shape_and_missing`, M9 도구 4번째 추가 → `test_mcp_lists_three_read_only_tools` | 통과 |

## 병합 시 PM 조치 (1건)

- `pyproject.toml`에 `mcp` 의존성이 없다(루트 파일은 PM 소유, 빌더가 `"mcp>=2.2,<3"`을 제안). `tests/e4/test_mcp_server.py`가 최상단에서 `mcp`를 import하므로, `mcp`가 없는 환경(새 클론, Codex 쪽)에서는 `verify.py`의 pytest 수집이 실패한다. 병합할 때 PM이 추가한다. 1.x를 깔면 `mcp.server.mcpserver`가 없어 import에서 실패하므로 하한 `>=2.2`가 필요하다.

## 비차단 권고

1. E2-L0·E1-L2는 아직 main에 없어 이 브랜치의 테스트·verify는 어댑터 경로로 돈다. 위 3번 (b)로 모듈 경로도 동작함(11 passed, hybrid 검색)을 확인했지만, 두 브랜치 병합 뒤 `pytest tests/e4 -k mcp`를 한 번 다시 돌린다(기대 `backend`가 자동으로 모듈 쪽으로 바뀌어 검사됨).
2. 첫 hybrid 검색이 약 15.6초다(색인+bge-m3 적재). 서버는 시작 때 백그라운드로 미리 읽지만, 클라이언트 도구 호출 제한이 15초보다 짧으면 첫 호출이 끊길 수 있다(빌더 보고서에도 적혀 있음).
3. 공지 DOI가 없는 사후상태 레코드는 `notice_url=null`이다(실데이터에 kind 4종 모두 이런 레코드가 있음). `source_url`(데이터셋 CSV)은 항상 있어 "결과마다 출처 URL"은 지켜지지만, 공지 링크가 없는 경우라는 점이 필드로는 드러나지 않는다.
4. 300자 상한은 휴리스틱이다. 300자 이하의 계획서 발췌는 통과한다(설계 의도: 검색어만). 도구 스키마에 없는 추가 인자는 오류 없이 버려진다(무해).
