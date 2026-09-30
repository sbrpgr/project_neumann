"""시연 영상 mp4 변환·편집본 (E6-L3c). `record_demo.py`가 남긴 webm + JSON으로 만든다.

    python scripts/record_demo_edit.py data/video/demo_<시각>_live.json [--speed 4] [--ffmpeg <경로>]

- `<이름>.mp4`: 전체 녹화를 그대로 H.264(yuv420p, 25fps, faststart)로. PowerPoint 삽입용.
- `<이름>_edit.mp4`: 분석 대기 구간(`observed.analysis_t_click` → `analysis_t_report`)만 `--speed`배로 가속하고,
  그 구간에만 "분석 중(가속 ×N · 실제 대기 S초)" 자막을 넣는다. 나머지는 원래 속도. 자르기·가속 외의 편집은 하지 않는다.
  녹화 중 실패한 단계가 있으면 그 단계 자막이 뜨기 직전(`t_start - 0.4s`)에서 끝낸다(실패 장면을 성공처럼 보이지 않게).
- 샘플 녹화(`sample: true`)는 편집본을 만들지 않는다(`--allow-sample`로만). 파일 이름의 `_sample`/`_live`는 그대로 따라간다.
- 한글 자막 글꼴은 `C:/Windows/Fonts/malgunbd.ttf`(없으면 malgun.ttf). ffmpeg 필터 경로 이스케이프를 피하려고
  글꼴·자막 파일을 출력 폴더의 `_edit/`에 복사해 두고 그 폴더에서 ffmpeg를 부른다.
- 영상은 저장소에 커밋하지 않는다.

종료 코드: 0 성공, 2 입력·ffmpeg 문제.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_FFMPEG = (
    "C:/Users/User/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/"
    "ffmpeg-9.0.2-full_build/bin/ffmpeg.exe"
)
FONTS = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]
FAIL_MARGIN_S = 0.4  # 실패 단계 자막은 단계 시작 뒤 0.2~0.4s에 영상에 뜬다(E6-L3c 프레임 확인)
ENCODE = ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def plan_edit(meta: dict[str, Any], speed: float) -> dict[str, Any]:
    """JSON 메타데이터 → 편집 계획(구간 초·자막 문구·예상 길이). 순수 함수."""
    obs = meta.get("observed") or {}
    t1, t2 = obs.get("analysis_t_click"), obs.get("analysis_t_report")
    if t1 is None or t2 is None or not (0 <= t1 < t2):
        raise ValueError("분석 클릭·리포트 시각이 없다(observed.analysis_t_click/analysis_t_report)")
    if speed < 1:
        raise ValueError("가속 배율은 1 이상")
    end = float(meta.get("duration_s") or meta.get("wall_s") or 0)
    failed = [s for s in meta.get("steps") or [] if s.get("status") == "failed"]
    cut_reason = "전체"
    if failed:
        end = min(end, float(failed[0]["t_start"]) - FAIL_MARGIN_S)
        cut_reason = f"{failed[0]['id']} 단계 실패 → 그 자막 전에서 끝"
    if end <= t2:
        raise ValueError(f"리포트 뒤 남는 구간이 없다(끝 {end:.2f}s ≤ 리포트 {t2:.2f}s)")
    wait = t2 - t1
    label = f"분석 중(가속 ×{speed:g} · 실제 대기 {wait:.1f}초)"
    return {
        "segments": [(0.0, t1, 1.0), (t1, t2, speed), (t2, end, 1.0)],
        "caption": label,
        "end": round(end, 3),
        "cut_reason": cut_reason,
        "expected_s": round(t1 + wait / speed + (end - t2), 3),
    }


def filter_graph(plan: dict[str, Any], fontfile: str, textfile: str) -> str:
    parts, labels = [], []
    for i, (a, b, k) in enumerate(plan["segments"]):
        lab = f"s{i}"
        f = f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{k:g}"
        if k != 1:
            f += (f",drawtext=fontfile={fontfile}:textfile={textfile}:fontsize=30:fontcolor=white"
                  ":box=1:boxcolor=0xB91C1C@0.92:boxborderw=14:x=(w-tw)/2:y=h-150")
        parts.append(f + f"[{lab}]")
        labels.append(f"[{lab}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,fps=25,format=yuv420p[out]")
    return ";".join(parts)


def probe_duration(ffmpeg: str, path: Path) -> float | None:
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split()[1].split(":")
            return round(int(h) * 3600 + int(m) * 60 + float(s), 2)
    return None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", help="record_demo.py가 남긴 JSON")
    ap.add_argument("--speed", type=float, default=4.0)
    ap.add_argument("--ffmpeg", default=DEFAULT_FFMPEG)
    ap.add_argument("--allow-sample", action="store_true")
    args = ap.parse_args(argv)

    jp = Path(args.json)
    meta = json.loads(jp.read_text(encoding="utf-8"))
    webm = jp.with_name(meta["video"])
    if not webm.is_file() or not Path(args.ffmpeg).is_file():
        print(f"[record_demo_edit] 없음: {webm if not webm.is_file() else args.ffmpeg}", file=sys.stderr)
        return 2
    full = webm.with_suffix(".mp4")
    subprocess.run([args.ffmpeg, "-v", "error", "-y", "-i", str(webm), *ENCODE, "-r", "25", str(full)], check=True)
    print(f"[record_demo_edit] mp4: {full} · {probe_duration(args.ffmpeg, full)}s")
    if meta.get("sample") and not args.allow_sample:
        print("[record_demo_edit] 샘플 녹화라 편집본은 만들지 않는다(--allow-sample)")
        return 0

    plan = plan_edit(meta, args.speed)
    work = webm.parent / "_edit"
    work.mkdir(exist_ok=True)
    font = next((f for f in FONTS if Path(f).is_file()), None)
    if font is None:
        print("[record_demo_edit] 한글 글꼴 없음", file=sys.stderr)
        return 2
    shutil.copyfile(font, work / "font.ttf")
    (work / "accel.txt").write_text(plan["caption"], encoding="utf-8")
    edit = webm.with_name(webm.stem + "_edit.mp4")
    graph = filter_graph(plan, "font.ttf", "accel.txt")
    subprocess.run([args.ffmpeg, "-v", "error", "-y", "-i", str(webm.resolve()), "-filter_complex", graph, "-map", "[out]", *ENCODE, str(edit.resolve())],
                   check=True, cwd=work)
    got = probe_duration(args.ffmpeg, edit)
    print(f"[record_demo_edit] 편집본: {edit} · {got}s (예상 {plan['expected_s']}s) · 끝 {plan['end']}s ({plan['cut_reason']})")
    for a, b, k in plan["segments"]:
        print(f"[record_demo_edit]   {a:7.2f}s → {b:7.2f}s  ×{k:g}")
    print(f"[record_demo_edit] 가속 자막: {plan['caption']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
