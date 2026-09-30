# HWPX-UPLOAD 구현 보고서

## 결과

- 작업 브랜치: `codex/hwpx-upload`. 시작 기준 `origin/main = 5093383361c1b5e1215a4218676e3658670f7969`.
- `git branch -a`로 `task/E4-L2h`를 찾고, `0220be3`까지의 구현·후속 보안 수정(diff/log)을 읽었다. 다른 worktree는 수정하지 않았다.
- HWPX 업로드 추출기, 업로드 진입점, 파일 선택 안내와 관련 테스트를 현재 브랜치 작업 파일에 통합했다.
- **커밋은 미완료다.** 명시적 파일 목록의 `git add`가 `.git/worktrees/hwpx-upload/index.lock: Permission denied`로 반복 실패했다. 사용자 지시로 커밋을 허용받았지만 실행 환경은 인덱스 쓰기를 거부했다. 훅 우회·stash·main 병합·push는 하지 않았다.
- 재현·검토용 패치: `out/hwpx-upload/HWPX-UPLOAD.patch`. 보고서를 포함한 모든 변경 파일이 들어 있다. 이 패치는 커밋이나 main 병합을 대신한 것으로 주장하지 않는다.

## 변경과 보안 한도

`src/neumann/api/hwpx.py`는 ZIP 안의 허용한 본문·메타데이터만 메모리에서 읽는다. spine 순서 또는 구역 번호순으로 문단·표·각주·글상자를 추출한다. 그림은 압축을 풀지 않는다. 읽지 못한 구역, 중첩 제한, 본문 대신 미리보기 일부를 가져온 경우는 경고로 표시한다.

`src/neumann/api/upload.py`에 HWPX 판별·추출·격리 작업자 연결을 추가했다. HWP/HWT/HML은 415와 **“HWP는 한글에서 HWPX 또는 PDF로 저장해 올려 주세요”**로 거절한다. XML 파서는 엔티티 해석·네트워크·DTD 로딩·huge_tree를 끄고 DTD/ENTITY 선언을 거절한다. 메타데이터의 UTF-16/UTF-32 선언도 검사한다. 중복 항목과 읽을 수 없는 암호화 manifest는 거절한다.

| 경계 | 결과 |
|---|---|
| 업로드 10 MiB 초과 | 413 |
| 실제 읽는 ZIP 항목 압축 해제 합계 20 MiB 초과 | 413 |
| ZIP 항목 1,000개 초과 | 413 |
| 1 MiB 초과 항목의 압축비 100배 초과 | 413 |
| mimetype 해제 256 B / 압축 4 KiB 초과, 크기·CRC 위조 | 422, 격리 전에 차단 |
| XML 요소 누적 500,000개 초과(숨은 요소·메타데이터 포함) | 413 |
| manifest 1 MiB 초과 / 구역 256개 초과 | 413 |
| DTD·외부 엔티티·암호화 | 422 |
| 정리 뒤 50,000자 초과 / 5,000줄 초과 | 413 / 422 |
| HTTP 추출 시간·메모리·동시 처리 | main의 기본 10초·512 MiB·2건 유지 |

E4-L2h 파일을 그대로 덮어쓰면 SEC-7의 PDF 스트림 상한, 작업자 메모리 제한, 10초 기본값, 줄 수 제한 및 공통 입력 정리가 사라진다. 공통 조상 기준으로 변경을 통합하고 충돌을 해결해 이를 보존했다. 계약 및 설정 파일은 변경하지 않았다. lxml은 기존 python-docx 의존 환경에 있다.

화면에는 `.hwpx`/`application/hwp+zip` accept와 HWPX 안내를 추가했고, 정적 화면에서 HWPX는 서버가 필요하다고 안내한다. CSS 블록은 HEAD와 동일하다.

## 검증 명령과 실제 출력

모든 시험 명령 앞에서 프로세스 환경의 키·솔트·live 플래그를 제거했다. `.env`를 열지 않았으며 pytest 공통 설정은 설정 로더의 env_file을 비활성화한다. 재사용한 기존 작업자 환경 테스트에서 PATH 값 비교와 실제 솔트 변수명에 시험값을 넣는 구문을 발견해, PATH 이름 존재 여부와 가짜 SALT 변수명으로 변경했다. 최종 테스트는 환경변수 값을 출력·단언하지 않고 키 이름의 존재/부재만 검사한다.

```powershell
Remove-Item Env:OPENAI_API_KEY,Env:NEUMANN_PSEUDONYM_SALT,Env:NEUMANN_LIVE_LLM_OK,Env:NEUMANN_LIVE_TESTS -ErrorAction SilentlyContinue
$env:NEUMANN_LLM_PROVIDER='mock'
$env:NEUMANN_UI_TESTS='1'
$env:PYTHONPATH='src;.'
$env:PYTHONIOENCODING='utf-8'
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e4/test_upload.py tests/e4/test_upload_hwpx.py tests/e4/test_hwpx_security_regression.py tests/e4/test_hwpx_mimetype_boundary.py tests/e4/test_hwpx_upload_candidate.py tests/e4/test_webui_upload.py tests/e4/test_sec7.py -q
```

최종 묶음 출력: **`229 passed in 36.93s`**.

추가 확인: 경로 조작 테스트의 읽기 허용 목록을 강화한 뒤 후보 파일 전체를 같은 환경에서 다시 실행해 **`12 passed in 7.36s`**를 확인했다. 작업자 환경 테스트 조정 뒤에도 해당 테스트를 재실행했다.

- 추출 정상 입력, 표·구역 순서·미리보기 경고, HWP 거절, 파일·글자·ZIP·XML 제한, XXE·엔티티 폭탄, mimetype 크기 위조, 300건 퍼징을 포함한다.
- 추가 후보 테스트는 ZIP 경로 조작 5종, 외부/상위 경로 spine 3종, 실제 50만 요소 XML, main 줄 수 제한, 거대 XML의 HTTP 413 및 작업자 시작 전 거절을 검사한다.
- SEC-7 기존 회귀도 통과했다. 스캔 PDF 오류 문구 테스트 기대값 1곳을 새 안내 문구로 조정했다.
- 초기 검사에서 발견한 문구 기대값 불일치 및 추가 테스트 견본의 ZIP 정규화·압축비 선행 거절 문제는 수정했다. 실패를 최종 성공으로 숨기지 않았다.
- `git diff --check`: 종료 코드 0. 개행 정규화 경고만 있고 공백 오류 없음.
- 전체 `scripts/verify.py`는 작업 지시대로 실행하지 않았다.

## Headless 화면 측정

`tests/e4/test_hwpx_upload_candidate.py::test_headless_upload_reaches_analysis_with_identical_text`는 빈 8180~8199 포트에 mock 시험 서버를 띄우고 Playwright Chromium headless만 사용한다. 실제 upload router와 실제 화면을 사용하되 분석 요청은 시험 응답으로 종료한다. 검색·LLM·수정/최종화 엔진은 실행하지 않는다. finally에서 시험 서버를 종료한다.

| 폭 | HWPX 응답 | 추출 본문 = 분석 요청 본문 | HWP 안내 | 가로 넘침 | JS 오류 |
|---|---|---|---|---|---|
| 1440 | 200 | 일치 | 415 문구 일치 | 0 px | 0 |
| 390 | 200 | 일치 | 415 문구 일치 | 0 px | 0 |

`out/hwpx-upload/measurements.json`과 `upload-{1440,390}.png`, `analysis-{1440,390}.png`, `hwp-rejection-{1440,390}.png`를 남겼다. 업로드 화면 이미지 2장을 직접 확인했다. 이 결과는 **업로드 → 분석 요청 경계**의 검증이며 전체 재탄생·확정·최종 초안 성공을 뜻하지 않는다.

화면 디자인 규격을 읽었다. 추가 CSS·색·글자 크기·글꼴 선언은 0개이고 CSS 블록은 기준 커밋과 같다. 그러나 기준 화면에는 구형 필기체·기존 스테퍼 등이 남아 있어 전체 디자인 규격 준수를 주장하지 않는다. 정적 검색 기준 기존 hex 색 표식 36개, font-size 선언 233개, font-family 선언 102개다(위반 개수나 실제 글꼴 종수와는 다른 지표). 전체 6단계 디자인 검증은 UI 통합 과제로 남는다.

## 남은 것과 다음

1. PM/실행 관리자가 Git 인덱스 쓰기 권한을 복구한 뒤 현재 브랜치의 변경 파일과 이 보고서를 명시적으로 stage하고 `[HWPX-UPLOAD]` 커밋을 생성해야 한다. 또는 제공 패치를 승인된 작업 공간에서 적용한다.
2. 독립 검증과 main 병합은 PM이 진행한다. 본 작업은 하위 에이전트 위임 없이 수행한 빌더 자체 검증이다.
3. 실제 사용자 HWPX 원본과 전체 수정·최종화 흐름, 라이브 API는 시험하지 않았다. 이 작업의 제품 LLM 실제 호출은 0건이다.

builder: codex-gpt-6.1-sol
