# SEC-6 검증 보고서 (독립 검증자, Claude Sonnet 5.5)

- 대상: `task/SEC-6` HEAD `38a87be`(worktree `.claude/worktrees/s2-SEC-6`, 389d773 `queries._HEADING`, b664a66 `templates.HEADING`, 38a87be 보고서). 기준 main은 검증 중 `29d96ee` → `c4f4b12` → `04a54af`로 움직였고, 병합 시험은 `04a54af`로 했다.
- 코드·git 쓰기 없음. 임시 파일은 전부 스크래치 폴더(`…/scratchpad/v6/`)에만 만들었다. 빌더 worktree에는 아무것도 남기지 않았다(`.pytest_cache/`는 빌더가 21:25에 만든 것, gitignore 대상).

## 최종 판정: **PASS**

병합 전 필수 조치 없음. 아래 "발견"의 권고는 병합을 막지 않는다. 검증자 쪽 절차 이탈 1건은 맨 아래에 밝힌다.

## 완료 기준별 결과

| # | 항목 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1 | 선형성(빌더와 다른 입력) | `perf.py`: 100만 자 × 공백 종류 12가지(스페이스·`\t`·`\u3000`·`\xa0`·`\x0b`·`\x0c`·`\u2003`·`\u2009`·`\x85`·`\u2028`·`\r`·`\x1c`) × 3모양(`# a`, `## a`, `## 1. a`), 무작위 혼합 공백, `#`·공백 교대 5종, 줄바꿈 없는 100만 자(글자만·`#`만·공백만·`# `반복·` #`반복), CRLF 4종, `\r`만, 들여쓰기 3·4칸 줄, `#######`, 제목 줄 수십만 개. 대상은 `_headings`·`templates.sections`·두 정규식 `finditer` | 제목 찾기 최댓값 0.0057 s(줄바꿈 없는 글자만 100만 자). CRLF `#\r\n`×33만 줄 0.149 s, `# a\r\n`×20만 줄 0.114 s. `scale.py`로 25만→400만 자 재면 지수 1.0~1.05(되돌림 없음, 선형). 옛 정규식은 내가 다시 재도 `# a`+`\t`×1000 = 1.28 s, `\u3000`×1000 = 4.26 s(세제곱), 옛 templates는 N=10,000에 0.78 s | **통과** |
| 2 | 정상 마크다운 차등 | `diffq.py`(내 생성기, 빌더 것과 다름): 정상 문서 20,000건 → `plan_axis_queries`·제목 목록 차이 **0건**(kwargs 변형 3종 15,000회도 0). `real_md.py`: 저장소·기획서 폴더 md·txt 198개 → `plan_axis_queries` 차이 0, `templates.sections` 차이 0. 전 유니코드 0x110000개에서 `\s` = `str.isspace` = `[^\S\n]`(줄바꿈 제외) 일치(불일치 0) | 빈 제목 줄이 섞인 문서에서만 차이(3,735/20,000) | **통과** |
| 2b | "새 쪽이 CommonMark에 맞다" | `oracle.py`: `markdown-it-py`(CommonMark 파서)로 만든 기준 결과와 `plan_axis_queries` 비교(ASCII 공백, 코드 펜스 없는 문서 20,000건씩) | 빈 제목 없음: 옛 0·새 0 불일치. 빈 제목 비율 0.1: **옛 2,192건 불일치 / 새 0건**. 0.25: **옛 3,241건 / 새 0건**. 빌더가 든 5개 모양(`#\n방법`, `# \n#### 데이터 수집`, `# 데이터\n##\n본문`, `# ###`, `######` 뒤 본문 줄)도 markdown-it 결과가 새 쪽과 같다 | **주장 타당** |
| 2c | 제품 영향 | 5절 호출 그래프 + 런타임 측정 | 축 추출(`plan_axis_queries`)은 서빙에서 안 불림 → 서빙 영향 0. 템플릿 목록은 서버 소유 파일 11개에서 옛=새 | **영향 없음** |
| 3 | `GET /templates` 서빙 결과 | `serve_templates.py`: FastAPI TestClient로 `GET /templates`와 `GET /templates/{id}` 8개(골격 5 + 예시 3) + 없는 id 404를 main 스냅샷(`04a54af`)과 브랜치에서 각각 받아 JSON 저장 | 두 JSON 파일 바이트 동일(`cmp` 통과, sha256 앞 16자 `d17802ef01726074`), 상태 200·항목 5+3·404 동일. `tpl_files.py`: 실제 파일 11개(골격 5·예시 2·`tests/fixtures/plans` 4) 각각 `sections()`·`plan_axis_queries` 옛=새, CRLF 원문도 동일. 독립 무작위 차등(`diff_tpl.py`) 6만 건: 차이는 전부 이름이 빈 `##` 줄이 있는 문서, 그런 줄이 없으면 0건(31,687건) | **통과** |
| 4 | 남은 위험이 서빙에서 사용자 입력에 닿는가 | 아래 5절 | 닿는 것 없음 | **통과** |
| 5a | main 최신과 병합 충돌 | 병합 기준 `55fcc23`. `git diff 55fcc23..main --stat -- <SEC-6 5개 파일>` 출력 없음(main 쪽 변경 82커밋이 이 파일들을 안 건드림), 옛식 `git merge-tree` 충돌 표지 0, 다른 `task/*`·`integ/*` 브랜치 중 `queries.py`·`templates.py`를 건드리는 것 없음. main의 두 파일 = 빌더 기준본(`cmp` 동일) | 충돌 없음 | **통과** |
| 5b | 전체 pytest | (가) 브랜치 worktree에서 `scripts/verify.py`. (나) main `04a54af` + SEC-6 5개 파일을 얹은 스냅샷(`git archive`, 스크래치)에서 `pytest -q` | (가) `1252 passed, 46 skipped in 156.67s`, `보안: 파일 409개`, `계약: 2개`, `테스트: 통과`, `verify 통과`, exit 0. (나) `1416 passed, 26 skipped in 272.39s`, exit 0. SEC-6 관련 5개 파일만 따로: `112 passed, 1 skipped` | **통과** |
| 6 | 계약·범위 | `git diff main...task/SEC-6 --stat` | 5개 파일: `docs/reports/SEC-6.md`, `src/neumann/api/templates.py`(E4 소유), `src/neumann/index/queries.py`(E2 소유), `tests/e0/test_sec6_*.py` 2개. `contracts/`·`models.py` 변경 없음, 데이터·비밀 파일 없음(verify 보안 검사 통과) | **통과**(E2·E4 소유 파일 수정은 PM 지시라고 보고서에 적혀 있음. 과제 파일 `docs/tasks/SEC-6.md`가 없어 내가 확인은 못 함) |
| 7 | 테스트가 항상 통과하는가 | 스냅샷 복사본에 결함 3가지를 심어 SEC-6 테스트 실행: (a) 닫는 `#` 안 벗김, (b) ASCII 공백만 인정, (c) 다음 줄을 제목으로 삼는 옛 동작 | 셋 다 즉시 실패(`test_random_normal_markdown_same_as_old` 2건, `test_documented_differences` 1건). 시간 상한 테스트는 옛 세제곱 정규식이면 100만 자에서 끝나지 않는 방식이라 실패 방식은 정지 | **통과** |

## 5절. 남은 위험 호출 그래프 확인 (항목 4)

대상: `sentences.py`의 `_TOKEN_BEFORE`·`_WORD_BEFORE`(실제 제곱)·`_LEADING_MARKER`·`_AFTER_SPACE_START`·`_AFTER_BULLET`·`_ENUM_ONLY`, `models.EMAIL_RE`, 새 `_HEADING_LINE`·`templates.HEADING`.

정적(스냅샷 = main `04a54af` + SEC-6, `src/`·`scripts/` 텍스트 검색과 AST):
- `index.sentences`를 가져오는 곳은 `index/store.py:28` 하나(테스트 제외). 거기서 쓰는 `excerpts_for_reviews`는 `IndexStore.from_corpus`(store.py:108)에서만 불리고, `from_corpus` 호출자는 `scripts/build_index.py:163`과 `store.build_store_from`뿐이다. `build_store_from`은 `src/`·`scripts/`에 호출자가 없다(테스트만). 서버가 쓰는 `IndexStore.load`(`api/mcp_server.py:399`, `search.py`)는 이 경로를 안 탄다. `analyze/backend.py`의 `split_sentences`는 같은 이름의 별개 함수(fixture 전용, 자체 정규식 `_SENT_END`).
- 동적 import는 `api/main.py`(라우터·파이프라인), `api/meta.py:391`, `api/serving.py`, `scripts/precompute_demo.py`, `scripts/build_index_calibrate.py:209`뿐이고 `neumann.index.sentences`를 이름으로 불러오는 곳은 없다.
- `plan_axis_queries`(옛 `_HEADING` 쓰는 함수) 호출자는 `scripts/build_index_calibrate.py:209`(오프라인)와 테스트뿐이다. main 최신에도 서빙 쪽 호출자 없음.
- `templates.HEADING`은 `sections()`에서만 쓰이고, `sections()`는 카탈로그 검사(`catalog_errors`)와 `_template_item`·`get_template`에서 서버 소유 파일(골격·예시 폴더 두 곳, 카탈로그 id에서만 찾음)에만 돈다. 요청 문자열로 파일 경로를 만들지 않는다.
- `EMAIL_RE`는 `models.email_spans`(.match 창 한정)와 `analyze/pii.py:258`(창 한정)에서만 쓰인다. 200,000자 적대 입력 8종에서 `email_spans` 최악 0.137 s.

런타임(`runtime.py`, 스냅샷, mock provider, 실색인·bge-m3 로드): `sys.setprofile`로 모든 `re.Pattern` 메서드 호출을 기록하면서 4.5만 자짜리 적대 계획서(공백·`\u3000`·`# a`+공백, `#`·공백 교대, `a. B`×3000, `._`×3000, `AA`+`mZ`×3000, `A@A.A.AA`+`_`×3000, ` - `+`\u3000`×3000 포함)로 `POST /premortem/view`, `POST /premortem`, `POST /premortem/jobs`, `POST /upload/plan`(md·txt), `GET /templates`·`/taxonomy`·`/config/weights`·`/health`·`/queue/status`·`/premortem/precomputed`·`/api`를 호출했다(모두 200/202; 작업 엔드포인트는 내 TestClient 하네스에서 `error`로 끝났고 **수정 없는 main 스냅샷에서도 같다** → SEC-6과 무관). 259개 정규식이 호출됐고:

```
_AFTER_SPACE_START  호출 없음     _AFTER_BULLET  호출 없음     _TOKEN_BEFORE  호출 없음
_WORD_BEFORE        호출 없음     _ENUM_ONLY     호출 없음     _HEADING_LINE  호출 없음
옛 _HEADING·옛 templates.HEADING  호출 없음(당연)
EMAIL_RE            .match 23회, 호출처 models.py:email_spans 뿐(창 한정)
templates.HEADING   .finditer 30회, 호출처 templates.py:sections 뿐(GET /templates, 서버 파일)
```

결론: 서빙 경로에서 사용자 입력에 닿는 남은 위험은 없다. (`_LEADING_MARKER`도 `sentences._trim` 계열이라 같은 오프라인 경로.)

추가로 빌더 기준(55fcc23) 이후 main에 들어온 정규식(`serving.py`·`jobs.py` 오류문 정리·경로 마스킹 등, 모듈 수준 23개)을 3,000·6,000회 반복 펌프 입력 약 1,500모양으로 재봤다: 초선형 표시 0개.

## 발견

1. (참고, 병합 무관) 빈 제목 줄 100만 자(`#\n`×50만)에서 `_headings`·`_HEADING_LINE.finditer`가 0.20~0.25 s로 지시의 0.2초 선을 살짝 넘는다. 되돌림이 아니라 일치 50만 개를 만드는 선형 비용이다(지수 1.05, 400만 자에서 0.75 s). 빌더 테스트도 이 모양은 1.5초 상한(`test_many_headings_1m_linear`)으로 따로 잰다. 붙여넣기 상한 20만 자에서는 약 0.04 s라 서빙 영향 없음.
2. (참고) 빈 제목이 섞인 비정상 마크다운에서 결과가 옛날과 달라진다. 옛 쪽이 다음 줄을 제목으로 삼거나 `##` 줄을 앞 제목에 먹이던 버그 성격이라 새 쪽이 맞다. 다만 `# 데이터\n##\n본문`처럼 사용자가 빈 `##` 줄을 자리표시로 둔 문서는 본문이 데이터 절에서 빠진다(CommonMark와 동일). 서빙 경로에서 `plan_axis_queries`를 부르지 않으므로 현재 영향 0. 나중에 서빙에 붙일 때 알아 둘 것.
3. (권고) 오프라인 제곱 2곳(`_TOKEN_BEFORE`·`_WORD_BEFORE`)은 서빙과 무관하다는 보고서 주장이 맞다. 다만 새 코퍼스로 색인을 다시 만들기 전(E2)에 뒤에서부터 걷기로 바꾸는 편이 좋다(보고서 "다음 과제"와 같음).
4. (참고) 옛 `_HEADING`은 서빙에서 안 불렸지만 모듈은 서빙 프로세스에 올라와 있다(`search.py`가 `normalize_axis`를 가져옴). 미래에 붙이는 사람이 밟을 함정이 이번에 제거됐다는 보고서 서술은 코드와 맞다.

## 병합 전 필수 조치

없음.

## 검증자 절차 이탈(밝힘)

- 지시의 "모든 명령 `NEUMANN_LLM_PROVIDER=mock`" 중 **한 번** 어겼다. 작업 엔드포인트 확인용 `job1.py`를 처음 돌릴 때 이 변수를 명령에 붙이지 않았고, 셸에 물려받은 값은 `openai`였다. `NEUMANN_LIVE_LLM_OK`가 없어 SEC-3 관문이 provider를 mock으로 강등했고("provider=openai 요청됐으나 NEUMANN_LIVE_LLM_OK 없음 → mock") 그 실행은 색인 단계에서 `IndexNotBuilt`로 실패했다. 실제 OpenAI 호출은 없었다. 이후 재실행은 모두 mock을 명시했다. 그 밖에 변수를 명시하지 않은 명령은 정규식·템플릿 모듈만 가져오는 스크립트(`oracle.py`, `tpl_files.py`, `diff_tpl.py`, `real_md.py`, `old_t.py`)이고 LLM 경로를 타지 않는다. `NEUMANN_LIVE_LLM_OK`는 한 번도 켜지 않았고 `.env`는 열지 않았으며 키 값은 출력·기록하지 않았다. 이 이탈을 엄격히 FAIL로 보실지는 PM이 판단해 주세요. SEC-6 코드에 대한 판정에는 영향이 없다.

## 재현 파일(스크래치, 커밋 안 함)

`C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Desktop---------\ab440ac0-8275-44a8-8bcd-b86e972dbc78\scratchpad\v6\`: `perf.py`·`scale.py`(선형성), `diffq.py`·`oracle.py`·`diff_tpl.py`·`tpl_files.py`·`real_md.py`(차등·CommonMark 기준), `serve_templates.py`(`tpl_main.json`·`tpl_branch.json`), `runtime.py`·`an_runtime.py`·`callgraph.py`(호출 그래프), `email_t.py`, `fuzz_new.py`, `mutate.py`, `verify_branch.log`, `pytest_merged.log`, `old_queries.py`·`old_templates.py`(main `55fcc23` 원본 추출).
