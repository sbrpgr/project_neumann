# STATIC-FINAL — 제출용 6단계 정적 프로토타입

브랜치 `codex/static-final`. 빌더 `codex-gpt-6.1-sol`.

## 구현 결과

- `scripts/build_static_final.py`와 `scripts/static_final/`의 HTML·CSS·JS로 정적판을 재현합니다. 기존 `codex/fin-static`의 `0cf9c6d`를 읽어 참고했으며, 긴 7단계 화면과 추가 승인 체크박스를 6단계 전환형 화면으로 교체했습니다.
- **입력 → 분석 → 채택 → 수정 계획서 → 최종 점검 → 완성**. 현재 단계만 표시하고 과거 단계로 돌아갈 수 있습니다. 단계 전환 시 맨 위로 이동합니다.
- 기존 계획서 fixture 3편(전해액·의료영상·뇌영상), 각 2개 수정 제안, 원문 문자 오프셋으로 검증한 가상 심사 발췌를 사용합니다. 실제 논문 심사 결과로 소개하지 않습니다. 신경과학 샘플은 의료영상의 지적을 가져온 **분야 수준 참고**로 표시합니다.
- 상단에 **사전 계산 결과 · 실시간 분석 아님**을 표시합니다. 제안별 출처는 **Claude/Codex 오프라인**, 점검별 출처는 **로컬 도구 실행 결과**입니다.
- 기본 채택 토글, 한 줄 수정 미리보기, 접힌 근거·보조 정보, 720px 문서, 변경 문장 강조와 번호, body 직속 수정 내역 대화상자, 문단 제자리 편집을 제공합니다.
- 확정 한 번 뒤 논리·물리·구조 결과를 순서대로 재생합니다. 자동 수정에는 재채택을 요구하지 않으며, 항목별 되돌리기는 실패 상태와 최종 문안에 반영됩니다.
- 최종 초안과 변경 통계, 로컬 `.md`·`.docx` 다운로드, 처음부터 다시를 제공합니다. 다운로드에는 생성 방식·점검 범위·추가 검토 필요 문구도 포함합니다.

## 빌드와 배포

테스트·빌드 프로세스에서 비밀값을 제거하고 mock을 지정합니다. 값을 출력하거나 단언하지 않습니다.

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:NEUMANN_PSEUDONYM_SALT -ErrorAction SilentlyContinue
Remove-Item Env:NEUMANN_LIVE_LLM_OK -ErrorAction SilentlyContinue
$env:NEUMANN_LIVE_TESTS='0'
$env:NEUMANN_LLM_PROVIDER='mock'
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
& C:/Users/User/.venvs/neumann/Scripts/python.exe scripts/build_static_final.py
```

빌드 출력:

```text
STATIC-FINAL: 3 samples; 6 stages; 9 corrected local tool checks; offline HTML
```

산출물은 이 worktree의 `data/site_final/index.html`, `flow.json`, `.nojekyll`, `FONT-LICENSE.txt`입니다. 글꼴·코드·데이터를 HTML에 내장하므로 서버·키·외부 CDN 없이 열 수 있습니다. Pretendard 라이선스를 함께 제공합니다. `data/`는 git에 올리지 않습니다. PM이 커밋을 합류시킨 뒤 같은 명령으로 재빌드하여 `data/site_final/`을 Pages 배포 아티팩트로 사용하면 됩니다. Pages 프로젝트 하위 경로 `/neumann/`에서 동작을 검사했습니다. 이 작업에서 배포·main 병합·push는 수행하지 않았습니다.

## 완료 기준별 측정

| 기준 | 측정 결과 |
|---|---|
| 샘플 2~3편 전체 흐름 | 3편 × 1440·390 = **6회 완주**, 각 6단계 = **36개 화면 상태** 검사 |
| 출처·인용 | 제안 6개에 출처 표시. 전체 발췌 fixture의 원문 SHA-256·문자 오프셋 대조; 변조된 인용 거절 |
| 로컬 도구 실제 실행 | 각 샘플의 Z3·Pint·NetworkX 점검 **3/3 실패 → 3/3 통과**, 전체 **9건 수정 전 실패·수정 후 통과** |
| 오류 수정 내용 | 배분 합계 초과를 시험 배분 조정으로 수정; `1 mS/cm = 1 S/m`를 `0.1 S/m`로 수정; 평가→학습 순환 관계 제거 |
| 도구 검사 반례 | 배분·환산값·선행 관계를 다시 변조하면 각각 실제 실패 |
| 직접 편집 정직성 | 점검 조건을 편집하면 해당 도구 **미점검**, 자동 덮어쓰기 없음. 일반 문단 편집에는 별도 검토 안내. 과거 단계 편집 시 완성 단계 잠금 |
| 되돌리기·채택 | 채택 0·1·2건; 원문 유지; 자동 수정 되돌림 후 실패 1건과 최종 원문 복원; 재적용 후 통과 |
| 입력 | 300자 미만 거절; 600자 미만 경고; 범위 밖 사유 우선; 새 문안 실행 차단; 파일 선택 후 제한 안내 |
| 외부 요청 | 각 해상도에서 첫 HTML 로컬 요청 **1건** 뒤 offline으로 전환하고 전 흐름·다운로드 수행. 외부 요청 **0**, 추가 요청 **0**, 브라우저 오류 **0** |
| 빌드 네트워크 | socket 접속을 차단한 상태에서도 빌드 성공; 설정 로더·제품 LLM·`.env` 사용 없음 |
| 비밀값·개인정보 | 출력 데이터 allowlist에 심사자 신원·헤더·설정 객체 없음. HTML의 키 형태·이메일·휴대전화 패턴 **0** |
| 가로 넘침 | **1440·390의 36개 상태 모두 0px**, 추가 375 및 1152px/125% 대화상자 검사 통과 |
| 디자인 토큰 | `:root` 밖 색 리터럴 **0**, 토큰을 통하지 않는 글자 크기 **0**, 실제 크기 **14·16·20·28px**, 글꼴 **Pretendard 1종** |
| 화면 구조 | 각 상태 현재 섹션 **1**, 주 버튼 **1**. 스테퍼 높이 **56px**. 모달 body 직속·Escape 닫기·모션 감소 설정 검사 |
| 다운로드 | 3편 × 두 해상도에서 Markdown의 문안·고지 대조; DOCX ZIP 무결성·XML 파싱·수정 문장 일치 |
| 시험 서버 | 빈 **8100** 포트의 작업 전용 정적 시험 서버 사용, fixture 종료 때 스레드 종료·포트 연결 실패 확인. 금지 포트에서 서버 기동 없음 |

관련 검사 명령:

```powershell
$env:TEMP=(Join-Path (Get-Location) 'data/tmp')
$env:TMP=$env:TEMP
& C:/Users/User/.venvs/neumann/Scripts/python.exe -m pytest tests/e6/test_static_final.py -q --basetemp data/static-final-test-tmp
```

최종 실행 결과:

```text
10 passed in 56.52s
```

`git diff --check`도 통과했습니다. git 권한 문제로 실제 파일 staging은 실패했으므로 `verify --staged`의 파일 0개 결과를 이 변경의 보안 통과로 계산하지 않습니다.

스크린샷: `data/site_final/qa/{1440,390}-{0..5}-*.png` 12개, 375·1152/125% 대화상자 2개. 측정 JSON: `1440-measurements.json`, `390-measurements.json`. HTML 파일 크기는 약 2.8MB입니다. 스크린샷과 측정 기록은 무시된 `data/`에만 보관합니다.

## 제한과 다음 작업

- 새 문안·PDF·DOCX·HWPX의 실시간 분석이나 파일 파싱은 하지 않습니다. 선택한 파일은 읽거나 전송하지 않고, 지원 범위를 안내합니다. 붙여넣기는 저장된 샘플과 문안이 일치할 때만 결과를 엽니다.
- `wait.js/wait.css`는 요청 없는 정적 WAIT-UX 어댑터이며 `NeumannWait.create/update/done/fail`을 제공합니다. 실제 모델 준비 시간이나 서버 진행률로 표현하지 않습니다.
- 실행 조건은 시연용 오프라인 제안입니다. 전도도 환산은 세 샘플 모두 도구 사용 예이며, 의료영상·뇌영상 연구의 물리 실험 조건이 아닙니다. 수치 배분·단위 환산·선행 관계만 점검하며 성능·임상 유효성·전체 연구 타당성을 확인하지 않습니다.
- 브라우저에서 도구나 LLM을 재실행하지 않습니다. 직접 바꾼 조건에는 이전의 통과 결과를 적용하지 않습니다. 파일 직접 열기는 자원 내장 구조로 지원하며, 브라우저 검사는 사용자 지시에 따라 81xx 서버의 headless Playwright로만 수행했습니다.
- DOCX는 최소 표준 OOXML 내보내기입니다. ZIP/XML/문안 일치를 검사했으며 Word 렌더링의 페이지 배치는 검사하지 않았습니다.
- 하위 에이전트 위임 금지에 따라 자체 관련 검사만 수행했습니다. 독립 검증과 main 병합·Pages 배포는 PM의 별도 작업입니다. 전체 `scripts/verify.py`는 실행하지 않으며 커밋 훅의 staged 보안 검사는 유지합니다.

## git 권한 차단과 인계

`git add`에서 다음 오류로 차단됐습니다. 기존 lock 파일은 없었고 `.git` 및 해당 worktree 메타데이터에 Deny ACL이 있습니다. 권한 변경·훅 우회·다른 worktree 쓰기는 수행하지 않았습니다.

```text
fatal: Unable to create 'C:/Users/User/Desktop/project_neumann/.git/worktrees/static-final/index.lock': Permission denied
```

따라서 **커밋은 미완료**입니다. 변경 파일 9개는 현재 worktree에 보존하고 `data/STATIC-FINAL.patch` 및 `data/STATIC-FINAL-commit-message.txt`로 인계합니다. 코드·보고서 파일 9개는 기존 `verify.py`의 경로/패턴 검사 함수로 직접 검사했습니다. 이 검사는 비밀값이나 `.env`를 읽지 않으며, 실제 커밋 훅의 대체 통과로 주장하지 않습니다.

```text
C:/Users/User/.venvs/neumann/Scripts/python.exe data/package_static_final.py
STATIC-FINAL scoped security: 9 files + commit message; 0 findings; patch packaged
```

권한이 있는 PM 세션에서 **이 worktree의 `codex/static-final` 브랜치**에 다음 작업만 남습니다.

```powershell
git add scripts/build_static_final.py scripts/static_final/index.html scripts/static_final/style.css scripts/static_final/flow.js scripts/static_final/wait.js scripts/static_final/wait.css tests/e6/test_static_final.py docs/reports/STATIC-FINAL.md docs/decisions.md
git commit --file data/STATIC-FINAL-commit-message.txt
```

main 병합·push는 이 인계 명령에 포함하지 않습니다.
