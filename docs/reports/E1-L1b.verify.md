# E1-L1b 검증 보고서 (Claude Sonnet 5.5)

- 대상: 브랜치 `task/E1-L1b`(worktree `.claude/worktrees/agent-a24401a9648d9d327`, HEAD `d9616f1`), 빌더 보고서 `docs/reports/E1-L1b.md`, 산출물 `data/processed/elife_*`·`europepmc_*`
- 검증일: 2026-09-30 · 검증자는 코드·데이터를 고치지 않았다. 산출물과 캐시는 읽기만 했다. 원문 대조용 원본은 검증자 작업 폴더(scratchpad)에만 받았다.
- 환경: `_COMMON.md`와 같다(`PYTHONPATH="src;."`, Windows Python). 네트워크는 원문 대조 5건(eLife 3, Europe PMC 2)에만 썼고 요청 사이 1초 이상 띄웠다.
- 이 보고서에는 실명을 적지 않는다(공개 저장소에 올라가므로). 남은 이름은 레코드 ID와 유형으로만 적는다.

## 최종 판정: **FAIL (리뷰어 실명 가림 불충분 — 재작업 후 재검증)**

출처 URL 100%, 신원 필드 0, 원문 대조, 테스트, 기존 데이터 무변경은 모두 통과다. 그러나 이 과제의 핵심 불변식인 **리뷰어 실명 가림**이 실데이터에서 깨져 있다. 산출물 전량을 스캔했더니 리뷰어(또는 F1000 심사자)로 보이는 실명이 **심사평 22건, 저자 답변 3건**에 그대로 남아 있다(약 20명). 무작위 30건 표본에서는 하나도 안 걸렸다(누출률이 약 1%라 표본으로는 놓친다). 고칠 범위는 작다(규칙 추가 + 캐시로 `--offline` 재생성, 네트워크 불필요).

| 핵심 근거 | 값 |
|---|---|
| `pytest tests/e1 -k "elife or europepmc"` | 26 passed |
| `python scripts/verify.py` | 327 passed, 2 skipped, 보안 150개 파일, 계약 2개, verify 통과 |
| 출처 URL(전 엔티티 provenance) | eLife 2,722/2,722, Europe PMC 1,928/1,928 = 100%. `source_url`이 해당 API 접두, 딥링크 `url` 있음, 64자 sha·접근 시각 있음 |
| 신원 필드(JSON 키 전수) | 0 (모든 JSONL의 모든 중첩 키에서 name·email·orcid·author·affiliation·reviewer·writer·signature·contrib·participant 등 검색) |
| 구조화 명단(저자·편집자·리뷰어) 전체 이름이 본문에 남은 수 | eLife 0 (21,329회 대조, 예외는 단체명 1건). 명단에 없는 이름은 아래 |
| **본문에 남은 리뷰어 실명** | **심사평 22건 + 답변 3건 (FAIL)** |
| 무작위 5건 원문 대조 | 5/5 (문단 단위 글자 그대로), eLife 3건은 `content_sha256`도 일치 |
| 기존 data/processed(researcharcade)·data/index | 무변경 (아래 §4) |
| 소유 경로 밖 변경 / 계약 변경 / 데이터·비밀값 커밋 | 없음 |

## 1. 완료 기준별 실행 결과

| # | 항목 | 실행한 명령 | 실제 출력(핵심) | 판정 |
|---|---|---|---|---|
| 1 | 소스별 편수·심사평 수·분야 분포 | 산출물 JSONL 직접 집계 + manifest 대조 | eLife works 500 / reviews 1,224 / 답변 499 / 결정 499. Europe PMC 388 / 845 / 307 / 388. 분야 태그 eLife neuro_fmri 434·medical_imaging 229·ml_methods 65, EPMC 202·279·228. 빌더 보고서 수치와 전부 일치. 두 manifest `status: complete`, 엔티티 JSONL 6종×2 sha256·건수가 manifest `outputs`와 12/12 일치. 고아 레코드 0, 심사평 없는 논문 0, 정규화(`normalize_text` 멱등) 위반 0, 논문 ID·제목 중복 0, EPMC에 eLife DOI(10.7554) 0 | 통과 |
| 2 | 무작위 표본 원문 대조 | 내가 짠 코드로 seed 777 표본 5건을 API에서 새로 받아 문단 단위로 포함 여부 확인(빌더 코드 재사용 없음) + eLife 3건은 빌더의 `raw_hash(canonical_json(block))` 함수만 호출해 해시 비교 | 아래 §2. 5/5 일치 | 통과 |
| 3 | pytest, verify | `python -m pytest tests/e1 -q -k "elife or europepmc"`, `python scripts/verify.py` | `26 passed, 98 deselected`, `327 passed, 2 skipped`, 보안·계약·테스트 통과, `verify 통과`(빌더 보고서의 315/14와 개수가 다른 것은 현재 main 병합분 차이) | 통과 |
| 4 | 데이터 커밋 금지 | `git diff main...task/E1-L1b --name-status`, `git ls-files \| grep ^data/` | 추가 파일 7개(소스 2, 스크립트 2, 테스트 2, 보고서 1)뿐. 데이터·`.env`·키 없음. worktree 작업 트리 깨끗 | 통과 |
| 5 | **리뷰어 실명 가림(불변식)** | 산출물 전량 정규식 스캔 + 구조화 명단 대조 + 무작위 30건 직접 열람 | §3. 실명 잔존 25건 | **실패** |

## 2. 원문 대조 (독립 코드, seed 777)

| 레코드 | 종류 | 저장 글자 | 원문 글자 | 저장 문단이 원문에 그대로 있음 | 비고 |
|---|---|---|---|---|---|
| `elife:97848:sa2` | 공개 심사평 | 2,739 | 2,734 | 6/6 | `content_sha256` 일치, 딥링크 DOI가 원문 블록 DOI와 같음 |
| `elife:91722:sa0` | 평가(assessment) | 613 | 613 | 1/1 | 해시 일치 |
| `elife:85223:sa2` | 저자 답변(구모델) | 36,804 | 44,407 | 91/91 | 해시 일치. 차이 7,603자는 인용 분리로 뗀 몫(빌더 기록 `elife_quote_removal.jsonl`) |
| `europepmc:PMC12373210:pone.0330463.r001` | PLOS 결정문 | 7,927 | 16,260 | 39/39 | 뗀 몫은 보일러플레이트·편집부 안내 |
| `europepmc:PMC12853013:report45243` | F1000 심사평 | 4,326 | 4,927 | 24/24 | 원문 contrib의 심사자 이름은 저장 본문에 없음, "I confirm…" 꼬리 제거 |

정직성: 규칙으로 만든 결과를 LLM 결과로 표시하는 곳 없음(전 과정 규칙). 결정 매핑은 `mapping_rule`이 레코드에 남는다(`elife_published_vor`, `plos_acceptance_letter`, `published_article`). 답변은 원문 글자 그대로의 문단만 남기고 잘라 낸 양을 별도 파일에 기록한다.

## 3. 리뷰어 실명 가림 — 실패 상세

### 3.1 무엇을 했나

1. **구조화 명단 대조:** eLife 캐시 500편의 저자·편집자·리뷰어 전체 이름(선호 표기, "이름 성", 성만은 편집자·리뷰어 한정)을 저장 심사평·답변에서 찾았다. 전체 이름 표기가 남은 곳은 없다. 성만 남은 것(약 100건)은 "Gordon et al." 같은 참고문헌 인용이라 정상이다.
2. **패턴 전량 스캔(검증자 자체 정규식):** `Reviewer #N (이름)`, `Reviewer #N [이름]`, `Reviewer #N, 이름 (note … signed …)`, `Signed: 이름`, 맺음말 없이 심사 블록 끝에 혼자 놓인 이름 줄, 맺음말 뒤 같은 줄 이름, `-이름`, 학위·소속 줄(`…, PhD` / 대학명), `Dr./Prof. 이름`, ORCID·이메일.
3. **무작위 30건 직접 열람:** seed 20260930, eLife 공개 심사평·결정서 10 + PLOS 결정문 12 + F1000 심사평 8. 머리·꼬리·짧은 줄을 눈으로 확인 → **30건 모두 이름 없음**(`Kind regards, [NAME]`처럼 가려진 것만 보임). 그러나 전량 스캔에서는 아래처럼 걸린다. 누출률이 심사평 845건 중 22건(2.6%)이라 30건 표본은 통계적으로 놓친다. **빌더 보고서의 "본문 속 이름 0/1"은 구조화 명단(JATS contrib) 대조일 뿐이라 본문 서명을 재지 못한다.**

### 3.2 남은 실명 (레코드 ID만; 이름은 적지 않음)

| 유형 | 예시 형태(이름은 `X`로 바꿈) | 레코드 | 건수 |
|---|---|---|---|
| A. PLOS Biology 헤더 | `Reviewer #1, X (note, reviewer 1 has signed this review):` | `europepmc:PMC10734982:pbio.3002442.r002`, `…r004`, `PMC10824459:pbio.3002452.r004`, `PMC12324687:pbio.3003277.r002`(2명), `PMC12404645:pbio.3003354.r004`, `PMC13293518:pbio.3003856.r003`(2명) | 6 |
| B. PLOS Biology 헤더 | `Reviewer #2 (X):` / `Reviewer #2 [X]:` | `PMC11554119:pbio.3002829.r002`, `PMC11703074:pbio.3002461.r002`, `…r004`, `PMC12143891:pbio.3003149.r004`, `PMC12404645:pbio.3003354.r002`, `PMC12543185:pbio.3003159.r004`, `PMC12885375:pbio.3003629.r002` | 7 |
| C. 서명 줄 | `-X` (심사 블록 끝) | `PMC12091770:pbio.3003161.r004` | 1 |
| D. 맺음말 없는 서명 줄 | 블록 끝에 이름만 한 줄 | `PMC10994395:pmed.1004263.r002`, `PMC11581397:pmed.1004435.r002`, `PMC11299807:pone.0308295.r001`, `…r005`, `PMC9931290:pdig.0000189.r001` | 5 |
| E. 서명 + 학위 + 소속 | `X, PhD` 다음 줄 `University of …` | `PMC12585101:pcbi.1013599.r001` | 1 |
| F. `Signed: X` | 서명 표기 | `PMC12058195:pcbi.1012994.r002` | 1 |
| G. 이름만(맺음말 `Best` 다음 줄) | 이름 첫 단어만 노출 | `PMC12453261:pone.0331870.r001` | 1 |
| H. eLife 저자 답변 | `Reviewer #1 (X)` — 원문 이름은 발음 부호가 있고 저장 명단은 ASCII라 일치하지 않음(`name_variants`가 발음 부호를 무시하지 않음) | `elife:74478:sa2` | 1 |
| I. F1000 답변(sub-article `comment…`) | `Reviewer 1: X` 헤더 그대로, `Prof. X`에게 감사 | `europepmc:PMC12775658:comment15014-384616`, `PMC10521057:comment8741-142618` | 2 |
| | | **심사평 22 + 답변 3 = 25건** (A·B 13 + C 1 + D 5 + E·F·G 3 = 22) | |

- 원인: 가림 규칙(`SIGNED_RE`, `REVEAL_RE`, `SIGNOFF_RE`, `SALUTATION_RE`, 명단 일치)이 (1) 구조화 명단에 없는 리뷰어를 잡는 규칙을 "맺음말 다음 줄 서명"과 "`(X signed his report)` / `Name signed`"로만 한정했고, (2) PLOS Biology의 `Reviewer #N (X)` / `Reviewer #N, X (note…)` 두 형식과 `Signed: X`, 맺음말 없는 서명 줄, 발음 부호가 다른 표기를 다루지 않는다. PLOS Biology 리뷰어 이름은 JATS `contrib`에 없어서(편집자만 있음) 명단 방식으로도 못 잡는다. 빌더의 단위 테스트 26개에는 이 형식 픽스처가 없다(`signed this review`·`Signed:`·PLOS Biology 헤더 검색 결과 0건).
- 재현(코드 수정 없이 함수 호출만): `redact_identity("Reviewer #1, <이름> (note, reviewer 1 has signed this review): …", [])`, `"Reviewer #2 (<이름>): …"`, `"Reviewer #2 [<이름>]: …"`, 이름만 있는 줄을 넣으면 **전부 가려지지 않고 그대로 반환**된다. 반면 `"Reviewer #1 ([NAME] signed his report)"`와 `"Sincerely,\n\nName"`은 가려진다. 즉 규칙이 실제로 작동은 하지만 커버리지가 모자란다(항상 통과하는 검사기는 아님: 다른 호스트 URL·신원 키 조작 입력에서는 실제로 위반을 낸다는 빌더 테스트를 확인).
- 이 검사는 하한이다. 본문 중간에 적힌 서명이나 "제 이름은…" 같은 문장은 규칙으로 찾을 수 없어 남은 것이 더 있을 수 있다.

### 3.3 병합 전 고칠 것 (조건)

1. `redact_names`에 PLOS Biology 두 헤더 형식, `Signed:`·`Signature:`, `-X`, 맺음말 없이 `Reviewer #` 또는 `**********` 바로 앞에 혼자 놓인 이름 줄(학위·소속 줄 포함)을 추가한다. 명단 비교는 발음 부호를 접어서(`unicodedata` NFD 후 결합 문자 제거) 대소문자 무시로 한다.
2. F1000 답변의 `Reviewer N: X` 헤더와 `Prof./Dr. X` 호칭도 가린다(`comment` sub-article 28건 전부 재확인).
3. 위 유형마다 **실데이터에서 가져온 형식의 픽스처(이름은 가짜)**를 `tests/e1/`에 추가한다. 항상 통과하지 않도록, 규칙을 빼면 실패하는 케이스여야 한다.
4. `audit_outputs`에 **본문 잔존 서명 스캔**을 넣어 위반 수로 센다(위 유형의 정규식). 지금의 `names remaining 0/1` 지표는 구조화 명단 기반이라 이 누출을 못 재므로 보고서 문구도 고친다.
5. 캐시에서 `--offline`으로 재생성(네트워크 불필요, 약 20초 + 15초)하고, manifest sha256을 갱신한다. 재검증에서는 이 보고서 §3의 전량 스캔을 그대로 다시 돌려 0이어야 한다.

## 4. 계약·무변경 확인

| 항목 | 방법 | 결과 |
|---|---|---|
| 소유 경로 밖 변경 | `git diff main...task/E1-L1b --name-status` | `A` 7개: `docs/reports/E1-L1b.md`, `scripts/collect_elife.py`, `scripts/collect_europepmc.py`, `src/neumann/sources/{elife,europepmc}.py`, `tests/e1/test_{elife,europepmc}.py`. 전부 소유 경로 또는 허용 예외 |
| `contracts/`·`src/neumann/models.py`·`corpus.py` 변경 | 위 diff | 없음 |
| 기존 researcharcade 산출물(`data/processed/{works,reviews,author_responses,decisions,selection}.jsonl`) | sha256을 `corpus_manifest.json`의 `outputs`와 비교, 수정 시각(18:40)이 E1-L1b 산출(19:16~19:26)보다 앞 | 5/5 일치, 무변경 |
| `data/index/` | `manifest.json`의 입력 sha(`works.jsonl` `317e966f…`, `reviews.jsonl` `b0ba375f…`)가 현재 `data/processed` 파일과 일치, 수정 시각 18:47 | 무변경 |
| 산출 파일 위치·형식 | `elife_*`·`europepmc_*` 엔티티별 JSONL + manifest, E1-L0의 `iter_jsonl`로 `Work`·`ReviewEvent`·`AuthorResponse`·`Decision` 전량 로드 | 오류 0 |
| 검증자가 남긴 파일 | worktree 작업 트리 | 없음(추적 안 되는 파일 0. `.pytest_cache`는 빌더가 19:01에 만든 무시 파일) |

## 5. 기타 발견(병합을 막지는 않음)

- **manifest 소요 시간·HTTP 통계가 마지막 재변환 실행분만 담김:** `elapsed_s`는 eLife 14.3초, EPMC 10.2초이고 `http`는 `cache_hits`뿐이다. 실제 수집 시간(eLife 160.7+104.3초, EPMC 691.8+19.4초)과 요청 통계는 빌더 보고서에만 있다. 스펙의 "소요 시간"을 manifest에서 재현할 수 없다. 재생성 때 이전 값을 이어받게 하거나 `runs` 배열로 누적하는 편이 낫다.
- **저자 답변 편지머리의 개인정보:** 일부 답변에 저자 소속·부서·우편 주소가 남는다(`europepmc:PMC11081267:pone.0303519.r002` 등 3건에 부서·대학·번지, 저자 이름 몇 곳은 `Linjie, Ph.D.,`처럼 남음). 리뷰어가 아니라 저자이고 신원 필드도 아니지만, 정책("개인정보는 마스킹")상 가릴 후보다.
- **eLife 구모델 `accept` 결정:** 게재본만 수집했으므로 246편 전부 `accept`. 빌더가 결정 §5에 적은 대로 생존편향이며 다운스트림(E5 백테스트)이 알아야 한다. 결함 아님.
- 분야 태그 `medical_imaging` eLife 229편은 대부분 MRI를 쓰는 신경과학 논문이다(빌더 보고서에 적힘). 데모 3번 의료영상 CNN 보강은 EPMC 279편에 기댄다.

## 6. 실행한 것 요약

- `python -m pytest tests/e1 -q -k "elife or europepmc"`(worktree, `-p no:cacheprovider`), `python scripts/verify.py`
- 산출물 JSONL 12개 sha256·건수·provenance·키·정규화·고아·중복 전수 검사(자체 스크립트)
- 구조화 명단 21,329회 대조, 서명 패턴 전량 스캔 6종, 무작위 30건 열람, `redact_identity` 재현 호출
- 원문 대조 5건(네트워크, 요청 간 ≥1초), eLife 3건 `raw_hash` 비교
- 금지 사항(코드 수정·git 쓰기·`.env` 열기·하위 에이전트)은 하지 않았다.
