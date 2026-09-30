# E1-L1c 검증 보고 — eLife·Europe PMC 검색 코퍼스 합치기(코드·비교 도구)

**PASS-조건부**

**색인은 DO_NOT_SERVE — 코드 병합 판정만.** `data/index_elife`·`data/index_elife_epmc`는 원본 E1-L1b의 리뷰어 실명 잔존 FAIL 때문에 서비스에 쓰지 않는다. 이 판정은 `corpus.py` 추가분·빌드/비교 스크립트·테스트의 병합 가능 여부이고, 색인 내용의 서비스 가능 여부가 아니다.

- 검증자 Claude Sonnet 5.5(빌더 Opus 5.5와 다른 모델), 2026-09-30. 브랜치 `task/E1-L1c` da2f5dc(merge-base b05de3c). 코드·git·공유 `data/`를 고치거나 쓰지 않았다(임시 fixture는 세션 scratchpad에서만 만들고 지움, worktree 변경 0).
- **병합 전 고칠 것 1건**(아래 2번): 해시 불일치로 빌드가 rc 1로 끝나도 결과 폴더에 "쓰면 안 됨" 표시가 자동으로 붙지 않는다.

## 결과 표

| # | 확인 | 실행한 것 | 실제 결과 | 판정 |
|---|---|---|---|---|
| 1a | `load_corpus` 기본 동작 그대로 | b05de3c의 `corpus.py`를 `git show`로 뽑아 옛 함수와 새 함수를 실제 `data/processed`에 돌려 편수·전 레코드 해시(모델 JSON sha256) 비교 | 옛 `load_corpus(D)` = 새 `load_corpus(D)` = 새 `load_corpus(D, include=None)` = 새 `load_corpus(D/"processed")`(위치 인자). 모두 works 1128 · reviews 5366 · author_responses 12660 · decisions 1128, 해시 `5d2b3fe6a4bb8f3a` 동일. `include=("researcharcade",)`도 같은 편수 | PASS |
| 1b | 추가만 했는지 | `git diff main...task/E1-L1c -- corpus.py`, 옛·새 공개 함수 시그니처 비교 | 삭제 3줄 = import 한 줄에 `Iterable` 추가, `load_corpus` def 줄, 그 docstring 첫 줄. 기존 함수 본문 변경 없음. 시그니처는 `load_corpus`에 키워드 전용 `include=None` 하나만 늘었고 `Corpus`·`audit_processed`·`iter_jsonl`·`resolve_processed_dir`는 그대로 | PASS |
| 1c | eLife 병합 | `load_corpus(D, include=("researcharcade","elife"))` | works 1628 · reviews 6590 · responses 13159 · decisions 1627(eLife 결정 499 = accept 245 + no_binary_decision 254, eLife 500편 중 1편은 결정 레코드가 없음. 빌더가 위반으로 보고하지 않은 사항이라 참고만) | PASS |
| 1d | 출처 URL·원문 해시·신원 필드 검사가 실제로 실패하는지(조작 입력) | 실제 소스 파일 앞 6줄로 만든 임시 코퍼스를 하나씩 조작해 `audit_sources`/`load_sources` 호출, 17건 | 전부 거부: eLife `source_url`을 외부 URL로(1건)·OpenReview URL로(1건), `content_sha256` 짧은 값·삭제, 신원 키 `reviewer_name`·중첩 `contrib`·`signatures`(researcharcade)·`orcid`, 딥링크 `url` 이상, eLife 파일에 다른 소스 `work_id` 접두, `provenance.source` 불일치, 깨진 JSON, 소스 간 work_id 중복, 고아 심사평, 소스 파일 누락, 모르는 소스, 빈 include. 조작 없는 기준선은 통과(비율 1.0, 신원 0). 실제 `data/processed` 전량: researcharcade+elife 23,004레코드, +europepmc 24,932레코드 모두 출처 URL 1.0·딥링크 1.0·해시 1.0·신원 키 0·위반 0. `check_elife_decisions` 위반 0(원문 보존 254/254) | PASS |
| 2a | `build_index_elife.py` 보호 폴더 출력 거부 | 임시 `NEUMANN_DATA_DIR` 아래 `index`·`index_l3`·`NEUMANN_INDEX_DIR` 폴더에 sentinel 파일을 두고 `--out`으로 11가지 표기(대소문자, 끝 `/`, `x/../index`, `./index_l3`, 상대경로, processed 폴더 자체, `NEUMANN_INDEX_DIR`과 같은 폴더·`../` 표기) | 11건 모두 rc 2 + "거부" 메시지, sentinel 3개 그대로(아무것도 쓰이지 않음). 공유 `data/`는 이 시험에서 쓰지 않음 | PASS |
| 2b | 입력 해시 대조 불일치 → rc≠0 | 임시 코퍼스로 `--no-embed`. 소스 manifest의 `elife_reviews.jsonl` sha256을 0으로 바꿈. 대조군은 sha를 맞춘 manifest | 대조군 rc 0(해시 True, 오프셋 1488/1488). 불일치 rc **1**, manifest `elife.corpus_hash_check.sha256_match: false`. 감사 위반은 rc 1에 폴더 자체를 안 만듦(빌더 테스트와 일치) | PASS |
| 2c | 불일치 결과를 "쓰면 안 됨"으로 **표시**하는지 | 2b 불일치 산출 폴더를 조사, 스크립트·`src/neumann/index`에서 `do_not_serve`/`DO_NOT_SERVE` 검색 | **자동 표시 없음.** rc 1이어도 `--out` 폴더에 완전한 색인(bm25·embeddings·excerpts·manifest 등)이 남고 `DO_NOT_SERVE.txt`도 manifest `do_not_serve`도 없다. 남는 신호는 manifest의 `sha256_match: false` 하나뿐이고 그걸 읽는 코드가 없다. 실패 메시지 앞에 `전환: NEUMANN_INDEX_DIR=…` 안내가 먼저 찍힌다. 스크립트·`index/` 어디에도 DO_NOT_SERVE 코드가 없다(grep 0건) → 표시는 빌더가 두 폴더에 손으로 넣은 것이고, 로더는 그 표시를 검사하지 않는다(`NEUMANN_INDEX_DIR`로 가리키면 그대로 서비스됨) | **고칠 것(조건)** |
| 2d | 두 색인의 DO_NOT_SERVE 표시 | 실제 `data/index_elife`, `data/index_elife_epmc` 확인 | 두 폴더 모두 `DO_NOT_SERVE.txt`(사유·재빌드 명령) 있음, `manifest.json`에 `do_not_serve.flag: true`(사유·시각·재빌드 명령·입력 해시) 있음, UTF-8 정상 | PASS |
| 2e | 보호 색인 무변경 | `data/index`, `data/index_l3` manifest sha256 | `a0d1cf87…`, `22e5ec50…` — 보고서 값과 같음 | PASS |
| 2f | DO_NOT_SERVE가 타당한 이유 확인 | 두 색인 manifest의 입력 파일 해시와 **지금** `data/processed` 파일 해시 비교 | 두 색인 모두 `elife_reviews.jsonl` 해시가 현재 파일과 다르다(epmc는 `europepmc_reviews.jsonl`도). 색인이 재작업 전 입력이라는 보고서 주장과 일치 | PASS |
| 3a | `pytest tests/e1 -q -k elife` | `NEUMANN_LLM_PROVIDER=mock`으로 | 28 passed, 125 deselected | PASS |
| 3b | `python scripts/verify.py` | 같은 환경, 2회 실행 | 910 passed, 21 skipped, 보안·계약·테스트 통과, "verify 통과", rc 0 (1차 82.9s, mock 명시 재실행 62.8s) | PASS |
| 3c | 소유 경로 | `git diff main...task/E1-L1c --stat/--name-status` | 6개 파일만: `corpus.py`(M), `scripts/build_index_elife.py`·`build_index_elife_compare.py`, `tests/e1/test_corpus_elife.py`·`test_corpus_elife_index.py`, `docs/reports/E1-L1c.md`(A). `src/neumann/index/`·`scripts/build_index.py`·`contracts/`·`models.py`·`data/`·`.env` 변경 0. main이 merge-base 뒤로 움직였지만 이 파일들과 겹치는 main 변경 없음 | PASS |
| 4 | 실명 미이월 | `data/cache/elife`에서 리뷰어 전체 이름 488개·저자 전체 이름 3,650개를 메모리에만 올려, 브랜치 변경 6개 파일 + 커밋 메시지 5개 + `git log -p` 전체를 정규화 후 완전 일치 검색(이름은 출력하지 않음) | 전부 **0건**. fixture는 새로 추가된 게 없고 테스트는 코드 안 가짜 행이다. 참고로 같은 이름 목록을 `index_elife` eLife 문장 33,655개에 대보니 리뷰어 전체 이름이 든 문장이 2개 나온다(빌더 표 3문장과 이름 목록 정규화 차이) → 색인에 실명이 남아 있다는 DO_NOT_SERVE 사유 재확인 | PASS |
| 5 | 비교 도구 | 코드 읽기 + 빌더 테스트 `test_compare_marks_elife_hits` 통과 | 기본 실행은 읽기 전용이고 `--json`/`--md`를 줄 때만 쓴다. 가짜 두 색인(어휘 검색) 시험은 통과. **실제 색인으로 재실행은 안 했다**(GPU 대량 작업 금지 범위, 보고서 표는 검증 못 함) | 부분(미재현) |

## 병합 전 고칠 것

1. **해시 불일치·오프셋 불일치로 rc≠0이면 `--out` 폴더에 `DO_NOT_SERVE.txt`와 manifest `do_not_serve: {flag: true, reason}`를 스크립트가 직접 남긴다.** 지금은 rc 1이어도 완전한 색인이 그대로 남아 이 사고(재작업 전 입력으로 빌드된 색인)를 코드가 막지 못한다. 실패 메시지 앞에 나오는 `전환: NEUMANN_INDEX_DIR=…` 안내는 성공일 때만 찍는다. 테스트 `test_build_fails_on_manifest_hash_mismatch`에 표시 존재 단언을 더한다(현재는 `sha256_match is False`만 본다). 코드 몇 줄이다.

## 참고(병합을 막지 않음)

- `load_corpus(include=…)`/`load_sources` 자체는 URL·신원 검사를 하지 않는다(모델 검증·중복·고아만). 검사는 `audit_sources`이고 빌드 스크립트가 빌드 전에 부른다. `load_corpus(include=…)`만 직접 부르는 소비자는 감사를 따로 불러야 한다.
- `audit_sources`의 Europe PMC 딥링크 접두가 `https://`(아무 https)이고, `provenance.source` 검사가 `startswith`라 느슨하다. 지금 데이터는 통과하지만 조작 방어력은 eLife·OpenReview보다 낮다.
- 로더(`src/neumann/index`)가 DO_NOT_SERVE를 검사하지 않는다(소유 밖). 서버 쪽(E4·E2)이 `DO_NOT_SERVE.txt`가 있는 색인을 거부하게 하면 좋다.
- `tests/e1/test_corpus_elife_index.py::test_real_index_elife_manifest`가 공유 `data/index_elife`의 빌드 시점 `sha256_match is True`를 단언한다. DO_NOT_SERVE 색인에도 통과하므로 verify 통과가 "색인 서비스 가능"을 뜻하지 않는다. 재빌드 후에도 그대로 유효하다.
- 보고서의 "보안: 파일 311개"는 내가 돌린 시점 312개(마지막 보고서 커밋 뒤). 사소한 불일치.
- 실행 환경: 셸에 `NEUMANN_LLM_PROVIDER=openai`가 들어 있었다. `tests/conftest.py`가 `NEUMANN_LIVE_TESTS=1`이 아니면 pytest에서 mock으로 덮고(이 변수는 미설정), 내가 직접 돌린 빌드·감사·조작 시험 스크립트는 LLM 코드를 부르지 않았다. 지시를 받은 뒤 `-k elife`와 `verify.py`를 `NEUMANN_LLM_PROVIDER=mock`으로 명시해 다시 돌려 위 결과를 얻었다. OpenAI 호출 없음.

## 검증하지 않은 것

- 색인 내용의 서비스 적합성, 재빌드 결과(E1-L1b 재작업 PASS 이후 별도 검증).
- 보고서의 데모 상위 10편 전후 비교 표 수치(GPU 빌드·질의 임베딩이 필요해 재현하지 않음).
- 실명 검색은 전체 이름 완전 일치만이다. 성만·JATS 하위 기사 기여자 목록(409명)·Europe PMC 쪽은 대지 않았다.
