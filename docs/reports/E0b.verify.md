# E0b 검증 보고서

- 검증자: Claude Sonnet 5.5 (빌더 claude-opus-5.5와 다른 모델)
- 대상: 브랜치 `task/E0b`, HEAD `d37ba4a`, worktree `.claude/worktrees/agent-a50479f8a261ffff4`
- 범위: 브랜치 전체(models·config는 PM이 main에 선병합했지만 fixture·로더·데모 계획서 포함해 재확인)
- 검증 시각: 2026-09-30. 코드·git 쓰기 조작 없음. 임시 실험은 전부 스크래치 폴더의 복사본에서 했고 worktree에는 아무것도 남기지 않았다(`.pytest_cache`도 지움).

## 판정: **PASS**

병합 전에 반드시 고칠 것은 없다. 아래 "권고(비차단)"는 후속 과제에서 처리해도 된다.

## 항목별 결과

| # | 확인 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | `tests/e0` 전부 통과 | `python -m pytest tests/e0 -q` (환경변수는 _COMMON.md) | `45 passed in 0.29s` | 통과 |
| 1b | `verify.py` 통과 | `python scripts/verify.py` | `45 passed`, `보안: 파일 47개`, `계약: 2개`, `테스트: 통과`, `verify 통과`. 훅 꺼짐 경고만(worktree 설정 탓, 빌더 보고서와 같은 현상) | 통과 |
| 2a | Excerpt 12건 전량 원문 대조(독립 스크립트) | 원시 JSON을 직접 읽어 `source[start:end] == text`, `sha256(text) == text_sha256`, `len == end-start`, `source_sha256 == sha256(원문)`, `source_url == 원문 provenance.source_url`, `provenance.content_sha256 == sha256(원문)` 검사. 발췌 12건(review 11·decision 1) 전량 | 12/12 전부 참, 불일치 0. 오프셋 0 시작 포함(예: `ex_c5986bb2facc61b2` 0~59). 카드·태그가 가리키는 Excerpt id·Work id에 고아 없음 | 통과 |
| 2b | 모델의 `verify_against` 가 조작을 잡는지 | 12건 각각: 원문 1글자 변경 / 원문 앞에 글자 추가(오프셋 밀림) / `model_copy`로 text 조작 → `verify_against` 결과, 생성자에 조작 text 전달 → 예외 | 12건 모두 조작 감지(False), 생성자는 ValidationError | 통과 |
| 2c | fixture 테스트가 항상 통과하는 것이 아닌지(스크래치 복사본에 변이 주입) | M1 reviews.jsonl 1글자 변경 / M2 excerpts.jsonl text 1글자 조작(해시 유지) / M4 plan.md 1바이트 추가 / M5 RiskCard 근거 최소 1 제거 / M6 신원 가드 무력화 / M7 `verify_against` 항상 True / M8 `env_ignore_empty=False` | M1 3건 실패, M2 5건 실패, M4 2건 실패, M5 1건 실패, M6 8건 실패, M7 2건 실패, M8 1건 실패. 전 변이가 테스트에서 잡힘. (M3 "오프셋과 text·해시를 함께 1칸 이동"은 통과하는데, 이동해도 원문의 유효한 조각이라 정당한 통과이며 결함 아님) | 통과 |
| 2d | 생성기 재현성 | 스크래치 복사본에서 `make_fixtures.py` 재실행 후 6개 JSONL + `premortem_result.json`을 worktree 파일과 `cmp` | 전부 바이트 동일. Excerpt는 원문에서 잘라 생성됨 | 통과 |
| 3 | 데모 계획서 3건이 키트 원본과 바이트 동일 | `sha256sum`으로 작업 트리 파일 및 `git show task/E0b:<path>` 커밋된 blob을 키트 `부록/데모입력/`과 대조 | `plan.md` `3d35460d…ef33c`, `plan_elife_neuro.md` `f0fb41c5…d9ff`, `plan_medimaging.md` `4d8d8887…e031` — 작업 트리·커밋 blob·키트 세 곳 모두 SAME. `.gitattributes`가 `eol=lf`라 체크아웃 후에도 유지. 음성 대조 `negative_recipe.md`는 한국어 조리법(연구 무관) 확인 | 통과 |
| 4 | 신원 필드 금지가 실제로 작동 | `python -c`로 `NeumannModel`·`Work`·`ReviewEvent`·`Provenance`·`Decision`·`AuthorResponse`·`PostStatus` 서브클래스에 `name` 필드 정의 | 7종 모두 `TypeError: … 신원 필드 금지`. 추가로 `email`·`reviewer_name`·`authors`·`orcid`·`reviewer_id`·`Email`(대소문자)·`username`·`first_name`, 별칭 `Field(alias="name")`·`validation_alias="email"` 도 TypeError. `title`·`reviewer_pseudonym`은 허용(정상). 런타임 `extra="forbid"`도 있음 | 통과 (아래 권고 1 참고) |
| 5 | 계약 위반·소유 경로 밖 변경 | `git diff main...task/E0b --stat` (분기점 기준), `--name-only`에서 소유 경로 밖 필터 | 변경 15파일, 전부 `tests/fixtures/`(14), `tests/e0/test_e0_fixtures.py`, `docs/reports/E0b.md`. `contracts/`·루트·`docs/`(보고서 제외)·`src/`·`scripts/` 변경 없음. `models.py`·`config.py`는 main과 diff 0(선병합분과 동일). 삭제 없음. main이 브랜치보다 앞서 있어 `main..task/E0b` 2점 diff에는 `.env.example`·`HANDOFF.md`·`_VERIFY.md` 등이 "삭제/변경"으로 보이나 빌더가 건드린 것이 아니라 main이 그 뒤로 전진한 것 | 통과 |
| 6 | fixture에 실제 인명·이메일·키 없음 | fixture 전 파일 grep: 이메일 정규식, ORCID, `sk-`·`AKIA`·`ghp_`·`Bearer`·`api_key`·`secret`·`token`·`password`, URL 호스트 집계, 심사평·결정·논문 본문 전량 육안 확인, 계획서 3건 `@`·`http` 확인 | 이메일 0, ORCID 0, 키 패턴 0. URL 호스트는 `https://example.org` 72건뿐. 논문 제목은 `[FAKE]` 접두, venue `FakeConf 2099`, 심사평 12건 `reviewer_pseudonym=null`, 인명 없음(`nnU-Net`은 방법 이름). 설정 테스트의 키는 `fake-test-key-not-real-000` 같은 명백한 가짜. `.env` 열지 않음(존재 여부 bool만 확인, 저장소 루트에 없음) | 통과 |
| 7 | 정직성: 생성 방식 표기 | 카드 2장과 태그 12건의 `generator`, 결과 `stages`·`notices` | 카드·태그 전부 `generator=mock`, 결과 stages의 `impl`이 `fixture:mock`, `notices`에 `[FAKE] fixture result…`. 규칙·mock을 astra로 표시한 곳 없음 | 통과 |
| 8 | 설정 로더 우선순위(독립 확인, 가짜 키) | 임시 폴더에 `.env`(`OPENAI_API_KEY=` 빈 값, `NEUMANN_PSEUDONYM_SALT=` 빈 값) + 환경변수에 가짜 키·가짜 솔트를 주고 `Settings(_env_file=…)` | 환경변수 값 우선(`key==env: True`). `repr`·`str`·`f-string`·`model_dump`·`model_dump_json` 어디에도 키·솔트 노출 없음(`**********`). `load_dotenv`는 docstring 언급 1회뿐이며 코드에 없음. 셸에 이미 `NEUMANN_LLM_MODEL` 환경변수가 있어 `.env` 값보다 환경변수가 이기는 것도 관측됨 | 통과 |
| 9 | 빌더 보고서 정합성 | 보고서의 명령·수치·표 대조, 커밋 메시지 형식 | pytest 45건, 커밋 3건(`73a264b` models·config 먼저 → fixture → 보고서), 끝줄에 `verify 통과`·`builder: claude-opus-5.5` 있음. 불변식↔테스트 표의 테스트 이름이 실제 `def test_` 목록과 일치. 결정·못 한 것·PM 제안 기재됨 | 통과 |

## 실패 재현 절차
없음(실패 항목 없음).

## 권고 (비차단, 후속 과제로)

1. **신원 토큰 우회 여지(낮음):** `reviewerId`(camelCase)·`reviewerid`·`user_id`·`contact` 같은 이름은 `IDENTITY_TOKENS`의 부분 문자열 일치를 통과한다(`python -c`로 확인). 스펙이 든 `name·email·reviewer_id·author·orcid`는 모두 막히고, `extra="forbid"`가 입력 데이터 쪽 유출을 막으므로 병합을 막을 사유는 아니다. 강화하려면 필드명에서 비영숫자를 제거하고 소문자로 만든 뒤 `reviewerid` 등을 토큰에 추가하면 된다(PM 승인 필요: models.py는 계약).
2. **fixture 테스트의 절대 경로:** `test_e0_fixtures.py`의 `KIT_DEMO`가 이 머신 경로로 고정돼 있고 없으면 원본 대조를 건너뛴다. 현장 머신에서는 실행되지만 CI 등 다른 환경에서는 조용히 건너뛴다. 필요하면 sha256 3개를 테스트에 상수로 박아 두는 편이 낫다.
3. **`excerpt_id == Excerpt.make_id(...)` 검사 없음:** fixture 테스트가 id와 (종류, 원문 id, 오프셋)의 일치를 확인하지 않는다(변이 M3에서 확인). 지금은 생성기가 맞게 만들고 있어 실해 없음.
4. `NEUMANN_LIVE_TESTS`·`tests/conftest.py`(mock 기본)는 빌더가 제안한 대로 main에 이미 반영돼 있다. 이 브랜치에는 그 파일이 없지만(브랜치가 그 커밋 이전 분기) 병합 후 충돌 지점은 없다.

## 병합 메모

- 병합 시 `models.py`·`config.py`·`test_e0_models.py`·`test_e0_config.py`는 main과 이미 동일하다. 새로 들어오는 것은 fixture·로더·계획서·`test_e0_fixtures.py`·빌더 보고서다.
- 병합 후 main에서 `python scripts/verify.py`를 한 번 더 돌릴 것(main에는 `tests/conftest.py`가 있어 provider 기본값이 mock으로 바뀐 상태로 테스트가 돈다. 이 검증은 그 파일이 없는 브랜치 상태에서 수행했다).
