# E6-pres5: apply the final product form (decisions 2026-10-01 02:5x) and the 대표 direction
# ("an agent that works from start to finish", n=5 as one compact panel, no bigger-data claims)
# to content.json. Idempotent: run on the E6-pres3 content.json (backup) -> writes the new one.
# usage: pres5_content.py <in content.json> <out content.json>
import copy
import json
import sys

SRC, DST = sys.argv[1:3]
C = json.load(open(SRC, encoding="utf-8"))

# 대표 정의 원문(decisions 2026-09-30 23:1x "에이전트 정의(대표 원문)") — 글자 그대로
D = ("Neumann의 에이전트는 불완전한 연구계획을, 불완전한 거절 기록들을 모아 설명해 주고, "
     "완전한 기획으로 다시 재탄생시켜 주는 에이전트.")
POS = "연구를 수행하는 AI 에이전트는 많다. Neumann은 연구를 시작하기 전까지의 전 과정을 맡고, 연구 에이전트와 융합한다."
MB = "【병합 후 확정】"
MM = "【측정 중】"
TOOLS = "Z3 논리 · Pint 단위 · NetworkX 구조 · 산술 일관성"

EMU = 6350  # 1 px at 1920 wide


def px(v):
    return int(round(v * EMU))


def key(spec):
    return (spec["slide"], spec.get("shape"), spec.get("tshape"), spec.get("table"),
            spec.get("row"), spec.get("col"), spec.get("para", 0))


def put_run(spec):
    """Replace the run spec with the same target (slide/shape/cell/para), or append."""
    k = key(spec)
    for i, old in enumerate(C["runs"]):
        if key(old) == k:
            C["runs"][i] = spec
            return
    C["runs"].append(spec)


def drop_runs(pred):
    C["runs"] = [r for r in C["runs"] if not pred(r)]


def put_note(slide, **kw):
    for i, n in enumerate(C["notes"]):
        if n["slide"] == slide:
            C["notes"][i] = dict({"slide": slide}, **kw)
            return
    C["notes"].append(dict({"slide": slide}, **kw))


def small(t, size=7.5, **o):
    return ["r0", t, dict({"size": size, "bold": False}, **o)]


# ---------------------------------------------------------------- slide 1 (표지)
put_run({"slide": 1, "shape": 7, "segs": [["r0", D]]})
put_note(1, set=(
    "팀 데이웨이의 Project Neumann입니다. " + D + " "
    "불완전한 계획서를 넣으면, 비슷한 연구들이 실제로 받은 지적으로 점검하고, 거절 사유를 설명하고, 수정안을 권고합니다. "
    "연구자가 확정하면 마지막으로 한 번 점검해 그 자리에서 고친 초안을 돌려 드립니다. 처음부터 끝까지 수행하는 에이전트입니다. "
    "(수정 권고부터 최종 점검까지는 병합 후 확정)"))

# ---------------------------------------------------------------- slide 2 (목차) — 16·19쪽을 뺐다
put_run({"slide": 2, "shape": 29, "segs": [["r0", "기대 효과 · 사전기획 전주기와 연구 에이전트 융합 · 단계별 중장기 사업"]]})
put_run({"slide": 2, "shape": 30, "segs": [["r0", "14–16"]]})
put_run({"slide": 2, "shape": 34, "segs": [["r0", "19시간 구현 계획"]]})
put_run({"slide": 2, "shape": 35, "segs": [["r0", "17"]]})

# ---------------------------------------------------------------- slide 6 (제안 · 정의 · 전체 흐름)
put_run({"slide": 6, "shape": 4, "segs": [["r0", "Neumann — 점검에서 최종 초안까지, 끝까지 수행하는 에이전트"]]})
put_run({"slide": 6, "shape": 5, "segs": [["r0", D]]})
# 카드 네 장을 줄여(907px → 820px) 아래에 전체 흐름 띠를 크게 둔다
C["geoms"] = [g for g in C.get("geoms", []) if g.get("slide") != 6]
for rect, desc, line, foot in ((12, 15, 16, 17), (18, 21, 22, 23), (24, 27, 28, 29), (30, 33, 34, 35)):
    C["geoms"] += [
        {"slide": 6, "shape": rect, "h": 2189480},
        {"slide": 6, "shape": desc, "h": 666750},
        {"slide": 6, "shape": line, "y": 4667250},
        {"slide": 6, "shape": foot, "y": 4730750},
    ]
C["textboxes"] = [t for t in C["textboxes"] if t.get("slide") != 6]
C["textboxes"].append({
    "slide": 6, "x": 548640, "y": px(832), "w": 11094415, "h": px(24), "anchor": "top", "size": 9,
    "paras": [[["dark", "흐름 — 불완전한 계획서 한 건이 끝까지", {"size": 10.5}],
               ["muted", "   연구자가 확정한 뒤 최종 점검은 한 번, 찾은 오류는 그 자리에서 수정(반복 루프 0) · 수정 권고부터 ",
                {"size": 9, "color": "4F555C"}],
               ["mark", MB, {"size": 8.5}]]]})
C["textboxes"].append({
    "slide": 6, "x": 548640, "y": px(944), "w": 11094415, "h": px(46), "anchor": "top", "size": 8,
    "paras": [[["dark", "에이전트다움  ", {"size": 8.5}],
               ["muted", "① 검증된 절차 — 분석 순서와 최종 점검의 도구 선택은 코드가 정함 · "
                         "② 근거 기반 — 근거 없는 문장은 내보내지 않음, 수치·단위·합계는 도구 결과로만 판정 · "
                         "③ 행동으로 연결 — 거절 사유 해석 → 계획서 수정안 → 확정 뒤 최종 점검에서 그 자리 수정 · "
                         "④ 사람이 결정 — 채택·수정·기각·확정은 연구자, 기록이 남고 연구자만 아는 사실은 [확인 필요] · "
                         "⑤ 시간에 걸친 동반 — 재점검 → 심사 대응 → 사후 감시(다음 단계)",
                {"size": 8, "color": "4F555C"}]]]})

C["boxes"] = [b for b in C.get("boxes", []) if b.get("slide") not in (6, 9)]


def strip(slide, x0, y, h, widths, gap, items, arrow_size=12):
    x = x0
    for i, (w, it) in enumerate(zip(widths, items)):
        C["boxes"].append(dict({"slide": slide, "x": x, "y": y, "w": w, "h": h, "anchor": "middle",
                                "inset": 64008, "fill": "FFFFFF", "radius": 50800}, **it))
        x += w
        if i < len(widths) - 1:
            C["boxes"].append({"slide": slide, "x": x, "y": y, "w": gap, "h": h, "anchor": "middle",
                               "align": "center", "inset": 0, "line": None,
                               "paras": [[["muted", "→", {"size": arrow_size, "color": "8B8B94"}]]]})
            x += gap


def item(title, subs, line, tsize=11, ssize=8.5):
    paras = [[["dark", title, {"size": tsize, "font": "Pretendard SemiBold", "color": "18181B"}]]]
    for s in subs:
        paras.append([["muted", s, {"size": ssize, "color": "52525B"}]])
    return {"paras": paras, "line": line, "line_w": 0.75}


# UI 토큰: --line(구현) · --accent(오늘 만든 재탄생·최종 점검 구간)
GRAY, RED = "E4E4E7", "2F54EB"
gap6 = px(22)
w6 = (11094415 - 5 * gap6) // 6
strip(6, 548640, px(862), px(74), [w6] * 6, gap6, [
    item("불완전한 계획서", ["초안 붙여넣기 · PDF · DOCX"], GRAY),
    item("근거 달린 분석", ["위험카드 · 예상 심사평 · 원문 인용"], GRAY),
    item("수정 권고 · 재탄생", ["거절 사유 해석 · 계획서 수정안"], RED),
    item("연구자 확정", ["채택 · 직접 수정 · 기각"], RED),
    item("최종 점검·수정 한 번", ["도구로 오류 확인 · 그 자리 수정"], RED),
    item("완성도를 높인 초안", ["변경 이력 · 남은 쟁점 · [확인 필요]"], RED),
])
put_note(6, append=(
    D + " 에이전트다움은 자율성의 크기가 아니라, 목표를 끝까지 수행하고 결과를 행동으로 잇는 정도라고 봅니다. "
    "아래 줄이 계획서 한 건이 끝까지 가는 길입니다. 불완전한 계획서를 넣으면 근거 달린 분석으로 위험을 찾고, "
    "거절 사유를 해석해 수정안을 권고하고, 연구자가 채택·수정·기각해 확정하면, 마지막으로 한 번 점검해 "
    "논리·물리·구조 오류를 그 자리에서 고친 초안을 돌려 드립니다. 다시 도는 루프는 없습니다. "
    "수치·단위·합계는 LLM이 아니라 검증 도구의 결과로만 판단하고, 연구자만 아는 사실은 [확인 필요]로 남깁니다. "
    "수정 권고부터 최종 점검까지는 오늘 만든 것이라 병합 뒤에 확정합니다."))

# ---------------------------------------------------------------- slide 9 (AI 구성) — ①~⑦ 전체 흐름 띠
C["textboxes"] = [t for t in C["textboxes"] if not (t.get("slide") == 9 and t.get("pres5"))]
C["textboxes"].append({
    "slide": 9, "pres5": True, "x": 548640, "y": px(884), "w": px(1373), "h": px(22), "anchor": "top", "size": 8.5,
    "paras": [[["dark", "전체 흐름  ", {"size": 9.5}],
               ["muted", "8쪽 ①~③(구현, v1)에 ④~⑦이 이어짐 · ④~⑦ ", {"size": 8.5, "color": "4F555C"}],
               ["mark", MB, {"size": 8}],
               ["muted", " · 연구자 코드 실행은 이번 버전에 없음(로드맵, 15쪽)", {"size": 8.5, "color": "4F555C"}]]]})
gap9 = px(16)
ws9 = [px(135), px(135), px(140), px(130), px(140), px(370)]
ws9.append(px(1373) - sum(ws9) - 6 * gap9)
strip(9, 548640, px(909), px(74), ws9, gap9, [
    item("① 계획서 입력", ["불완전한 초안"], GRAY, 9, 7.5),
    item("② 분석 10단계", ["근거 게이트"], GRAY, 9, 7.5),
    item("③ 리포트", ["위험카드·심사평"], GRAY, 9, 7.5),
    item("④ 수정 권고", ["거절 사유 해석"], RED, 9, 7.5),
    item("⑤ 연구자 확정", ["채택·수정·기각"], RED, 9, 7.5),
    item("⑥ 최종 점검·수정 — 도구 검증", [TOOLS, "유형별 코드 선택 · 오프라인 · 한 번, 그 자리 수정"], RED, 9, 7),
    item("⑦ 완성도를 높인 초안", ["변경 이력 · [확인 필요]"], RED, 9, 7.5),
], arrow_size=10)
for n in C["notes"]:
    if n["slide"] == 9:
        base = n["append"].split(" [E6-pres5] ")[0]
        n["append"] = base + (
            " 8쪽의 ① 기획, ② 분석, ③ 결과 뒤에 ④ 수정 권고, ⑤ 연구자 확정, ⑥ 최종 점검·수정, ⑦ 완성도를 높인 초안이 이어집니다. "
            "최종 점검은 연구자가 확정한 뒤 한 번만 돕니다. 논리·물리·구조 오류를 찾으면 그 자리에서 고치고, 다시 도는 루프는 없습니다. "
            "이때 수치와 단위, 합계는 LLM이 판단하지 않습니다. 점검 유형에 따라 코드가 도구를 고릅니다. "
            "논리와 수치 제약은 Z3, 단위는 Pint, 선행 관계 같은 구조는 NetworkX, 합계는 산술 일관성 검사로 오프라인에서 확인합니다. "
            "연구자만 아는 사실은 지어내지 않고 [확인 필요]로 남깁니다. 연구자의 코드를 실행해 보는 기능은 이번 버전에 없고 로드맵에 있습니다. "
            "④부터 ⑦까지는 오늘 만든 것이라 병합 뒤에 확정합니다.")

# ---------------------------------------------------------------- slide 11 (UI/UX) — 시나리오 띠를 전체 흐름으로
put_run({"slide": 11, "shape": 4, "segs": [["r0", "프로토타입 UI/UX — 계획서 한 건의 점검부터 최종 초안까지"]]})
put_run({"slide": 11, "shape": 21, "segs": [["r0", "시나리오 — 처음부터 끝까지"]]})
put_run({"slide": 11, "shape": 25, "segs": [["r0", "분석 · 근거"]]})
put_run({"slide": 11, "shape": 26, "paras": [[["r0", "유사 연구 10편"]], [["r0", "카드 5장 · 85.0초", {"size": 9}]]]})
put_run({"slide": 11, "shape": 28, "segs": [["r0", "수정 권고"]]})
put_run({"slide": 11, "shape": 29, "paras": [[["m0", MM]], [["r0", "거절 사유 해석 · 수정안", {"size": 9}]]]})
put_run({"slide": 11, "shape": 31, "segs": [["r0", "연구자 확정"]]})
put_run({"slide": 11, "shape": 32, "paras": [[["m0", MM]], [["r0", "채택 · 수정 · 기각", {"size": 9}]]]})
put_run({"slide": 11, "shape": 34, "segs": [["r0", "최종 점검 · 수정"]]})
put_run({"slide": 11, "shape": 35, "paras": [[["m0", MM]], [["r0", "도구 검증 · 그 자리 수정", {"size": 9}]]]})
put_run({"slide": 11, "shape": 37, "segs": [["r0", "완성도를 높인 초안"]]})
put_run({"slide": 11, "shape": 38, "paras": [[["m0", MM]], [["r0", "변경 이력 · [확인 필요]", {"size": 9}]]]})
for t in C["textboxes"]:
    if t.get("slide") == 11 and t["x"] in (2095500, px(372)):
        t["x"], t["w"] = px(372), px(920)
        t["segs"] = [["muted", "시연 예시(선별) · 배터리 전해질 계획서 · 분석까지 9/30 21:13 v1 라이브 · gpt-6.1-sol  "],
                     ["mark", "【v1 확정 전】"]]
for n in C["notes"]:
    if n["slide"] == 11:
        memo = n["set"].split("\n\n", 1)[1] if "\n\n" in n["set"] else ""
        memo = memo.split(" [E6-pres5] ")[0]
        n["set"] = (
            "배터리 전해질 과제 계획서로 실제 화면을 보여 드립니다. 이 계획서는 시연 예시(선별)이고, 성능 주장은 12쪽 백테스트로만 합니다. "
            "분석까지는 9/30 밤 v1 라이브(gpt-6.1-sol) 결과입니다. 85초 만에 유사 연구 10편과 위험카드 5장이 나오고, "
            "카드마다 실제 심사평 인용과 원문 링크가 붙습니다(v1 확정 전). "
            "그다음이 오늘 만든 부분입니다. 카드별로 거절 사유를 해석해 수정안을 권고하고, 연구자가 채택·수정·기각해 확정하면, "
            "최종 점검을 한 번 돌려 논리·물리·구조 오류를 검증 도구로 확인하고 그 자리에서 고친 초안을 돌려 드립니다. "
            "이 뒷부분의 값은 시연 예시 2~3건을 한 번씩 끝까지 돌려 채웁니다(측정 중). "
            "직접 써 보실 수 있도록 프로토타입 주소와 시연 영상을 표지 QR에 두었습니다.\n\n" + memo +
            " [E6-pres5] 시나리오 칸을 전체 흐름(입력 → 분석·근거 → 수정 권고 → 연구자 확정 → 최종 점검·수정 → 초안)으로 바꿈. "
            "뒤 네 칸의 【측정 중】은 전체 흐름 라이브(시연 예시 2~3건, 각 1회, 대표 승인 범위) 뒤 같은 실행 값으로 채운다. "
            "'1위 R2 · 예상 심사평 8문장·근거 번호 23개'는 칸에서 빼고 이 노트에만 둔다.")

# ---------------------------------------------------------------- slide 12 — n=5 한 판, 한계, 사후 칸
put_run({"slide": 12, "shape": 10, "segs": [["r0", "백테스트 n=5 — 일반 LLM과 같은 모델 gpt-6.1-sol · 블라인드 판정 v3"]]})
put_run({"slide": 12, "tshape": 25, "row": 0, "col": 0,
         "segs": [["r0", "지표"], ["r0", "   n=5 · 통계적 결론 없음", {"size": 8.5, "bold": False, "color": "B5171F"}]]})
put_run({"slide": 12, "tshape": 25, "row": 1, "col": 1, "paras": [
    [["r0", "26.7%"]], [small("[6.7, 46.7]", 7)], [small("A 4/15자리", 7)], [small("낸 위험 중 A 4/15", 7)],
    [small("논문 단위 hit@3 0.6", 7)]]})
put_run({"slide": 12, "tshape": 25, "row": 1, "col": 2, "paras": [
    [["r0", "20.0%"]], [small("[0.0, 60.0]", 7)], [small("A 3/15자리(빈 11)", 7)], [small("낸 위험 중 A 3/4", 7)],
    [small("논문 단위 hit@3 0.2", 7)]]})
put_run({"slide": 12, "tshape": 25, "row": 3, "col": 0, "para": 0, "segs": [["r0", "사후 재실행"]]})
put_run({"slide": 12, "tshape": 25, "row": 3, "col": 0, "para": 1,
         "segs": [["r0", "위험 0개 3편에 수정안 시험 적용 · 처음 결과와 섞지 않음"]]})
put_run({"slide": 12, "tshape": 25, "row": 3, "col": 1, "paras": [
    [["r0", "A 1/3", {"size": 10.5}]], [small("같은 1편 · hit@3 1.0")]]})
put_run({"slide": 12, "tshape": 25, "row": 3, "col": 2, "paras": [
    [["r0", "B 1/1", {"size": 10.5}]], [small("1/3편에서 카드 1장")], [small("hit@3 0")]]})
put_run({"slide": 12, "shape": 12, "geom": {"y": 5143500, "h": 914400}, "paras": [
    [["r0", "한계 — n=5(대표 결정, 비용 사유 30→15→5편) · 셔플 대조 없음(특이성 측정 안 함) → 통계적 결론 없음 · "
            "사전 등록 앞 5편(거절 3·채택 2, PDE 4편 편중), 초록에서 결과 문장을 지운 계획서 · "
            "Neumann은 3편에서 위험 0개(빈 자리 11은 적중 아님) · 입력 3편(153·281·287자)은 지금 제품의 300자 미만 거절 대상"
            "(처음 결과는 사전 등록대로) · 판정 v3(주 결과) — Claude Sonnet 3명 블라인드 다수결, 단서 2건 제거, 3명 일치 0.947, "
            "남은 단서(설명 길이·어미) · v2(부분 블라인드) 민감도: Neumann A 4/4 · precision@3 0.267 · hit@3 0.4 · "
            "대표 판정(사실상 비블라인드) 일치율 ", {"size": 7.5}],
     ["m0", MM, {"size": 7.5}], ["r0", " %", {"size": 7.5}]],
    [["r0", "Macro-F1 — gpt-6-astra로 측정, 목표 0.70 미달 · 정답지 DISAPERE 148건(과반 합의), 1회 채점 · "
            "빈도 기준선 0.3308보다 높음은 Macro에서만 · ICLR ML 심사평 기준, AI for Science 성능은 보장 안 함 · "
            "사람 간 상한 0.725는 기획 문서 인용 · 재현 안 함", {"size": 7.5}]],
    [["r0", "E2E — v0 gpt-6-astra 데모 3건 5/5 · v1 gpt-6.1-sol 예시 3건 카드 5·7·7장, 근거 19/19·28/28·27/27, "
            "판정 4건 중 2건 통과 ", {"size": 7.5}],
     ["m0", "【v1 확정 전】", {"size": 7.5}],
     ["r0", " · 수정 권고부터 최종 초안까지 전체 흐름 라이브는 시연 예시 2~3건 ", {"size": 7.5}],
     ["m0", MM, {"size": 7.5}]],
]})
for n in C["notes"]:
    if n["slide"] == 12:
        rest = n["set"].split("\n\n", 1)[1] if "\n\n" in n["set"] else ""
        n["set"] = (
            "못 미친 것부터 말씀드립니다. 백테스트는 5편이라 통계적 결론은 내리지 않습니다. "
            "비용 때문에 30편에서 15편, 다시 5편으로 줄였고, 셔플 대조도 하지 않았습니다. "
            "주 결과는 블라인드 단서 두 가지를 지운 세 번째 판정(v3)입니다. "
            "Neumann이 낸 위험 4개 중 3개는 실제 심사평과 같은 사안이었고 모두 원문 근거가 붙었습니다. "
            "일반 LLM은 낸 위험 15개 중 4개였고 근거는 없습니다. "
            "하지만 Neumann은 5편 중 3편에서 위험을 내지 못해, 논문마다 3자리 기준 적중률은 20.0% 대 26.7%, "
            "논문 단위 적중은 0.2 대 0.6으로 기준선보다 낮고 Top-3 목표 50%에도 못 미칩니다. "
            "또 5편 중 3편(153자·281자·287자)은 지금 제품 기준(300자 미만 거절)이면 분석 전에 거절될 입력입니다. "
            "위험 0개였던 3편과 같은 묶음은 아닙니다. "
            "단서가 남아 있던 앞 판정(v2)의 Neumann 4/4, 논문 단위 0.4는 민감도로만 둡니다. "
            "위험을 내지 못한 3편에 수정안을 시험 적용한 사후 재실행에서는 1편에서 카드 1장이 나왔고 판정은 B였습니다. "
            "처음 결과와 섞지 않고 별도 칸에 적었습니다. 대표 판정은 사실상 비블라인드이고 일치율은 【측정 중】%입니다. "
            "지적 추출 Macro-F1은 0.4864로 목표 0.70에 못 미쳤고, 9/30 저녁 gpt-6-astra로 잰 값입니다. "
            "오늘 발표의 중심은 이 숫자가 아니라, 계획서 한 건이 점검부터 최종 초안까지 끝까지 가는 흐름입니다(6·9·11쪽)."
            + ("\n\n" + rest if rest else ""))

# ---------------------------------------------------------------- slide 14 — 정의 원문, 큰 데이터 주장 삭제
for t in C["textboxes"]:
    if t.get("slide") == 14:
        t["paras"][0] = [["dark", D, {"size": 9}]]
put_run({"slide": 14, "shape": 50, "segs": [["r0",
    "인건비: 과학기술 출연연 1인 평균 연봉 8천만~1억 원대(2026년 보도)에 4대보험을 더한 추정 · "
    "운영비: 지금 규모(색인 1,128편)에서 GPU 없는 서버 1대 기준 추정, 기관 설치형은 GPU 서버 별도"]]})
put_run({"slide": 14, "shape": 48, "segs": [["r0", "서버 1대 · 분석 1건당 LLM 약 200원 이하"]]})
put_note(14, append=D + " " + POS + " 운영비의 1건당 LLM 비용은 분석 단계 추정이고, 수정 권고와 최종 점검까지 포함한 비용은 아직 재지 않았습니다.")

# ---------------------------------------------------------------- slide 15 — 로드맵: NOW = 오늘의 최종 형태
put_run({"slide": 15, "shape": 5, "geom": {"y": 1085000, "h": 380000}, "paras": [
    [["r0", D, {"size": 11}]], [["r0", POS, {"size": 11, "color": "4F555C"}]]]})
put_run({"slide": 15, "tshape": 16, "row": 0, "col": 1, "para": 0, "segs": [["r0", "NOW · 오늘 본선"]]})
put_run({"slide": 15, "tshape": 16, "row": 0, "col": 1, "para": 1,
         "segs": [["r0", "점검 → 설명 → 재탄생 → 최종 점검", {"size": 11}]]})
S = 10
cells = {
    (1, 1): "10단계 분석(구현) → 수정 권고 → 연구자 확정 → 최종 점검 한 번, 오류는 그 자리 수정(반복 루프 0)",
    (1, 2): "연구 질문 정제 → 선행연구 지도 → 계획서 초안 → 구현 경로·연구자 코드 실행(제한 검증) → 제출 요건 점검",
    (1, 3): "실제 심사평 대조 → 근거 달린 답변서(모의 심사위원단 포함)",
    (1, 4): "완성된 기획(계획서 + 위험 목록 + 근거)을 연구 수행 에이전트에 표준 프로토콜(MCP)로 전달",
    (2, 1): "유사 연구 검색 · 위험카드 · 예상 심사평 · 근거 게이트 · 수정 권고 · 최종 점검 도구 검증(Z3·Pint·NetworkX·산술)",
    (2, 2): "질문·가설 다듬기 · 선행연구와 평가이력 지도 · 초안 작성 보조 · 구현 경로와 최소 실행 검증 1건(승인·격리) · 제출 요건 확인",
    (2, 3): "실제 심사평과 예상 심사평 대조 · 근거 달린 답변서 초안 · 관점이 다른 모의 심사위원단",
    (2, 4): "기획 산출물 전달 · 수행 중 위험 재발 감시 · 결과를 다음 기획으로 되먹임",
    (3, 1): "위험카드·수정안 채택·수정·기각 → 확정, [확인 필요] 채우기",
    (3, 2): "질문·초안 확정, 실행 범위 승인",
    (3, 3): "쟁점 채택, 답변 전략 선택",
    (3, 4): "넘길 기획 확정, 감시 알림 검토",
    (4, 1): "하이브리드 검색 · OpenAI 구조화 출력 · 근거 게이트 · 오프라인 검증 도구",
    (4, 2): "계획서 절 단위 대조 · 평가이력 지도 · 격리 실행기 · 제출 요건 규칙",
    (4, 3): "심사평 대조 · 근거 게이트를 거친 답변 초안 · 다관점 모의 심사",
    (4, 4): "MCP 서버 · 기획 산출물 표준 형식 · 모니터링",
}
for (r, c), text in cells.items():
    put_run({"slide": 15, "tshape": 16, "row": r, "col": c, "segs": [["r0", text, {"size": S}]]})
C["tags"] = [t for t in C["tags"] if t.get("slide") != 15]
C["tags"] += [
    {"slide": 15, "tshape": 16, "row": 1, "col": 1, "after": "(반복 루프 0)", "text": MB},
    {"slide": 15, "tshape": 16, "row": 2, "col": 1, "after": "NetworkX·산술)", "text": MB},
]
# 표가 한 줄 길어져 아래 "본선 구현이 이어지는 곳" 묶음을 20px 내린다
C["geoms"] = [g for g in C["geoms"] if g.get("slide") != 15]
for sid, y in ((11, 4956048), (12, 5303520), (13, 5440680), (15, 5440680), (17, 5440680),
               (14, 5440680), (10, 5440680), (18, 5440680)):
    C["geoms"].append({"slide": 15, "shape": sid, "y": y + px(20)})
put_run({"slide": 15, "shape": 10, "para": 0, "segs": [["r0", "결정 로그 · 근거 게이트 · 검증 도구"]]})
put_note(15, set=(
    D + " " + POS + " 본선에서는 첫 구간을 끝까지 만듭니다. 불완전한 계획서를 10단계로 분석하고, 거절 사유를 해석해 수정안을 권고하고, "
    "연구자가 확정하면 최종 점검을 한 번 돌려 논리·물리·구조 오류를 그 자리에서 고친 초안을 돌려 드립니다. "
    "점검은 이미 돌고, 수정 권고부터 최종 점검까지는 오늘 만든 것이라 병합 뒤에 확정합니다. "
    "최종 점검의 도구 검증은 Z3·Pint·NetworkX·산술 일관성이고, 점검 유형별로 코드가 고릅니다. "
    "연구자의 코드를 실제로 실행해 보는 검증은 이번 버전에 없고 STAGE 1에 둡니다. "
    "다음 단계는 연구 질문 정제부터 제출 요건 점검까지 사전기획 전주기, 실제 심사평이 오면 근거 달린 답변서를 쓰는 심사 대응, "
    "그리고 완성된 기획을 연구 수행 에이전트에 MCP로 넘기는 융합입니다. 세 단계 모두 아직 만들지 않은 로드맵이고, "
    "지금 만든 MCP 서버, 결정 로그와 근거 게이트·검증 도구, 거절 기록 코퍼스가 출발점입니다."))

# ---------------------------------------------------------------- slide 16·19 빼기, 17 다시 쓰기
C["delete_slides"] = [16, 19]
drop_runs(lambda r: r["slide"] == 16)
put_run({"slide": 17, "shape": 4, "segs": [["r0", "중장기 사업 — 에이전트 단계별 성과·인력·기간과 실증 연계"]]})
put_run({"slide": 17, "shape": 5, "segs": [["r0",
    "본선은 계획서 한 건이 점검부터 최종 초안까지 끝까지 도는 것의 증명, 이후는 연구 시작 전 전 과정으로 넓히는 사업"]]})
drop_runs(lambda r: r["slide"] == 17 and (r.get("table") or r.get("tshape") == 18))
T17 = {
    (0, 1, 1): [["r0", "지금 — 끝까지 도는 증명"], ["r1", "  "], ["r2", "본선"]],
    (0, 2, 0): [["r0", "STAGE 1"]], (0, 2, 1): [["r0", "사전기획 전주기"]],
    (0, 3, 0): [["r0", "STAGE 2"]], (0, 3, 1): [["r0", "심사 대응"]],
    (0, 4, 0): [["r0", "STAGE 3"]], (0, 4, 1): [["r0", "연구 에이전트와 융합"]],
    (1, 0, 0): [["r0", "범위"]],
    (1, 1, 0): [["r0", "AI 활용 과학 연구 계획서 한 건"]],
    (1, 2, 0): [["r0", "연구 질문부터 제출 요건까지"]],
    (1, 3, 0): [["r0", "심사평을 받은 뒤"]],
    (1, 4, 0): [["r0", "연구 수행 중·후"]],
    (2, 1, 0): [["r0", "불완전한 계획서 → 근거 달린 위험·수정안 → 최종 점검을 거친 초안"]],
    (2, 2, 0): [["r0", "질문·가설 정제, 구현 경로와 최소 실행 검증(승인·격리)"]],
    (2, 3, 0): [["r0", "예상 심사평과 실제 심사평 대조, 근거 달린 답변서 초안"]],
    (2, 4, 0): [["r0", "완성된 기획을 연구 에이전트에 전달, 수행 중 위험 재발 감시"]],
    (3, 2, 0): [["r0", "+ ML·백엔드 엔지니어 2"]],
    (5, 3, 0): [["r0", "파일럿 기관의 실제 심사 대응"]],
}
for (r, c, p_), segs in T17.items():
    put_run({"slide": 17, "tshape": 18, "row": r, "col": c, "para": p_, "segs": segs})
C["tags"] = [t for t in C["tags"] if t.get("slide") != 17]
C["tags"].append({"slide": 17, "tshape": 18, "row": 2, "col": 1, "after": "최종 점검을 거친 초안", "text": MB})
put_run({"slide": 17, "shape": 10, "segs": [["r0", "다음 단계의 출발점  "],
                                          ["r1", "오늘 끝까지 도는 흐름과 근거 게이트·결정 로그·검증 도구를 그대로 넓힘"]]})
put_note(17, set=(
    "그래서 Neumann은 단계별 중장기 사업입니다. 오늘은 계획서 한 건이 점검부터 최종 초안까지 끝까지 도는 것을 만들었고"
    "(수정 권고부터 최종 점검까지는 병합 후 확정), "
    "다음은 연구 질문부터 제출 요건까지, 그다음은 심사 대응과 연구 에이전트와의 융합입니다. "
    "단계마다 엔지니어와 분야 전문가, 보안·법무 인력이 더해집니다. 첫걸음은 출연연 한 곳의 신규 과제 계획서 10건 파일럿입니다. "
    "실패의 기록을 연구 생태계의 공공 자산으로 만들겠습니다. 감사합니다."))

# ---------------------------------------------------------------- 숫자 단일 원본(numbers_frozen.json)으로 덮어쓰기
N = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else None
if N:
    def val(v):  # None -> 【측정 중】 표시 칸
        return ["m0", MM] if v in (None, "") else ["r0", v]

    ALL_MERGED = bool(N["merged"].get("rebirth")) and bool(N["merged"].get("final_check"))
    if ALL_MERGED:  # 병합·화면 확인 뒤: 6·9쪽 머리, 15·16쪽 꼬리표의 【병합 후 확정】을 뗀다
        for t in C["textboxes"]:
            for para in t.get("paras", []):
                if any(s[0] == "mark" and s[1] == MB for s in para):
                    para[:] = [s for s in para if not (s[0] == "mark" and s[1] == MB)]
                    for s in para:
                        s[1] = s[1].replace(" · 수정 권고부터 ", "").replace(" · ④~⑦ ", "")
        C["tags"] = [t for t in C["tags"] if not (t.get("slide") in (15, 17) and t.get("text") == MB)]
    L = N["live_full_flow"]
    for shape, kk in ((29, "revise"), (32, "confirm"), (35, "final_check"), (38, "draft")):
        put_run({"slide": 11, "shape": shape, "paras": [[val(L[kk])], [["r0", L[kk + "_sub"], {"size": 9}]]]})
    A = N["s11_analysis"]
    put_run({"slide": 11, "shape": 26, "paras": [[["r0", A["similar"]]], [["r0", A["sub"], {"size": 9}]]]})
    for t in C["textboxes"]:
        if t.get("slide") == 11 and t["x"] == px(372):
            t["segs"] = [["muted", A["source"]]] + ([["mark", A["source_mark"]]] if A.get("source_mark") else [])
    # 11쪽 캡처 세 자리: src가 없으면 점선 자리표시
    shots = N["s11_shots"]
    old = {i + 1: p for i, p in enumerate(p for p in C["pictures"] if p["slide"] == 11)}
    C["pictures"] = [p for p in C["pictures"] if p["slide"] != 11]
    for k in ("1", "2", "3"):
        s, o = shots[k], old[int(k)]
        geom = {g: o[g] for g in ("x", "y", "w", "h")}
        if s.get("src"):
            C["pictures"].append(dict({"slide": 11, "src": s["src"], "crop": s["crop"]}, **geom))
        else:
            C["pictures"].append(dict({"slide": 11, "placeholder": s["placeholder"]}, **geom))
    for k, cap, desc in (("1", 10, 11), ("2", 14, 15), ("3", 18, 19)):
        put_run({"slide": 11, "shape": cap, "segs": [["r0", shots[k]["title"][0]], ["r1", shots[k]["title"][1]]]})
        if shots[k].get("desc"):
            put_run({"slide": 11, "shape": desc, "segs": [["r0", shots[k]["desc"]]]})
    B = N["backtest"]
    put_run({"slide": 12, "tshape": 25, "row": 1, "col": 1, "paras": [
        [["r0", B["baseline_p3"]]], [small(B["baseline_p3_ci"], 7)], [small(B["baseline_a_slots"], 7)],
        [small(B["baseline_a_risks"], 7)], [small(B["baseline_hit3"], 7)]]})
    put_run({"slide": 12, "tshape": 25, "row": 1, "col": 2, "paras": [
        [["r0", B["neumann_p3"]]], [small(B["neumann_p3_ci"], 7)], [small(B["neumann_a_slots"], 7)],
        [small(B["neumann_a_risks"], 7)], [small(B["neumann_hit3"], 7)]]})
    put_run({"slide": 12, "tshape": 25, "row": 3, "col": 1, "paras": [
        [["r0", B["posthoc_baseline"], {"size": 10.5}]], [small(B["posthoc_baseline_sub"])]]})
    put_run({"slide": 12, "tshape": 25, "row": 3, "col": 2, "paras": [
        [["r0", B["posthoc_neumann"], {"size": 10.5}]], [small(B["posthoc_neumann_sub1"])], [small(B["posthoc_neumann_sub2"])]]})
    ha = B.get("human_agreement")
    p1 = [["r0", B["limits"], {"size": 7.5}]] + ([["r0", ha, {"size": 7.5}]] if ha else [["m0", MM, {"size": 7.5}]]) \
        + [["r0", " %", {"size": 7.5}]]
    e2e = [["r0", B["e2e"], {"size": 7.5}]] + ([["m0", B["e2e_mark"], {"size": 7.5}]] if B.get("e2e_mark") else []) \
        + [["r0", " · 수정 권고부터 최종 초안까지 전체 흐름 라이브는 ", {"size": 7.5}]] \
        + ([["r0", L["e2e_line"], {"size": 7.5}]] if L.get("e2e_line") else
           [["r0", "시연 예시 2~3건 ", {"size": 7.5}], ["m0", MM, {"size": 7.5}]])
    put_run({"slide": 12, "shape": 12, "geom": {"y": 5143500, "h": 914400},
             "paras": [p1, [["r0", B["macro"], {"size": 7.5}]], e2e]})
    S_ = N["stage_line"]
    for r in C["runs"]:
        if r["slide"] == 12 and r.get("shape") == 9:
            r["segs"] = [["r0", "단계 도달  "], ["r1", S_["reached"]]] + \
                ([["m1", S_["reached_mark"]]] if S_.get("reached_mark") else []) + \
                [["r2", "     GitHub  "], ["r3", "github.com/sbrpgr/project_neumann", "https://github.com/sbrpgr/project_neumann"],
                 ["r3", S_["repo_tail"]]]
    put_run({"slide": 14, "shape": 50, "segs": [["r0", N["s14"]["ops_note"]]]})
    put_run({"slide": 14, "shape": 48, "segs": [["r0", N["s14"]["ops_value"]]]})

C["pres5_note"] = ("E6-pres5(2026-10-01 03시): 최종 제품 형태·대표 방향 반영. 이 파일은 build/pres5_content.py가 "
                   "E6-pres3 판 content.json에서 만든다. 16·19쪽은 delete_slides로 빠지고, 쪽 번호는 필드라 저절로 바뀐다.")

json.dump(C, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("runs", len(C["runs"]), "boxes", len(C["boxes"]), "textboxes", len(C["textboxes"]),
      "tags", len(C["tags"]), "notes", len(C["notes"]), "delete", C["delete_slides"])
