# E5-L2a 보고서 — 백테스트 데이터셋·일반 LLM 기준선·모델 중립 판정 실행기

- 브랜치 `task/E5-L2a`, 빌더 Claude Opus 5.5
- 사전 고정 커밋: `8eb01ec`(규칙 코드·프롬프트·테스트를 **표본을 뽑기 전에** 커밋). 그 뒤에 실데이터로 표본·계획서·제외 목록·기준선 3편을 만들었다.
- 데이터 산출물은 공유 데이터 폴더(`C:/Users/User/Desktop/project_neumann/data/eval/`)에만 있다. 커밋하지 않았다.

## 무엇을 했나

| 파일 | 내용 |
|---|---|
| `eval/backtest_common.py` | 사전 고정 상수(시드 20260930 계열, 30/15/10편, 부트스트랩 2000), 경로, 코퍼스 얇은 어댑터(`load_corpus` 있으면 그것, 없으면 JSONL) |
| `eval/backtest_sample.py` | 표본 30편: 강한 층 → 적격 → 거절·채택 층화, 비례 교차 배열(앞 15편 = 축소 표본), 셔플 짝, 사람 판정 10편, 목록 sha256, 덮어쓰기 방지 |
| `eval/backtest_plans.py` | 드롭형 스크러빙(05_eval_protocol 정규식 NUM·CLAIM·EVID 원문 + URL), 잔여 0 검사(0이 아니면 멈춤), 400자 미만 표시 |
| `eval/backtest_leakage.py` | `exclude_work_ids`: id 접두어 정규화 ∪ 제목 정규화 ∪ 심사평 해시 → **색인의 work_id 문자열**, 셔플은 i ∪ j, 자기 논문 검색 실측(`--probe-search`), 근거 인용 누출 검사 |
| `eval/backtest_riskset.py` | 위험 묶음 형식(두 시스템 공통), 블라인드 정리(`blind_text`), 문장 세기·자르기, Neumann `PremortemResult` → 위험 3개 + 근거율 |
| `eval/baseline_llm.py`, `eval/prompts/baseline_llm.txt` | 일반 LLM 기준선(gpt-6-astra, 계획서만), 프롬프트 원문 공개, strict JSON, 재시도·자르기, 캐시, 셔플 재사용 |
| `eval/backtest_run_neumann.py` | Neumann 위험 묶음 실행기(E3 `run_premortem` + 제외 목록), 실행마다 자동 누출 검사 |
| `eval/judge_envelope.py` | 판정 봉투·답 형식(JSON, 모델 무관), 블라인드 검사, 짝 표 분리, 사람 판정 꾸러미(MD·CSV) |
| `eval/judge_run.py` | 판정 실행기: `build` / `briefs`(Claude) / `codex`(비상, 기본 dry-run) / `validate` / `aggregate` |
| `eval/backtest_metrics.py` | precision@3·hit@3·오탐률·특이성·근거율, n + 95% 부트스트랩, 짝지은 차이, 사람 대 AI 일치율·κ |
| `tests/e5/test_backtest_*.py`, `tests/e5/test_judge_*.py` | 9개 파일 50개 테스트(+ 건너뜀 2: 실제 API, E2 검색 미병합) |

## 완료 기준별 측정

환경: `PYTHONPATH="src;."`, `NEUMANN_DATA_DIR=C:/Users/User/Desktop/project_neumann/data`, `C:/Users/User/.venvs/neumann/Scripts/python.exe`.

### 1. 표본 30편·sha256·층화 분포, 계획서 30건·잔여 0

`python -m eval.backtest_sample`

```
코퍼스 1128편(어댑터 e1.load_corpus) 선별 강도 {'multi': 210, 'single': 318, 'title': 600}
→ 적격 765편(강도 {'multi': 199, 'title': 566}), 제외 {'official_reviews_lt_3': 45, 'weak_selection_single': 318}
모집단 층 {'reject': 457, 'accept': 308} 거절 비율 0.5974 · 분야 {'materials_chemistry_molecules': 327, 'physics_pde_climate': 250, 'protein_biology_drug': 422}
표본 30편 층 {'reject': 18, 'accept': 12} · 앞 15편 층 {'reject': 9, 'accept': 6}
분야 {'materials_chemistry_molecules': 7, 'physics_pde_climate': 14, 'protein_biology_drug': 13} · 연도 {'ICLR 2024': 8, 'ICLR 2025': 22} · 강도 {'multi': 6, 'title': 24}
셔플 짝 30쌍(같은 분야 30) · 사람 판정 10편
list_sha256 fdea4d2514fca5357605660003308e25c036b6640d88b8ada3d2033dd0f2905c
reduced_list_sha256 fc5bba1abd670ebf3b2273a1b1e4bdeb6185fdb2090a0f70a339b736ffc50779
file_sha256 574c5387fe6764fdbd4db19f16241a3633bf841639bc9d5744692dd5cbf3ac6c  → data/eval/backtest_sample.json
   1 reject VqEE9i6jhE   2 accept U3PBITXNG6   3 reject SFCHv2G33F   4 accept o1IiiNIoaA   5 reject ihHeqPLRDk
   6 reject qi5dkmEE91   7 accept yUefexs79U   8 reject HB4lr0ykTi   9 accept kbm6tsICar  10 reject mBXLtNKpeQ
  11 reject KszBlT26pl  12 accept 3ep9ZYMZS3  13 reject jHKqr1sDDM  14 accept 5AtlfHYCPa  15 reject YNQF003Ad3
  16 reject p6eQRlaxGo  17 accept rINBD8jPoP  18 reject plAiJUFNja  19 accept BBD6KXIGJL  20 reject jUxzh1bi3i
  21 reject SmZD7yxpPC  22 accept KXrgDM3mVD  23 reject vsLohTBH4h  24 accept uQnvYP7yX9  25 reject 2CYZkawsmz
  26 reject 5LvTfc4fBz  27 accept dl0u4ODCuW  28 reject djmLZkEw1L  29 accept ARQIJXFcTH  30 reject otXB6odSG8
```
(id 접두어 `researcharcade_hf:` 생략.) 사람 판정 10편(앞 15편에서): VqEE9i6jhE, ihHeqPLRDk, qi5dkmEE91, yUefexs79U, HB4lr0ykTi, kbm6tsICar, KszBlT26pl, jHKqr1sDDM, 5AtlfHYCPa, YNQF003Ad3.

- 강한 층 수(600/210/318)가 E1-L0 검증 보고서 값과 같다. 적격 765 = 강한 층 810 − 심사평 3건 미만 45(심사평 없는 논문 포함).
- 층 비율: 모집단 거절 0.5974 → 30 × 0.5974 = 17.9 → 거절 18·채택 12. 앞 15편은 9·6.

`python -m eval.backtest_plans`

```
계획서 30건 · 잔여 패턴 합계 0 · 빈 계획서 0
평균 727.7자 · 보존율 0.5397 · 400자 미만 7건(수동 복구 대상 표시)
지운 문장 사유 {'NUM': 4, 'CLAIM': 71, 'EVID': 40, 'URL': 5}
plans_sha256 88f52c52ff75cf3c4f419bb66a4054203816f62b33653408107001dee6952e06 → data/eval/backtest_plans.jsonl
```
400자 미만 7건: U3PBITXNG6(281), o1IiiNIoaA(287), ihHeqPLRDk(153), jHKqr1sDDM(342), YNQF003Ad3(320), BBD6KXIGJL(128), ARQIJXFcTH(365). 옛 실측(12.8%)보다 높다(23%). 표시만 했고 복구하지 않았다(아래 "못 한 것").

### 2. 누출 회귀: 자기 논문 주입 → 0건

E2 검색은 main에 없다. 그래서 두 가지로 쟀다.

(a) 테스트(`tests/e5/test_backtest_leakage.py`): fixture 논문 6편을 색인 표기(`researcharcade_hf:<id>`)로 넣고 fixture 검색(E2와 같은 약속: exclude는 완전 일치)으로, 표본 쪽 표기(접두어 없음)의 자기 id를 주입.
- 제외 없음: 자기 논문 1위(검사가 의미 있음을 먼저 확인)
- 옛 방식(접두어 없는 id 그대로 완전 일치 제외): 자기 논문 1건 남음 → B-10 재현
- 정규화 제외: 자기 논문 0건, 다른 논문은 그대로 나옴
- 제목만 같은 사본·공백만 다른 심사평 사본도 잡힘
- E2가 main에 들어오면 `test_e2_search_self_injection_zero`가 실제 `search(..., store=...)`로 같은 검사를 한다(지금은 건너뜀)

(b) 실데이터 실측: E2 브랜치 코드(`task/E2-L0`의 `src/neumann`)를 scratch에 풀어 PYTHONPATH로만 얹고, 실색인(`data/index`, 1128편, hybrid bge-m3+BM25)에 30편 계획서를 질의로 넣었다(저장소에는 아무것도 가져오지 않음).

`python -m eval.backtest_leakage --probe-search`

```
색인 1128편(2026-09-30T09:47:25+00:00) · 대상 30편 중 색인에 있음 30
제외 색인 논문 합계 30 · 사유별 {'id': 30, 'review': 30, 'title': 30}
대상 외 추가 일치(동명·같은 심사평) []
검색 실측(k=10, 백엔드 hybrid, 30편): 자기 논문 top-k 제외 없음 30 → 제외 0 (접두어 없는 id 하나만: 30)
sha256 f37504ec46f7127e844d1250671c0a5657c75de1621494d410e95339dd0e2abe → data/eval/backtest_exclusions.json
```
- 스크러빙한 계획서로도 제외 없이는 30편 모두 자기 논문이 top-10(대부분 1위, 최저 5위)에 나온다. 누출 제거가 꼭 필요하다는 뜻이다.
- 접두어 없는 id 하나만 넣으면 30편 모두 새어 나온다(B-10 재현). 정규화 제외는 0.

### 3. mock 판정 답으로 전 과정 + 블라인드 테스트

- `tests/e5/test_judge_run.py::test_end_to_end_mock_answers_to_metrics`: 4편 × 2시스템 × 2조건(카드 2장뿐인 경우 포함) → 봉투 → mock 답 3명(J3은 늘 다르게) → 검증 12/12 → 다수결 → 짝 표 복원 → 지표. 손 계산 값과 일치: Neumann p@3 1/3, hit 1.0, 근거율 7/11, 일반 LLM p@3 1/12, 특이성 0.25·1/12, 차이 0.25(짝지은 CI가 점추정을 감쌈), 축소 표본 필터.
- 누락·오류 답: 봉투 단위로 집계에서 빠지고 목록으로 보고(`test_incomplete_and_invalid_answers_are_reported`).
- 블라인드: `tests/e5/test_judge_envelope.py` — 봉투 JSON(계획서·심사평 제외)에 neumann/baseline/astra/gpt/shuffle/condition/system/evidence/원 id/링크/발췌 id가 없음, 위험이 시스템별로 몰려 있지 않음, 시스템 이름·카드 번호·위험 코드·메타 키를 넣으면 검사기가 잡음, 짝 표를 봉투 폴더에 두면 거부.
- 실데이터 스모크(scratch, 커밋 안 함): 실제 astra 기준선 3편으로 봉투를 만들어 블라인드 위반 0, 심사평 4건씩(8.6~10k자), Claude 지시문 3개, Codex dry-run 명령 9개 확인.

`python -m pytest tests/e5 -q -k "backtest or judge"` → `50 passed, 2 skipped`

### 4. 일반 LLM 기준선 실제 astra 3편

`python -m eval.baseline_llm --provider openai --limit 3 --conditions real --workers 3`

```
provider openai · 요청 모델 gpt-6-astra · effort medium · 프롬프트 6f376a166bc06829
위험 묶음 3건(조건 ('real',)) · 형식 통과 3 · 14.3s
- [real] VqEE9i6jhE status=ok model=gpt-6-astra 위험 3개 (각 2문장)
    1. 그린 함수의 저랭크 표현 가능성 미검증 — DecGreenNet-TT는 그린 함수가 낮은 텐서트레인 랭크로 근사된다는 전제에 의존하지만, …
- [real] U3PBITXNG6 status=ok model=gpt-6-astra 위험 3개 (각 2문장)
    1. 분야 확장만으로는 연구 차별성 부족 — 자연영상 복원에 집중된 기존 연구를 과학 역문제로 확장한다는 동기만 제시되어 있으며, …
- [real] SFCHv2G33F status=ok model=gpt-6-astra 위험 3개 (각 2문장)
    1. 문제 제기만 있고 대체 방법론이 없음 — …
sha256 62c334bbd976297d37b86e901b26b9676f6189f42fa2aeb869d3540a102673b1 → data/eval/riskset_baseline_llm.first3.jsonl
```
- 3편 모두 한 번에 형식 통과(재시도 0, 자름 0). 응답 모델 id `gpt-6-astra`, 지연 14.1~14.3초, 토큰 747~920(추론 90~122).
- 전체 30편 실행은 하지 않았다(PM 지시 후).

### 5. verify

`python scripts/verify.py` → `270 passed, 8 skipped` · `보안: 파일 151개` · `verify 통과`. 데이터 파일은 커밋하지 않았고 프롬프트 원문(`eval/prompts/baseline_llm.txt`)은 커밋했다.

## 판정 봉투 형식

봉투 하나 = 논문 하나(`data/eval/judge/envelopes/env_<12hex>.json`):

```json
{"format": "judge-envelope-v1", "envelope_id": "env_3b1ca162c804",
 "task": "<판정 지시문(한국어)>", "rubric": {"A": "적중 …", "B": "타당 …", "C": "오탐 …"},
 "plan": "<그 논문의 계획서>",
 "reviews": [{"review_no": 1, "text": "<공식 심사평 전문>"}, …],
 "risks": [{"risk_id": "k01", "text": "<제목 — 설명(2문장 이내)>"}, … 최대 12개],
 "answer_template": {…}}
```

- 위험 = Neumann 진짜(계획서 i)·Neumann 셔플(계획서 j)·일반 LLM 진짜·일반 LLM 셔플 각 3개를 섞은 것. 셔플 위험도 계획서 i 봉투에 들어가 판정자는 어느 것이 셔플인지 모른다. 순서는 `random.Random("20260933|<work_id>")`.
- 봉투 id = sha256("20260933|<work_id>") 앞 12자. 형식 이름에도 제품명을 넣지 않았다.
- 비밀 짝 표: `data/eval/judge_key/pairing.json`(봉투 폴더 밖). 위험 id → 시스템·조건·순위·계획서 논문·근거 통과 여부.

답(`data/eval/judge/answers/<J1|J2|J3>/<envelope_id>.json`):

```json
{"format": "judge-answer-v1", "envelope_id": "env_…", "judge_id": "J1", "judge_model": "<실제 모델 id>",
 "judgments": [{"risk_id": "k01", "grade": "A", "review_no": 2, "reason": "<한국어 한 줄>"}]}
```

검증(오류면 그 답은 집계 제외): 형식·봉투 id·판정자 id·모델 id(자리표시 금지)·모든 risk_id 정확히 한 번·등급 A/B/C·이유 한 줄·review_no 범위. 경고: 이유 200자 초과, A인데 review_no 없음.

## 판정 실행기 사용법

판정 전에 경로 하나를 정하고 섞지 않는다(계획서 §5.7).

**Claude 경로(기본)**

1. `python -m eval.judge_run build` → 봉투 30개, 짝 표, 사람 판정 꾸러미(`judge/human/*.md`, `answers_template.csv`)
2. `python -m eval.judge_run briefs --batch-size 10` → `data/eval/judge/briefs/J1_b1.md … J3_b3.md`(판정자별로 봉투 순서를 따로 섞음)
3. PM이 지시문 파일 하나당 Claude Code 서브에이전트(Sonnet 5.5) 하나를 띄운다: "이 파일을 읽고 그대로 수행하라: <brief 경로>". 지시문에는 읽을 봉투·쓸 답 경로·금지(다른 판정자 폴더·짝 표·코드·웹 금지)가 있다. J1·J2·J3는 서로 다른 세션.
4. `python -m eval.judge_run validate` (완전하면 종료 코드 0)
5. `python -m eval.judge_run aggregate [--human data/eval/judge/human/answers.csv] [--work-ids reduced]` → `data/eval/judge_results.json`

**Codex 비상 경로(Claude로 시작할 수 없을 때만)**

- `python -m eval.judge_run codex` → dry-run: 판정자·봉투마다 프롬프트 파일과 명령만 만든다.
- `python -m eval.judge_run codex --execute [--workers 3]` → 실제 실행(PM 지시가 있을 때만). 판정자·봉투마다 따로:
  `codex.exe exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only -C <빈 작업 폴더 J#> --skip-git-repo-check --ephemeral --output-schema <answer_schema.json> -o <answers/J#/env.codex_last.txt> -` (프롬프트 = 지시문 + 봉투 JSON, stdin). codex.exe는 `%LOCALAPPDATA%\OpenAI\Codex\bin`의 최신 것을 자동으로 찾는다. 이미 답이 있으면 건너뛴다.
- 그다음 `validate` → `aggregate`는 같다. 발표·리포트 카드에 "판정자: Codex gpt-6-sol(제품과 같은 회사 모델, 편향 가능성)"을 적는다.

## 전체 백테스트 실행 순서(PM 지시 후)

```
# 0) 이미 끝남(이 과제): 표본·계획서·제외 목록
python -m eval.backtest_sample            # 목록이 바뀌면 덮어쓰지 않는다
python -m eval.backtest_plans
python -m eval.backtest_leakage --probe-search    # E2가 main에 들어온 뒤 다시 돌려 제외 0 확인
# 1) 생성(병렬 가능)
python -m eval.baseline_llm --provider openai                  # 30편 × 진짜·셔플, 계획서 30개만 호출(셔플은 캐시 재사용)
python -m eval.backtest_run_neumann                            # E3 run_premortem + E2 색인 필요, 누출 0이 아니면 종료 코드 1
# 2) 판정
python -m eval.judge_run build
python -m eval.judge_run briefs --batch-size 10                # Claude 경로 (비상: codex --execute)
python -m eval.judge_run validate
# 3) 집계
python -m eval.judge_run aggregate --human data/eval/judge/human/answers.csv
python -m eval.judge_run aggregate --work-ids reduced           # 1차 컷라인(15편)일 때
```

## 결정(스펙이 모호해서 고른 것)

1. **표본 모집단 = 강한 층**(PM 지시 19:00, 결과 산출 전) + 결정이 채택/거절 + 공식 심사평 3건 이상(§4.3). 층화는 거절·채택만(스펙대로). 분야는 층화하지 않았다.
2. **축소 표본이 성립하는 순서**: 층별로 뽑은 뒤 비례 교차 배열 → 어느 길이로 잘라도 거절 비율이 모집단과 1편 안쪽으로 같다. 셔플 짝과 사람 판정 10편도 앞 15편 안에서 고르게 해 컷라인에서도 그대로 쓴다.
3. **계획서에 제목을 넣지 않았다**(논문 식별 정보). **URL 문장도 드롭**(익명 저장소 링크, 스펙의 3종 정규식 밖의 추가 규칙, 드롭만 하므로 누출을 늘리지 않음). 결과: URL로 지운 문장 5개.
4. **셔플 조건**: 계획서 j로 만든 위험을 계획서 i 봉투에 섞는다(판정자가 셔플을 모름). Neumann 셔플 실행은 제외 목록 i ∪ j. 일반 LLM 셔플은 계획서 j 결과를 캐시에서 재사용(입력이 같음).
5. **위험 글 형식 통일**: 두 시스템 모두 `제목 — 설명(2문장 이내)`, 한국어(E3 카드가 한국어 제목 + 1~2문장 설명이라 기준선도 한국어로 맞춤). 같은 정리 함수로 링크·발췌 id·위험 코드·줄 번호(L12)·카드 번호·규칙 표기를 지운다. 2문장 초과는 한 번 재시도, 그래도 넘으면 앞 2문장으로 자르고 표시.
6. **기준선 추론 강도 medium**(E3 카드 합성 기본값과 같게). strict JSON 스키마(위험 정확히 3개)는 형식만 강제하고 내용 힌트는 없다.
7. **판정 입력 심사평 = 공식 심사평만**(메타리뷰·저자 답변 제외: 메타리뷰는 반박 뒤 요약이고 결정을 드러낸다).
8. **빈 자리·실패**: 카드가 3장 미만이면 빈 자리는 적중 아님(분모 3 유지). 시스템이 실패한 논문도 빼지 않고 0으로 센다. 3명 답이 다 없는 봉투는 집계에서 빼고 목록으로 보고.
9. **근거율 분모 = 낸 위험 수**(빈 자리 제외), 논문 재표집 비율 부트스트랩.
10. **A에 심사평 번호(review_no)**를 적게 했다(L3 규칙 "가리킬 문장이 없으면 A가 아니다"의 감사용). 없으면 경고만.
11. Codex 판정 추론 강도 high, 세션 저장 안 함(`--ephemeral`), 답 스키마 강제(`--output-schema`).

## 못 한 것

- **400자 미만 계획서 7건(23%)의 수동 복구**: 표시만 했다. 코퍼스에 초록만 있어 §4.2의 "Introduction에서 목적·방법 복원"을 할 원문이 없다. PM 결정 필요: 그대로 쓸지(짧은 계획서임을 리포트 카드에 표기), 사람이 복원할지.
- **2인 수동 검증(§4.2 3단)**: 하지 않았다(자동 1·2단만). 리포트 카드에 적어야 한다.
- **E2 검색이 main에 없어** 저장소 테스트의 실제 search 회귀는 건너뜀 상태다(E2 병합 후 자동으로 돈다). 실데이터 실측은 E2 브랜치 코드로 scratch에서 돌렸다(위 2-b).
- Neumann 위험 묶음 실행기(`backtest_run_neumann`)는 fake 파이프라인으로만 테스트했다. E3 `run_premortem`이 main에 없어 실제로 돌리지 않았다.
- 기준선 전체 30편, 판정자 실제 실행: 지시대로 하지 않았다.

## 다음 과제에 넘길 것

- E2·E3가 main에 들어오면: `backtest_leakage --probe-search` 재실행(색인이 다시 만들어졌으면 제외 목록 갱신), `backtest_run_neumann --limit 1`로 한 편 확인 뒤 전체.
- 판정자 지시문의 봉투 경로에 `project_neumann`이라는 폴더 이름이 보인다. 어느 위험이 어느 시스템인지는 드러나지 않지만, 더 가리려면 봉투 폴더를 중립 이름의 경로로 옮겨 `paths()`를 바꾸면 된다.
- 리포트 카드(E5-L3)에 적을 조건: 강한 층 765편 모집단, 계획서 23%가 400자 미만, 3단 사람 검증 미실시, 판정자 구성(Claude Sonnet 3명 또는 Codex sol), 사람 판정 10편.
