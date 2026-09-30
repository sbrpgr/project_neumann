# E3-L2r 독립 검증 — 대상 PASS-조건부

- 검증자 codex-gpt-6-sol, 대상 `f8932e0`, 비교 main `17c8058`, E4-L2f 실제 `signing.py` 소스 브랜치 `c3ff659`. mock/offline, 실제 API 0, 제품 코드·Git 수정 0.
- `tests/e3/test_revise.py tests/e3/test_assemble.py tests/e4/test_revise_api.py tests/e4/test_export_revision.py`: **119 passed in 3.79s**. 같은 네 파일에 실제 E4-L2f `signing.py`를 읽기 전용 모듈 주입해 **119 passed in 2.74s**. E4-L2f `test_payload_signing.py` **28 passed in 0.14s**.
- 독립 공개 설정 탐침: 한 IP 잘못된 result 6건 **422×6**, 매번 active/waiting/budget.used **0/0/0**; 다른 IP `/premortem`, `/premortem/revise` **200/200**. F2 채택 저자 답변, F3 취소·상한, F4 이중 서명, F5/F7 수치·신원, F6/F8 조립·다듬기 반례는 대상 테스트 통과.
- `python scripts/verify.py --security`: **보안 454개, verify 통과**. 전체 verify·부하·실제 API는 PM 직렬 큐 지시로 미실행.
- 통합 전 조치: `git diff --check main...HEAD` **rc 1**(`docs/reports/E3-L2r.md:90` 후행 공백). 읽기 전용 merge-tree에서 `src/neumann/api/export.py` 충돌 2곳(`display_text`, `JSON_GENERATOR_NOTE`), 최신 main 기능을 보존해 해결해야 한다. 그 뒤 결합 전체 verify PASS가 병합 조건이다.

명령·출력·한계 상세: `out/codex/results/E3-L2r-verify.md`(로컬 검증 기록).
