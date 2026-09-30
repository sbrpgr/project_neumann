# SEC-6 보고서: 제목 찾기 정규식 ReDoS 제거와 `src/` 정규식 전수 점검

- 빌더: claude-opus-5.5, 브랜치 `task/SEC-6`(main `55fcc23`에서 시작), worktree `.claude/worktrees/s2-SEC-6`
- 모든 명령은 `NEUMANN_LLM_PROVIDER=mock`, `NEUMANN_LIVE_LLM_OK` 없음. 실제 OpenAI 호출 0회. `.env`는 열지 않았다.
- 과제 파일(`docs/tasks/SEC-6.md`)은 없어서 PM 지시문을 기준으로 했다.

## 한 줄 요약

`index/queries.py`의 세제곱 정규식 `_HEADING`을 선형으로 바꿨다(공백 2,000개에 7.5초 → 100만 자에 0.02초 이하). 전수 점검에서 서빙 경로(api·pipeline)에 걸린 것은 `api/templates.py`의 `HEADING`(제곱) 하나뿐이었고 같은 방식으로 고쳤다. 나머지 초선형 정규식 7개는 모두 오프라인(색인 만들기) 경로이거나 선형으로만 쓰이는 곳이라 표로만 남긴다.

## 무엇을 했나

1. **`src/neumann/index/queries.py`** — `_HEADING = ^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$`(re.M)를 없애고 `_HEADING_LINE = ^[^\S\n]{0,3}#{1,6}(?:[^\S\n]([^\n]*))?$`(re.M) + `_headings()`로 바꿨다.
   - 정규식은 줄 앞머리(들여쓰기 0~3칸, `#` 1~6개, 공백 한 칸)만 맞춘다. 되돌림은 `{0,3}`·`{1,6}`로 상한이 있고, `[^\n]*`는 줄 끝까지 한 번에 가서 `$`가 바로 맞는다 → 입력 길이에 선형.
   - 제목 끝의 공백·닫는 `#`은 문자열로 벗긴다: `rest.strip().rstrip("#").rstrip()`. 이것은 옛 정규식의 `(.+?)\s*#*\s*$`가 남기던 제목과 같다(파이썬 `str.strip()`의 공백과 정규식 `\s`는 유니코드 전 범위에서 같음을 확인했다).
   - `plan_axis_queries()`는 새 `_headings()`를 쓰고, 축이 없는 절은 본문을 자르기 전에 건너뛴다(결과는 같고 제목이 많은 글에서 빠르다).
2. **`src/neumann/api/templates.py`**(서빙 경로 `GET /templates`, `GET /templates/{id}`) — `HEADING = ^##\s+(?:\d+\.\s*)?(.+?)\s*$`(re.M, 제곱)를 `^##[^\S\n]([^\n]*)$`로 바꾸고 번호(`1.`)·공백은 `sections()`에서 문자열로 벗긴다.
3. **테스트 2개 파일**(`tests/e0/`, SEC-4와 같은 자리)
   - `test_sec6_heading_linear.py`: 옛 구현 복사본과 차등 비교(고정 계획서 4개, 무작위 정상 마크다운 400건, 무작위 한 줄 20,000개), 차이 나는 모양 5개를 기대값으로 고정, 100만 자 적대 입력 13종.
   - `test_sec6_templates_heading.py`: 실제 골격·예시·계획서 11개와 무작위 500건 차등 비교, 차이 모양 4개 고정, 100만 자 적대 입력 7종.
4. **전수 점검**: `src/` 정규식 427개(아래 표)를 정적 후보 찾기 + 적대 입력 실측으로 점검했다.
5. **호출 그래프**: `_HEADING`을 쓰는 함수가 서빙 경로에서 불리는지 확인했다(아래 4절).

## 1. `_HEADING` 선형화 — 전후 시간

옛 정규식(`list(OLD.finditer(text))`, 스크래치 `old_times.py`):

| 모양 | N=250 | N=500 | N=1,000 | N=2,000 |
|---|---|---|---|---|
| `"# a" + " "×N + "b"` | 0.014 s | 0.105 s | 0.855 s | **7.503 s** |
| `"# a" + "\t"×N + "b"` | 0.019 s | 0.157 s | 1.448 s | 8.708 s |
| `"# a" + "\u3000"×N + "b"` | 0.022 s | 0.164 s | 1.220 s | 9.099 s |

N이 2배일 때 시간이 약 8배 → 세제곱. SEC-4 검증자는 N=4,000에서 55~87초를 쟀다. 100만 자라면 끝나지 않는다.

새 구현(100만 자, 3회 중 최소, 스크래치 `perf_heading.py`):

```
모양                           길이        _headings  plan_axis_queries
#a+spaces+b                  1,000,004   0.0003s    0.1218s
#a+tabs+b                    1,000,004   0.0003s    0.1190s
#a+(space#)+b                1,000,004   0.0003s    0.1223s
#a+(# )+b                    1,000,004   0.0003s    0.1293s
#a+spaces+#s+spaces+b        1,000,003   0.0003s    0.1213s
#+newlines+x                 1,000,002   0.0202s    0.0186s
#+spaces+newline-mix         1,000,004   0.0174s    0.0168s
hashes only                  1,000,000   0.0055s    0.0053s
spaces only                  1,000,000   0.0053s    0.0054s
newlines only                1,000,000   0.0178s    0.0186s
#space repeated              1,000,000   0.0014s    0.1219s
heading lines ("# a\n"×25만) 1,000,000   0.1338s    0.2767s
empty heading lines ("#\n"×50만) 1,000,000 0.2016s  0.2435s
#a+ideographic spaces+b      1,000,004   0.0009s    0.1497s
4-space + # lines            1,000,000   0.0128s    0.0134s
```

- 제목 찾기(옛 `_HEADING` 자리)는 공백·`#` 반복 적대 입력 100만 자에서 모두 0.02초 이하다.
- `plan_axis_queries` 전체가 0.12초 남짓인 것은 100만 자짜리 제목에 축 키워드 정규식 4개(`데이터|자료|data|dataset` 등, re.I)를 돌리는 시간이다. 선형이고 이번 과제에서 바꾸지 않았다.
- 제목 줄이 수십만 개인 글(마지막 두 줄 위)은 되돌림이 아니라 제목 수만큼 파이썬 반복이 도는 선형 비용이다(100만 자에 0.2~0.3초).

## 2. 차등 테스트 — 옛 결과와 같은가

스크래치 `diff_heading.py` 출력(시드 고정):

```
한 줄 성질 위반: {} {}
[정상] 문서 1000건: plan_axis_queries 차이 0건, 제목 목록 차이 0건
[빈 제목·#만 줄 섞음] 문서 1000건: plan_axis_queries 차이 161건, 제목 목록 차이 783건
[실제 md] 파일 169개: plan_axis_queries 차이 0건, 제목 목록 차이 0건
```

- 한 줄 성질: 무작위 한 줄 200,000개(`#`, 공백, 탭, `\u3000`, `\xa0`, `\r`, 글자)에서 옛 정규식이 글자가 있는 제목을 내면 새 구현도 같은 제목을 낸다. 다른 것은 내용이 없거나 `#`뿐인 제목 줄뿐이다(아래).
- 정상 마크다운: 제목 1~6단, 들여쓰기 0~3칸, 닫는 `#`, 끝 공백, `\r\n`, `C#`, `#hashtag`, 4칸 들여쓴 `#`, `#######`, 코드 줄 속 `# 주석`을 섞은 1,000건 → 차이 0.
- 실제 마크다운 169개(저장소 `docs/**/*.md` 129개, 고정 계획서 4개, 기획서 폴더 36개, 기획서는 읽기만) → 차이 0.
- 차이는 **빈 제목 줄**(`#`, `# `, `##`, `# ##`)이 있을 때만 난다. 어느 쪽이 맞는지:

| 입력 | 옛 결과 | 새 결과 | 맞는 쪽 |
|---|---|---|---|
| `#\n방법\n본문` | 제목 `방법`(다음 줄을 제목으로 삼음) | 빈 제목 하나, `방법`은 본문 | **새 쪽**. 옛 `#{1,6}\s+`의 `\s`가 줄바꿈을 넘었다. CommonMark에서 `#`만 있는 줄은 빈 제목이고 다음 줄은 문단이다 |
| `# \n#### 데이터 수집\n본문` | 제목 `#### 데이터 수집` 하나, 이것이 문서 제목으로 topic에 들어감 | 빈 1단 제목 + `데이터 수집` 4단 제목 | **새 쪽** |
| `# 데이터\n##\n본문` | `##` 줄이 앞 제목에 먹혀 `본문`이 데이터 절 | `##`가 빈 제목이라 `본문`은 버려짐 | **새 쪽**(CommonMark). 다만 옛 쪽이 사용자가 기대한 결과였을 수도 있다. 정상 문서에는 이런 줄이 없다 |
| `# ###` | 제목 `#` | 빈 제목 | 새 쪽(CommonMark: `### ###`은 빈 제목) |
| `## 평가\n…\n######\n데이터 누수 점검 계획은 없다.` | 본문 줄 `데이터 누수…`가 `데이터` 절 제목이 돼 그 뒤가 data 질의로 들어감 | 빈 제목 뒤 본문으로 버려짐 | **새 쪽**. 옛 쪽은 본문 문장을 절 제목으로 잘못 읽었다 |

위 모양은 모두 `test_sec6_heading_linear.py`의 `test_documented_differences`·`test_empty_heading_does_not_steal_next_line`에 기대값으로 고정했다.

`api/templates.py` 차등(테스트 안에서 실행): 실제 파일 11개(골격 5, 예시 2, 고정 계획서 4)와 무작위 500건(번호 `1.`·`12.`·`١.`, 탭·`\u3000`, `###`·`##없음`·들여쓴 `##` 섞음) 차이 0. 차이는 `##\n방법`(옛: 다음 줄 `방법`을 칸 이름으로), `## \n## 2. 평가`(옛: `## 2. 평가`), `## 1.   `(옛: 공백 한 칸 `" "`), `##  `(옛: `" "`)뿐이고 모두 새 쪽이 맞다.

templates 전후 시간(`"## a" + " "×N + "."`): 옛 N=5,000 0.156 s · 10,000 0.865 s · 20,000 3.269 s · 40,000 15.329 s(제곱) → 새 N=1,000,000 0.0004 s.

## 3. `src/` 정규식 전수 점검

### 방법(스크래치 폴더, 커밋 안 함)

- **모으기**: `re._compile`에 기록 훅을 걸고 `neumann` 모든 모듈을 임포트(모듈 수준 정규식, 데이터로 만드는 키워드 정규식 포함 402개) + AST로 `re.*()`에 문자열을 바로 넘긴 곳 92개 중 임포트로 안 잡힌 것 17개 + 함수 안에서만 컴파일되는 `rules._PLAN_CUES` 8개 = **427개**. 함수 안에서 동적으로 만드는 4곳(`fitness._en`, `rules.plan_lines_for`, `researcharcade.keyword_regex`, `retraction._keyword_patterns`)은 실제 값으로 모두 잡혔다(모두 이스케이프한 낱말 나열 + `\b`/둘레 검사).
- **정적 후보**: 파싱 트리에서 ① 중첩 무한 수량자(`(a+)+`, `(?:\s+\w+)*`), ② 선택 요소만 사이에 둔 글자 집합이 겹치는 인접 무한 수량자(`(.+?)\s*#*\s*$`), ③ 고정되지 않은 앞머리 무한 수량자(`search`에서 제곱 후보) → 29개.
- **실측**: 패턴마다 패턴 글자로 만든 앞머리(최대 10개) × 펌프 글자(패턴 글자 + 공통 30자 + 반복 몸통 + 두 글자 조합, 최대 약 100개) × 끝 글자 3종 = 300~1,500 모양을 N=400과 N=800에서 `finditer`로 재고(3회 중 최소), 2.8배 넘게 늘고 0.5 ms 넘는 모양을 표시했다. 모양 하나가 20초 넘게 안 끝나면 따로 띄운 프로세스를 죽이고 기록했다. 표시된 패턴은 N=5,000~40,000으로 다시 재서 지수(시간 ∝ Nᵏ)를 구했다.
- 검출력 확인: 옛 `_HEADING`(k≈3, 모양 80개 표시)·옛 templates `HEADING`(k≈1.9)·SEC-4가 찾은 `EMAIL_RE`·`sentences._TOKEN_BEFORE`를 모두 잡았고, 새 `_HEADING_LINE`은 1,200 모양 중 표시 0개였다.

### 서빙 경로란

`api/main.py` → 선택 라우터(`api.export`, `api.upload`, `api.precomputed`, `api.templates`, `api.meta`) + `PIPELINE_MODULE = "neumann.pipeline"` → 그 아래 `analyze/*`, `llm`, `models`, `config`, `index.search`·`index.store`(→ `index.queries`, `index.sentences`, `index.taxonomy`, `index.bm25`). 모듈 기준으로는 `sources/*`와 `api/mcp_server`만 빠진다. 그래서 모듈이 아니라 **요청 처리 중에 실제로 그 함수가 불리는지**로 나눴다.

### 결과: 초선형으로 표시된 것 8개(+ fullmatch에서만 지수 1개)

| 위치 | 패턴 | 적대 입력 실측(`finditer`) | 코드의 실제 쓰임 | 서빙 경로? | 조치 |
|---|---|---|---|---|---|
| `index/queries.py:53` (옛 `_HEADING`) | `^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$` | `"# a"+" "×2,000+"b"` 7.5 s, k≈3 | `finditer`(계획서 전문) | 아니오(4절) | **고침** → 0.0003 s/100만 자 |
| `api/templates.py:40` (옛 `HEADING`) | `^##\s+(?:\d+\.\s*)?(.+?)\s*$` | `"## 1. a "+"\u3000"×N+"!"`: 1만 0.83 s, 2만 3.0 s, 4만 11.3 s, k≈1.9 | `finditer`(서버 소유 골격·예시 파일) | **예**(`GET /templates`, 입력은 서버 파일) | **고침** → 0.0004 s/100만 자 |
| `index/sentences.py:33` `_AFTER_SPACE_START` | `\s+["'“‘(\[]?[A-Z0-9]` | `" "+"\u3000"×N`: 1만 1.26 s, 2만 5.4 s, k≈2 | `.match(line, pos)` 고정 위치(구두점마다, 공백 구간이 서로 안 겹침) → 선형 | 아니오(색인 만들기 `store.from_corpus`, fixture backend) | 표로만 |
| `index/sentences.py:35` `_AFTER_BULLET` | `\s*[-*•]\s` | `" - "+"\u3000"×N`: 2만 2.9 s, 4만 9.3 s, k≈1.7 | `.match(line, pos)` → 선형 | 아니오 | 표로만 |
| `index/sentences.py:37` `_TOKEN_BEFORE` | `[\w.]*$` | `"._"×N`: 2만 3.5 s, 4만 13.5 s, k≈1.9 | `.search(line, 0, pos)` → **실제로도 제곱** | 아니오(리뷰 코퍼스) | 표로만 |
| `index/sentences.py:41` `_LEADING_MARKER` | `(?:[-*•+>]+\s*|…)+` | `match`·`finditer`는 40만 자 0.005 s 이하. **`fullmatch`만 지수**(`"*"×22` 0.48 s, 4자마다 약 16배) | `.match(text, s, e)` → 선형 | 아니오 | 표로만(잠재: 끝 고정·fullmatch로 바꾸면 지수) |
| `index/sentences.py:44` `_WORD_BEFORE` | `([A-Za-z][A-Za-z.]*)$` | `"AA"+"mZ"×N`: 2만 1.45 s, 4만 6.3 s, k≈2.1 | `.search(line, 0, dot_pos)` → **실제로도 제곱**: `split_sentences("a. B"×N/4)` 6천 자 0.15 s, 1.2만 0.51 s, 2.4만 2.43 s | 아니오 | 표로만 |
| `index/sentences.py:45` `_ENUM_ONLY` | `\s*(?:[-*•]\s*)?\(?(?:\d{1,2}|…)` | `" "+"\n\t"×N`: 1만 3.3 s, 2만 14.3 s, k≈2.1 | `.fullmatch(line, start, pos)` 구간 한 번 → 선형 | 아니오 | 표로만 |
| `models.py:44` `EMAIL_RE` | `[A-Za-z0-9._%+\-]+@…` | `"A@A.A.AA"+"_"×N`: 2만 0.49 s, 4만 1.6 s, k≈1.7 | `email_spans`·`pii`에서 `@` 둘레 구간 `.match`만(SEC-4) → 선형 | 쓰는 곳은 예, 쓰임은 선형 | 표로만(SEC-4 주석 있음) |

### 정적 후보였지만 실측에서 선형인 서빙 경로 정규식(200,000자 적대 입력, 실제 연산, 스크래치 `serving_candidates.py`)

```
rules._EN_PHRASE finditer          입력 4종(최대 200,002자) 최악 0.0381s
gate._NUM_RE finditer              입력 4종(최대 200,001자) 최악 0.0265s
gate._THOUSANDS_RE match           입력 2종(최대 200,003자) 최악 0.0134s
gate._ENUM_PREFIX_RE sub(count=1)  입력 4종(최대 200,002자) 최악 0.0263s
cards._NUM findall                 입력 2종(최대 200,000자) 최악 0.0076s
cards L-ref sub                    입력 3종(최대 200,004자) 최악 0.0645s
cards._SENT split                  입력 2종(최대 200,003자) 최악 0.0119s
view.RATING_NUM match              입력 2종(최대 200,021자) 최악 0.0032s
view.MD_HEADING match              입력 2종(최대 200,010자) 최악 0.0022s
templates.sections (새)             입력 2종(최대 1,000,005자) 최악 0.0014s
queries._headings (새)              입력 2종(최대 1,000,004자) 최악 0.0014s
```

- 이들은 중첩·겹침이 있어도 사이에 반드시 소비하는 구분 글자(`.`, `,`, `\s+` 뒤 글자 등)가 있거나 뒤에 실패할 요소가 없어 되돌림이 폭발하지 않는다. 퍼저에서도 표시 0개.
- `taxonomy`의 `\b…\w*\b[^.]{0,70}\b(…)` 7개는 `{0,70}` 상한이 있어 선형(퍼저 최악 0.1 ms/800자). `researcharcade.py:223` `PROFILE_ID_RE`(중첩)는 `_`로 구분돼 선형이고 오프라인 수집 코드다.
- 나머지 398개(taxonomy 키워드 97, researcharcade 키워드 163, rules 67 등)는 정적 후보도 아니고 퍼저 표시도 없다.
- `webui/index.html`의 JS 정규식 6개(`/^#+\s*/`, `/[.。]\s*$/`, `/\.([a-z0-9]+)$/` 등)는 브라우저에서 돌고 모두 한 번 훑기로 끝나 문제 없다.

## 4. `_HEADING` 호출 그래프 — 서빙 경로에서 불리나

```
_HEADING(지금 _HEADING_LINE)
  └ _headings()                     index/queries.py
      └ plan_axis_queries()         index/queries.py
          ├ scripts/build_index_calibrate.py:209   (오프라인 검색 보정 스크립트, params에 axes가 있을 때
          │                                          __import__("neumann.index.queries")로 가져옴)
          ├ tests/e2/test_e2_l1_search.py
          └ tests/e0/test_sec6_heading_linear.py
```

- **서빙 경로에서는 불리지 않는다.** `api/`, `pipeline.py`, `analyze/`, `index/search.py` 어디도 `plan_axis_queries`를 부르지 않는다. 모든 로컬 브랜치(`git grep`)에서도 다른 호출처는 없다.
- 다만 모듈 `neumann.index.queries`는 서빙 프로세스에 올라와 있다: `api/main.py`(EVIDENCE 목록) → `neumann.index.search` → `from neumann.index.queries import normalize_axis`. 서빙은 `normalize_axis`만 쓴다. 누군가 붙여넣기 계획서를 축 질의로 나누려고 `plan_axis_queries`를 파이프라인에 붙이면 옛 정규식은 즉시 ReDoS가 됐을 것이다(붙여넣기 상한 20만 자, 공백 2,000개면 7.5초). 이번 수정으로 그 위험은 없어졌다.

## 완료 기준별 명령과 출력

```bash
# 공통 환경
export NEUMANN_LLM_PROVIDER=mock PYTHONPATH="src;." PYTHONUTF8=1 PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
unset NEUMANN_LIVE_LLM_OK NEUMANN_LIVE_TESTS
```

1. 선형 재작성 + 차등 테스트: 위 1·2절. 테스트 실행
   `python -m pytest tests/e0/test_sec6_heading_linear.py tests/e2/test_e2_l1_search.py -q` → `57 passed in 3.93s`
   `python -m pytest tests/e0/test_sec6_templates_heading.py tests/e4/test_templates.py tests/e4/test_templates_ui.py -q` → `55 passed, 1 skipped in 8.35s`
2. ReDoS 회귀 테스트: `test_adversarial_1m_heading_scan_under_200ms`(13종, 각 0.2초 미만), `test_adversarial_1m_under_200ms`(templates 7종, 각 0.2초 미만). 옛 구현이면 100만 자 입력은 끝나지 않는다(공백 2,000개에 7.5초).
3. 전수 점검: 3절 표.
4. 호출 그래프: 4절.
5. `python scripts/verify.py` → 아래 "verify" 절.

## verify

첫 커밋 전(`389d773` 내용):

```
1248 passed, 27 skipped in 104.01s (0:01:44)
보안: 파일 407개
계약: 2개
테스트: 통과
verify 통과
```

templates 수정까지 넣은 뒤(`b664a66` 내용, 다른 에이전트가 같이 돌아 느림):

```
1271 passed, 27 skipped in 320.01s (0:05:20)
보안: 파일 408개
계약: 2개
테스트: 통과
verify 통과
```

(부하가 큰 상태에서도 새 시간 상한 테스트는 모두 통과했다.)

## 바꾼 파일

- `src/neumann/index/queries.py` — `_HEADING` 제거, `_HEADING_LINE`·`_headings()` 추가, `plan_axis_queries()`가 새 함수를 씀(E2 소유 파일, PM 지시로 수정)
- `src/neumann/api/templates.py` — `HEADING` 교체, `_SECTION_NUMBER` 추가, `sections()`가 번호·공백을 문자열로 벗김(E4 소유 파일, PM 지시로 수정)
- `tests/e0/test_sec6_heading_linear.py`, `tests/e0/test_sec6_templates_heading.py` — 새 테스트
- `docs/reports/SEC-6.md` — 이 보고서

## 결정(지시가 모호해서 고른 것)

- **공백 종류**: 지시 예시는 `[ \t]`였지만 옛 정규식의 `\s`와 같은 유니코드 공백에서 줄바꿈만 뺀 `[^\S\n]`를 썼다. `#\u3000제목`, `#\xa0제목`(한글 문서에 흔한 전각·줄바꿈 없는 공백)을 옛날처럼 제목으로 읽어 정상 문서 결과를 바꾸지 않기 위해서다. CommonMark는 공백·탭만 인정한다.
- **닫는 `#`**: 옛 규칙대로 끝의 `#`은 앞에 공백이 없어도 벗긴다(`## C#` → `C`). CommonMark라면 `C#`로 남지만 옛 결과를 유지했다. 축 판정에는 영향이 없다.
- **빈 제목 줄**: `#`, `# `처럼 내용이 없는 줄은 제목이 빈 제목 줄로 본다(CommonMark). 옛 쪽도 이런 줄에서 절을 끊었으므로 절 경계는 대개 옛날과 같고, 다음 줄을 제목으로 삼던 버그만 없어진다.
- **templates**: 이름이 빈 `##` 줄은 건너뛰고, `## 1.`처럼 번호 뒤에 이름이 없으면 옛날처럼 `1.`을 이름으로 둔다.
- **시간 상한**: 제목 찾기(`_headings`, `sections`)는 지시대로 100만 자 적대 입력마다 0.2초 미만으로 검사한다. `plan_axis_queries` 전체는 100만 자 제목에 축 키워드 정규식을 돌리는 선형 비용(0.12초 안팎)이 있어, 다른 에이전트가 같이 돌 때 흔들리지 않게 1초 상한으로 따로 검사한다. 제목이 수십만 개인 글은 1.5초 상한(실측 0.25~0.3초).
- **테스트 위치**: SEC-4와 같이 `tests/e0/`.
- **점검 도구는 커밋하지 않았다**: 스크래치 폴더에만 있다(재현용 경로 아래).
- **퍼저 설정 변경**: 처음에는 `finditer`와 `fullmatch`를 함께 쟀는데 `sentences._LEADING_MARKER`가 `fullmatch`에서만 지수 시간이라 퍼저가 멈췄다. `fullmatch`를 쓰는 곳은 `sentences._ENUM_ONLY` 하나뿐이어서 그 뒤로는 `finditer`만 쟀고, 이 둘은 따로 쟀다(3절 표).

## 못 한 것 · 남은 위험

1. **오프라인 제곱 2곳**: `index/sentences.py`의 `_TOKEN_BEFORE`(`[\w.]*$`)·`_WORD_BEFORE`(`([A-Za-z][A-Za-z.]*)$`)는 `search(line, 0, pos)`로 쓰여 실제로도 제곱이다(`"a. B"` 반복 2.4만 자에 2.4초). 리뷰 코퍼스로 색인을 만들 때만 돈다. 지시대로 고치지 않았다(E2 소유, 서빙 아님).
2. **쓰임새가 바뀌면 터지는 것**: `_LEADING_MARKER`는 `fullmatch`나 뒤에 실패할 요소를 붙이면 지수 시간, `_AFTER_SPACE_START`·`_AFTER_BULLET`·`_ENUM_ONLY`는 `search`/`finditer`로 바꾸면 제곱, `EMAIL_RE`는 본문 전체에 돌리면 제곱이다.
3. **퍼저는 증명이 아니다**: 모양을 패턴 글자에서 만들었고 N=400/800 비교라, 아주 긴 앞머리가 있어야 드러나는 경우는 놓칠 수 있다. 정적 후보 29개는 모두 따로 쟀다.
4. 제목이 수십만 개인 100만 자 글에서 `plan_axis_queries`는 0.2~0.3초(선형). 서빙에서 쓰지 않는다.
5. 빈 제목 줄이 있는 비정상 마크다운에서는 결과가 옛날과 다르다(2절 표, 새 쪽이 CommonMark에 맞다).

## 다음 과제에 넘길 것

- E2: `index/sentences.py`의 `_TOKEN_BEFORE`·`_WORD_BEFORE`를 "뒤에서부터 걷기"(문자열로 `pos` 앞 글자를 거꾸로 훑기)로 바꾸면 선형이 된다. 공개 코퍼스를 새로 받아 색인을 다시 만들기 전에 하면 좋다.
- 서빙 코드에 새 정규식을 넣을 때: `(.+?)\s*$`처럼 게으른 수량자 뒤에 겹치는 `\s*`를 두지 말고, 줄 단위로 앞머리만 맞춘 뒤 `strip()`으로 벗기는 방식(이번 두 곳)을 쓴다.

## 재현 파일(스크래치 폴더, 커밋 안 함)

`C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Desktop---------\ab440ac0-8275-44a8-8bcd-b86e972dbc78\scratchpad\sec6\`
`diff_heading.py`(차등), `perf_heading.py`·`old_times.py`(시간), `sec6_rec.py`·`import_all.py`·`make_extra.py`(정규식 모으기), `static_scan.py`(정적 후보), `fuzz_worker.py`·`fuzz_driver.py`(적대 입력 실측), `measure_flagged.py`·`measure_130.py`·`serving_candidates.py`(재측정), `import_graph.py`(모듈 그래프). 결과: `patterns.json`, `fuzz_out.json`, `fuzz_extra_out.json`, `static.json`.
