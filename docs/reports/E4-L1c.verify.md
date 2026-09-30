# E4-L1c 검증 보고서 — 근거 열람 패널·평가이력 지도 (화면 L1)

**PASS**

- 검증자: Claude Sonnet 5.5 (빌더 Opus 5.5와 다른 모델) · 대상: `task/E4-L1c` @ 9ca1897 (worktree `.claude/worktrees/s2-E4-L1c`)
- 방법: 서버 8137(`NEUMANN_LLM_PROVIDER=mock`, `OPENAI_API_KEY` 미전달) + Playwright 1440×900을 **내가 새로 쓴 스크립트**로 돌렸다(빌더의 `test_view_shots.py`를 그대로 쓰지 않음). 빌더 스크립트는 패널 인용을 fixture 값과만 비교하므로, 나는 색인 원문(`data/index/excerpts.jsonl`·`reviews.jsonl`)과 코퍼스 결정 파일(`processed/decisions.jsonl` 등)을 직접 읽어 대조했다. 서버는 끝나서 종료했다(8137 LISTEN 없음). 8010은 건드리지 않았다(다른 프로세스가 쓰는 중).
- 병합 전 필수 수정: 없음. 아래 "가벼운 지적"은 병합 뒤 처리해도 된다.

## 완료 기준별 결과

| # | 항목 | 실행 · 실제 출력(핵심) | 판정 |
|---|---|---|---|
| 1a | 인용 = 결과 오프셋 원문(글자 단위) | 서버 실흐름(mock, 색인 실물)으로 `/premortem/view`를 3개 계획서(plan·plan_elife_neuro·plan_medimaging)에 호출 → 근거 **53건 전부**: `ev.q == excerpts.jsonl.text == reviews.jsonl[source_id].text[start:end]` 53/53, `off == [start,end]` 53/53, `sha == sha256(q)[:16]` 53/53. 브라우저 패널 DOM(`#evQuote.textContent`)은 plan.md 결과의 근거 13건을 이전/다음 버튼으로 전부 훑어 색인 원문 조각과 13/13 일치. 표본 5개(#1 662–726, #4 762–873, #5 530–697, #9 13–89(메타리뷰), #13 3296–3599)를 색인에서 직접 잘라 대조: 전부 `eq=True` | 통과 |
| 1b | 결정·평점 = 코퍼스 값 그대로 | 근거 53건: 패널 결정 라벨이 `decisions.jsonl`의 `outcome`(accept_poster→Poster, reject→거절, accept_oral→Oral, accept_spotlight→Spotlight)과 53/53 일치, 평점은 그 심사평 `rating`의 앞자리 숫자와 53/53 일치(원문 `"8: accept, good paper"`는 `rtraw`·툴팁에 보존). 논문 30편: 결정 30/30 일치, `rs`(심사 평점 점들) = 공식 심사평 평점 집합 30/30, `r` = 그 평균(예 GRAIN [5,6,6,5,6] → 5.60). 메타리뷰(#9)는 평점 없음 → 패널에 평점 줄 자체가 없음(지어내지 않음). 거절된 논문에 8점(#4)도 있는 그대로 표시. 코퍼스에서 한 논문에 서로 다른 결정이 있는 경우 0건 | 통과 |
| 1c | 원문 링크 | 패널 `#evLink.href` = 색인 `source_url` 13/13, `target=_blank rel="noopener noreferrer"`, `javascript:`/`data:` 링크 0 | 통과 |
| 1d | 계획서 줄 강조 | 근거 13건 모두 `#evLines .pline` ≥1개 + 상단 스트립 `.c.sel`(예 #1 → 11·21·22행). 계획서 탭 전환 시 선택 근거의 줄이 `.l.sel`로 밑줄 강조(스크린샷 확인) | 통과 |
| 1e | 평가이력 지도 | 유사 연구 10편 표(결정·평점 점·논문별 근거 번호 #n·원문 링크), 결정 분포 막대 "3 거절 · 7 Poster", "공식 심사 평점 · 거절 평균 3.38 · 채택 평균 5.95"(직접 계산: (2+4.75)/2=3.375 ✓) | 통과 |
| 1f | 예상 심사평·체크리스트는 있을 때만 | 서버 실결과(둘 다 없음): 섹션 `s-summary·s-map·s-cards·s-trace·s-plan`만, 목차에 III·IV 없음. 규칙 경로로 예상 심사평·체크리스트를 붙인 결과: `s-review`·`s-check`와 목차 III·IV 표시 | 통과 |
| 1g | 콘솔 오류·외부 요청 | 서버 실흐름: 콘솔 error 0, pageerror 0, 실패 요청 0, 요청 14건 전부 `127.0.0.1:8137`(외부 호스트 0). 조작·풍부 뷰 5개 장면에서도 각각 0 | 통과 |
| 2a | 샘플에 코퍼스 값을 섞지 않음 | `_sample_result()`→`build_ui_view(sample=True)`: `default_records` 호출 0회, `_status.records=None`, 논문 결정 전부 "미정"·평점 "–". **실제 코퍼스 work_id를 넣은 샘플 결과**(work_id=`researcharcade_hf:7bAjVh3CG3`, sample=True)도 "미정"·평점 없음(호출 0). 같은 입력을 sample=False로 주면 Poster·5.60이 채워지고 `_status.records.filled`에 개수가 남음. 결과 값이 있으면 결과가 우선(`dsrc:'result'`). (참고: 호출자가 `records=`를 직접 넘기면 샘플에도 적용되는데, `main.py`는 넘기지 않고 빌더 스크린샷은 fixture 기록을 넘긴 것이라 코퍼스를 섞은 것이 아님) | 통과 |
| 2b | mock·비상 규칙 경고가 패널 상단에 남음 | 서버 mock 실결과: 근거 13건 전부 패널 첫 요소가 `#panelWarn` = "일부 단계 강등 · mock provider 3장", 리포트 상단 알림에 "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다". 규칙 경로 예상 심사평(비샘플)은 결과 status가 degraded로 오르고 패널 경고 + 알림에 `expected_review · degraded · llm_call_not_provided`, `checklist · degraded · … 규칙 문구로 대신함`. 심사평 머리에 "규칙 합성 · 비상 경로 / 상태 degraded · 사유", 체크리스트 행마다 생성 방식. 샘플은 패널 경고에 "분석 결과 아님 · 공용 fixture(가짜 데이터)" | 통과 |
| 2c | 리뷰어 신원 없음 | 코퍼스 `reviewer_pseudonym` 0건, 실결과 `ev.rv` 전부 "". 결과에 `reviewer_pseudonym="John Smith (MIT)"`, `reviewer_name`, `reviewer_id`를 넣어도 뷰 JSON 어디에도 안 나옴(패턴 `PSEUDONYM`만 통과, 기존 로직). 패널에는 "익명 유지"만 | 통과 |
| 3 | XSS | ① `build_ui_view`에 `<img src=x onerror=…><script>…</script><b id=pwn>`을 계획서 줄·제목·결정·평점·venue·인용·평점·리뷰어·카드 제목·심사평 문장·`gate`·`status`·`reason`·`model`·체크리스트 항목·`verify`·note에 넣고 `javascript:` URL(work url, source_url) ② 실서버 뷰의 **모든 문자열 값**에 같은 페이로드를 덧붙인 원시 ui_view(+`u`는 전부 `javascript:`) 를 응답 가로채기로 주입. 근거 전부 훑기·계획서 탭·체크리스트 결정 클릭·인용 클릭 후: `window.__xss` 미정의, `img`·`#pwn` 0개, `a[href]` 중 `javascript:`/`data:` 0(전부 `http(s)`·`#`), 다이얼로그 0, 페이로드는 글자 그대로 화면에 보임. `on*` 속성 1개는 기존 `PDF` 버튼 `onclick="window.print()"`(정상 장면과 동일) | 통과 |
| 4 | 계약 | `jsonschema.Draft7Validator(contracts/ui_view.schema.json)`: 서버 실결과 3개(plan·elife·med) 오류 0, 규칙 경로 fixture 뷰(샘플·비샘플)·심사평 없는 뷰 오류 0. `git diff main...task/E4-L1c -- contracts src/neumann/models.py` 빈 결과(변경 없음). 추가 키(`ev.lns/cards/kind/rtraw`, `works.draw/dsrc/rs`, `review.gen/st/why/model`, `checklist.set/ln/ev/…`, `_status.records/verification`)는 스키마가 허용하는 선택 키이고 계약 추가 제안은 보고서 "제안"에만 있음 | 통과 |
| 5a | `pytest tests/e4 -q -k view` | `33 passed, 1 skipped, 92 deselected in 2.98s` | 통과 |
| 5b | `python scripts/verify.py` | `880 passed, 16 skipped in 72.20s` · 보안 파일 291개 · 계약 2개 · 테스트 통과 · `verify 통과` · exit 0 | 통과 |
| 5c | 소유 밖 변경 | `git diff main...task/E4-L1c --stat`: 13개 파일 — `src/neumann/api/view.py`, `src/neumann/webui/index.html`, `tests/e4/test_view_panel.py`, `tests/e4/test_view_shots.py`, `docs/reports/E4-L1c.md`, `docs/reports/E4-L1c_*.png` 8장. 소유 밖 0, `contracts/`·`models.py` 변경 0, 데이터·비밀값 파일 추가 0(PNG는 스크린샷 허용 범위) | 통과 |
| 5d | index.html 범위 | 변경 6개 hunk: CSS 한 블록(`.doclines` 다음, 새 셀렉터만: `.evh·.plbl·.pline·.pwarn·.pcard·.dist·.distl·.rdots·.ck .sub·.rev .gh·.tablewrap`), `dec`/`docLines` 헬퍼, `distHtml·rdots·workEv·renderReport·panelWarn·markSel·renderPanel`. 입력 화면 렌더·고지 영역·`.strip` 등 기존 규칙 수정 0. 새 CSS 클래스가 입력 화면 마크업에서 쓰이지 않음(grep) | 통과 |
| 5e | 병합 충돌 | `git merge-tree --write-tree HEAD task/E4-S06` → 충돌 없음. **task/E4-S06은 이미 main에 병합됨(08f32c5)**이라 `git merge-tree --write-tree HEAD main` → 충돌 없음(트리 52a5fd1). 병합 결과의 index.html을 실제로 렌더(응답 가로채기): 입력 화면에 S06 "외부 전송 · OpenAI API(gpt-6-astra)로 전송 … 자세히" 고지 그대로, 리포트·근거 패널 정상, 콘솔 오류 0·외부 요청 0. `git merge-tree --write-tree HEAD task/E4-L2d` → 충돌 없음(L2d는 `serving.py`·`export.py` 등, `view.py`·`index.html` 미변경, `build_ui_view` 미사용) | 통과 |
| 6 | 테스트가 항상 통과하지 않는가 | 임시 복사본(`AppData/Local/Temp`)에서 view.py를 9가지로 망가뜨려 `test_view_panel.py`+`test_e4_view.py` 29건 실행: 샘플에 기록 섞기·인용 공백 축약·기록이 결과 결정을 덮어씀·리뷰어 통과·체크리스트 `set` 항상 참·카드 순위 제거·평점 출처 오류·연결 줄 1개로 축소 → **8건 모두 실패(잡힘)**, 1건 생존(아래 지적 2) | 통과 |

## 스크린샷 육안 확인(내 렌더)

- 리포트 근거 패널: 패널 맨 위 "일부 단계 강등 · mock provider 3장", `#1 · R2 …`, 인용(세리프 따옴표), 논문·출처·결정 "채택 · Poster"·평점 "6 / 10 · 익명 유지"·원문 링크·검증(오프셋 662–726 · sha256 · 원문 대조 13/13), 계획서의 대응 문장 11·21·22행(붉은 밑줄), 이 근거를 쓴 위험카드, 같은 지적 목록.
- 평가이력 지도: 결정 분포 막대(3 거절 / 7 Poster), 평균 평점, 평점 점, 근거 번호. 예상 심사평: 규칙 합성 경고·감사 수치·게이트 이름.

## 가벼운 지적(병합을 막지 않음)

1. **생성 방식 라벨의 프로토타입 키**: `genLabel`이 `GEN[g]`를 그대로 조회해서 `gen`이 `"constructor"`·`"toString"`이면 `<span class="gen constructor">function Object() { [native code] }</span>`처럼 보인다(실제 렌더로 확인). XSS는 아니고 조작·오류 값의 표시 문제다. `Object.prototype.hasOwnProperty.call(GEN, g)`로 막으면 된다(`view.py`도 `review.gen`을 `GENERATORS` 밖이면 16자 잘라 그대로 통과시킴).
2. **테스트 하나가 판별력이 약함**: `test_view_panel.py`의 "메타리뷰 제외 평균" — 테스트 데이터의 메타리뷰 평점이 `None`이라 `kind == "official_review"` 조건을 지워도(변이 M4) 통과한다. 실제 코퍼스의 메타리뷰 1,068건은 평점이 전부 비어 있어 지금 동작에는 영향이 없다. 평점 있는 메타리뷰를 한 건 넣어 두면 된다.
3. **논문 평점 표기**: 지도의 논문 평점(5.60)은 공식 심사평 평점의 평균이고 "거절/채택 평균"은 그 논문 평균들의 평균(심사평 수 가중 없음)이다. 화면에 "평균"이라 밝히고 점으로 개별 값을 보이므로 정직성 문제는 아니나, 발표 때 "코퍼스 평점 그대로"라고 말하면 안 된다(평균은 파생값, 개별 평점·결정은 원문 그대로).
4. 스크린샷 8장 중 5장은 fixture 뷰를 응답 가로채기로 넣은 장면(빌더가 보고서에 밝힘). 서버 실흐름은 mock provider 결과다. 실제 astra 결과 화면은 v1 연결 후 다시 찍어야 한다(빌더 "못 한 것"과 동일).

## 재현

```
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 NEUMANN_LLM_PROVIDER=mock \
  NEUMANN_RAW_DIR=".../공개자료" NEUMANN_DATA_DIR=".../project_neumann/data" NEUMANN_EMBED_MODEL=".../models/bge-m3"
python -m uvicorn neumann.api.main:app --port 8137        # OPENAI_API_KEY 없이
python -m pytest tests/e4 -q -k view ; python scripts/verify.py
git diff main...task/E4-L1c --stat ; git merge-tree --write-tree HEAD main
```
검증 스크립트는 `AppData/Local/Temp/l1cv/`에만 두었고 빌더 worktree에는 파일을 남기지 않았다(`git status` 깨끗).
