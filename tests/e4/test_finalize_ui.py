from pathlib import Path


def test_finalization_single_action_safe_dom_and_download():
    source = Path("src/neumann/webui/index.html").read_text(encoding="utf-8")
    assert "'수정 확정·검증', 'rvFinalize'" in source
    assert "fetch('premortem/finalize'" in source  # 결정된 경로(옛 /premortem/revise/finalize는 서버 alias)
    assert "var body = assembleBody('json'); body.polish = false;" in source
    assert "body.confirmed_text = currentAsm().paras" in source
    assert "body.confirmed_base_id = st.asm.raw.revised_plan_id" in source
    panel = source.split("function finalizationPanel(st)", 1)[1].split("/* 서버 assemble", 1)[0]
    assert "innerHTML" not in panel and "el('pre', null, T(out.final_text))" in panel
    assert "result.tool_checks_before" in panel and "result.tool_checks_after" in panel
    assert "neumann_final_plan.md" in source
    assert "invalidateFinalization(); dc.text" in source
    assert "confirm(" not in source.split("function requestFinalization()", 1)[1].split("function finalizationPanel", 1)[0]
