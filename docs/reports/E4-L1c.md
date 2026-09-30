# E4-L1c — 근거 열람 패널·평가이력 지도(화면 L1)

- 빌더: Claude Opus 5.5 · 브랜치 `task/E4-L1c`(main f636fad에서 시작, main bc7d011까지 병합) · 검증: Sonnet 5.5
- 소유 범위만 고침: `src/neumann/api/view.py`, `src/neumann/webui/index.html`의 리포트·근거 패널 부분(CSS 한 블록 + `renderReport`·`renderPanel`과 그 헬퍼), `tests/e4/test_view_panel.py`, `tests/e4/test_view_shots.py`, 이 보고서와 스크린샷

## 무엇을 했나

### build_ui_view (`src/neumann/api/view.py`)
1. **결정·평점 기록 조회 `RecordLookup`**: 계약상 `SimilarWork`·`Excerpt`에는 결정·평점·논문 id가 없다. 그래서 파이프라인 결과만으로는 지도·패널이 늘 "미정"·"–"였다. 이제 코퍼스 기록(Decision·ReviewEvent·Work)에서 **원문 그대로** 조회한다.
   - 기본값 `records=AUTO`: 메모리에 이미 올라온 색인(`neumann.index.store._STORE`)을 먼저 쓰고(추가 IO 없음), 없으면 공유 데이터 폴더 `index/works.jsonl`·`index/reviews.jsonl`을 읽는다. 결정은 `processed/decisions.jsonl`·`processed/elife_decisions.jsonl`·`processed_l3/decisions.jsonl`. 파일 mtime으로 캐시한다(실측 첫 로드 0.19초, 결정 2,627·심사평 5,366·논문 1,128·평점 4,298건).
   - **결과 값이 우선**이다(`similar_works[].decision`·`rating`이 오면 그것). 기록에서 채운 값은 `dsrc`, 원문 문자열은 `draw`·`rtraw`로 남기고 개수를 `_status.records`에 적는다(추적 섹션에 표시).
   - **샘플이면 조회하지 않는다**(가짜 fixture에 실제 기록을 섞지 않음). `records=None`이면 끈다.
   - 논문 평점 = 그 논문 **공식 심사평** 평점(앞자리 숫자)의 평균. 메타리뷰는 뺀다. 하나하나는 `rs`.
   - 발췌 → 논문: 명시 `work_id` > **`source_id`(review_id·decision_id) → 기록의 work_id** > URL 대조 순. 유사 연구 밖 논문(확장 검색)도 제목·학회·결정을 기록에서 찾는다(`x` 표시는 유지).
2. **근거(`ev`) 추가 키**: `lns`(이 발췌를 인용한 카드들의 계획서 줄 전부), `cards`(인용 카드 순위), `kind`(원문 종류), `rtraw`. 인용 `q`는 결과 `text` 그대로(가공 없음), `off`·`sha` 그대로.
3. **예상 심사평(E3-L1a 출력)**: 목업 `{t, c}` + 문장별 `ln`·`cards`, 섹션에 `gen`(astra/rule/mock)·`st`·`why`·`model`, `audit.gate`. 근거 번호로 풀리지 않는 문장은 기존대로 뺀다.
4. **체크리스트(E3-L1b 출력)**: 목업 `{id, t, r, s, m}` + `ln`·`ev`·`card`·`v`(확인 조건)·`gen`·`why`(규칙 대체 사유)·`cv`·`set`. `decision=None`이면 `s`는 계약상 기본값 "보류"지만 `set=false`로 "결정 전"임을 남긴다.
5. `_status.verification`(원문 대조 `quotes_verified/total` + `verify_evidence` 단계 상태), manifest `llm_model`·`llm_provider` 별칭(모델 표시), 결정 라벨에 `DecisionOutcome` 매핑(대폭/소폭 수정 등). `kpi.n_accept`는 채택 계열(채택·Oral·Spotlight·Poster)만 센다.

### 화면 (`index.html` 리포트·패널)
- **근거 열람 패널**(목업 `Evidence.dc.html` 구성): `#n · 위험 유형` 머리 + 이전/다음 근거, "심사평 원문 · 축자"(원문 종류별), 인용, 논문(유사 n번/확장 검색)·출처·결정·평점(익명)·원문 링크·검증(오프셋·sha256·원문 대조 기록), **계획서의 대응 문장**(연결 줄 전부, 강조), 이 근거를 쓴 위험카드(생성 방식 표기), 같은 지적 목록(결정·평점).
- **연결된 계획서 줄 강조**: 근거를 고르면 상단 스트립 칸(`.sel`)과 계획서 탭 줄이 함께 강조된다.
- 패널 맨 위에 **샘플·강등·비 astra 생성 표시**를 늘 둔다(리포트 상단 알림이 스크롤로 사라져도 남음).
- **평가이력 지도**: 결정 분포 막대 + 범례(편수), 거절·채택 평균 공식 심사 평점, 논문별 평점 점(심사평 하나하나, 1–10), 논문별 근거 번호(누르면 패널).
- **예상 심사평**: 생성 방식·모델·상태·사유 줄, 감사 수치(게이트 이름), 문장이 0개여도 생성 기록이 있으면 섹션을 보인다. 없으면 숨김(목차에서도).
- **체크리스트**: 행동 아래 계획서 줄·근거 번호·카드·생성 방식·확인 조건. 결정 전 항목은 칩에 "결정 전 · 기본값 보류" 툴팁.
- **추적**: Records(결정·평점 기록 출처와 채운 개수), Verify(원문 대조).
- 원문·LLM 출력은 모두 `esc()`로 넣는다. URL은 `http(s)`만(`safeUrl`). 새 CSS는 디자인 규칙 토큰만 쓰고 한글에 모노·자간·uppercase 없음(숫자 범례만 모노).

## 완료 기준별 측정

### 1. Playwright 1440×900 스크린샷 · 콘솔 오류 0 · 외부 요청 0 (포트 8132)

```
export PYTHONIOENCODING=utf-8 PYTHONPATH="src;." HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  NEUMANN_DATA_DIR=".../project_neumann/data" NEUMANN_EMBED_MODEL=".../models/bge-m3" NEUMANN_RAW_DIR=".../공개자료"
python tests/e4/test_view_shots.py --port 8132 --out docs/reports      # exit=0
```

출력 요약(전체 JSON은 스크립트가 출력):

```
shots ['E4-L1c_server_default.png', 'E4-L1c_server_map.png', 'E4-L1c_server_evidence.png', 'E4-L1c_map.png',
       'E4-L1c_evidence.png', 'E4-L1c_evidence_plan.png', 'E4-L1c_review.png', 'E4-L1c_check.png']
console_errors []   page_errors []   failed_requests []   external_requests []   requests_total 44
problems []
server_default: header '분석 파이프라인 연결 · v0.0.1'
  notice '일부 단계 강등 / mock provider(테스트용) 결과 — 실제 astra 분석이 아니다'
  map_rows 10, dist '3거절 7Poster 공식 심사 평점 · 거절 평균 3.38 · 채택 평균 5.95'
  cards 3, card_gens ['mock provider'×3]
  records 'corpus_records · works_decision 10 · works_rating 9 · evidence_rating 12'
  panel: #1 … 결정 채택 · Poster, 평점 6 / 10 · 익명 유지, 원문 openreview.net/forum?id=7bAjVh3CG3&noteId=MLZYjk5HVY,
         검증 오프셋 662–726 · sha256 510ad2ad3973e1fa · 원문 대조 13 / 13 · verify_evidence ok,
         계획서의 대응 문장 11행·21행·22행, 이 근거를 쓴 위험카드 카드 01 mock provider
evidence(fixture 뷰): quote == 결과 ev["1"].q, strip_sel [16, 17], plan_sel 16·17행, next '#2'
review: '규칙 합성 · 비상 경로 / 상태 degraded · llm_call_not_provided …', sentences 2, cites 12, check_rows 4
xss: flag None, injected 0, js_links 0 (인용이 글자 그대로 '<img …><script>…' 로 보임)
```

- 서버 기본 흐름: main에 병합된 파이프라인이 **mock provider**로 실제 색인을 돈 결과다. 스크립트가 서버 하위 프로세스에 `NEUMANN_LLM_PROVIDER=mock`을 주고 `OPENAI_API_KEY`를 넘기지 않는다(실제 OpenAI 호출 0). 화면에 "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"와 카드마다 "mock provider"가 남는다. 결정·평점은 코퍼스 기록 조회 값(실제 ICLR 결정·심사 평점).
- 나머지 장면: 공용 fixture(가짜) + E3 규칙 경로 예상 심사평·체크리스트(LLM 없음) + fixture 기록 결정을 `/premortem/view` 응답 가로채기로 넣었다. `sample=True`라 샘플 표시가 리포트·패널에 남는다.
- 서버는 끝나면 종료(8132 LISTEN 없음 확인). 8010은 쓰지 않았다(스크립트가 8010을 거부).

| 파일 | 장면 |
|---|---|
| `E4-L1c_server_default.png` | 서버 기본 흐름 리포트 상단(mock 표시) |
| `E4-L1c_server_map.png` | 실제 색인 10편 평가이력 지도(결정 분포·평균 평점·평점 점·근거 번호) |
| `E4-L1c_server_evidence.png` | 실제 심사평 인용 근거 패널(결정·평점·원문 대조 13/13·대응 줄 3개) |
| `E4-L1c_map.png` | fixture 지도(거절·Poster·대폭 수정) |
| `E4-L1c_evidence.png` | fixture 근거 패널 + 샘플 표시 |
| `E4-L1c_evidence_plan.png` | 계획서 탭: 선택 근거의 16·17행 강조 |
| `E4-L1c_review.png` | 예상 심사평(규칙 합성 · 비상 경로, degraded 사유) |
| `E4-L1c_check.png` | 체크리스트(줄·근거·카드·생성 방식) |

### 2. 테스트

```
python -m pytest -q tests/e4/test_view_panel.py tests/e4/test_e4_view.py tests/e4/test_view_shots.py
29 passed, 1 skipped   (test_view_shots는 NEUMANN_UI_SHOTS=1일 때만)
```

`test_view_panel.py`(12건): 결정·평점 조회(결과 우선, 원문 보존, 메타리뷰 제외 평균), 기록 없으면 비움, **샘플에는 기록을 섞지 않음**(`default_records` 호출 0), 근거 인용 축자·오프셋·연결 줄·카드 순위·확장 검색 논문, 지도 칸, E3-L1a·b 규칙 경로 **실제 출력**의 목업 형식 변환과 생성 방식(`rule`·`degraded`·사유), 결정 전 체크리스트 `set=false`, 데이터 없을 때 숨김, fixture 기록, `default_records` 파일 읽기(깨진 줄 무시, 폴더 없으면 None).

### 3. verify

```
python scripts/verify.py
880 passed, 16 skipped in 74.36s
보안: 파일 291개 / 계약: 2개 / 테스트: 통과 / verify 통과
```

## main 병합·충돌

- `git merge main` 두 번(0ae4a3b, 339713b · main bc7d011) — 충돌 없음. main의 `index.html`은 f636fad 이후 바뀌지 않았다.
- 입력·고지 빌더(E4-S06) 브랜치는 아직 main에 없다. 미리보기 `git merge-tree --write-tree HEAD task/E4-S06`(149d56f) → 충돌 파일 없음. 내 CSS는 리포트 영역(`.doclines` 다음)에, JS는 `renderReport`·`renderPanel`·그 헬퍼에만 넣었다.

## 바꾼 파일

- `src/neumann/api/view.py` — RecordLookup·default_records, 근거·심사평·체크리스트 추가 키, 상태 블록
- `src/neumann/webui/index.html` — 리포트·패널 CSS 블록, `dec()`·`docLines()`, 지도·심사평·체크리스트·추적·패널 렌더
- `tests/e4/test_view_panel.py`(신규), `tests/e4/test_view_shots.py`(신규, Playwright)
- `docs/reports/E4-L1c.md`, `docs/reports/E4-L1c_*.png` 8장

## 결정(스펙이 모호해서 고른 것)

- **결정·평점 출처**: 결과 계약에 없어서 코퍼스 기록을 조회하기로 했다(main.py는 소유 밖이라 `build_ui_view` 기본값 `AUTO`로 자동 적용). 결과 값이 있으면 결과가 이긴다. 기록에서 채운 사실·개수는 `_status.records`와 추적 섹션에 표시.
- **논문 평점** = 공식 심사평 평점 앞자리 숫자의 평균(ICLR 1–10). 개별 값은 점으로 보여 준다. eLife처럼 평점이 없으면 "–".
- **수정 결정**(major/minor revision): 채택도 거절도 아닌 "대폭/소폭 수정"(앰버), 채택 수에 넣지 않는다.
- **체크리스트 미결정**: 계약 enum 때문에 `s="보류"`를 두되 `set=false`로 구분(화면 툴팁).
- **예상 심사평 문장 끝 마침표**: 목업처럼 인용 번호 뒤에 마침표를 한 번만 찍는다(문장 끝 마침표를 옮김, 문장 내용은 그대로).
- **목업의 설명 문구**("채택된 논문도 같은 질문을 받았습니다 …")는 05_디자인_규칙 §6(설명문 금지)과 조건부 사실이라 넣지 않았다.
- 스크린샷의 풍부한 장면은 fixture 뷰를 응답 가로채기로 넣었다(서버 파이프라인이 LLM 없이 예상 심사평·체크리스트를 만들지 않으므로). 샘플 표시를 유지한다.

## 제안(계약 추가만, PM 판단)

1. `SimilarWork`에 `decision`(원문)·`decision_outcome`·`rating_mean`·`ratings` — 지금은 화면이 기록을 다시 조회한다.
2. `Excerpt`에 `work_id`, 심사평 `rating`(원문) — 지금은 `source_id`로 기록을 찾는다.
3. `ui_view.schema.json`에 `ev.lns`·`ev.cards`·`works.rs`·`review.gen`·`checklist[].set` 등 이번 추가 키와 `_status` 정의(선택 키).

## 못 한 것 · 다음

- 실제 astra 결과 화면은 찍지 않았다(과제 규칙: 실제 OpenAI 호출 금지). v1 연결 후 astra 결과로 같은 스크립트를 돌리면 된다(서버 env만 바꾸면 됨).
- 체크리스트 결정 변경은 화면 안에서만 순환(저장·결정 로그 기록은 L2).
- 모바일 폭(<1180px)은 기존 드로어 동작만 확인 없이 유지했다(스크린샷은 1440×900만).
- 첫 요청 때 색인이 메모리에 없으면 기록 파일(심사평 19 MB)을 한 번 읽는다(실측 0.19초, 이후 캐시).
