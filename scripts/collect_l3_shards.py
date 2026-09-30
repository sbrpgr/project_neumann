"""E1-L3: ResearchArcade 리뷰 샤드 2~5를 HF에서 받아 공유 데이터 폴더 `data/raw/researcharcade/`에 둔다.

    python scripts/collect_l3_shards.py              # 샤드 2~5 받기(있고 sha256이 맞으면 건너뜀)
    python scripts/collect_l3_shards.py --verify     # 받지 않고 저장된 파일의 sha256만 manifest와 대조

- 고정 리비전(corpus_l3.HF_REVIEWS_REVISION)에서 받는다. HF tree API의 LFS sha256·크기와 맞을 때만 제자리에 둔다.
- 받은 URL·시각·크기·sha256은 `data/raw/researcharcade/manifest.json`(키트 manifest와 같은 칸).
- 키트 `공개자료`는 읽기만 한다(샤드 0·1 sha256이 같은 리비전인지 대조).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from neumann.sources import corpus_l3 as l3  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    from neumann.config import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir, help="공유 데이터 폴더(기본 NEUMANN_DATA_DIR)")
    parser.add_argument("--raw-dir", type=Path, default=settings.raw_dir, help="키트 공개자료(샤드 0·1 대조용, 읽기만)")
    parser.add_argument("--shards", type=int, nargs="+", default=list(l3.L3_SHARDS))
    parser.add_argument("--revision", default=l3.HF_REVIEWS_REVISION)
    parser.add_argument("--verify", action="store_true", help="받지 않고 저장된 파일 sha256만 대조")
    args = parser.parse_args()
    raw_l3 = Path(args.data_dir) / l3.RAW_SUBDIR

    if args.verify:
        manifest = l3.load_shard_manifest(raw_l3)
        if not manifest:
            print(f"manifest 없음: {raw_l3 / l3.SHARD_MANIFEST}")
            return 1
        ok = True
        for f in manifest["files"]:
            p = raw_l3 / f["path"]
            digest = l3.sha256_file(p) if p.is_file() else None
            same = digest == f["sha256"] == f.get("hf_lfs_sha256")
            ok &= same
            print(f"{f['path']}: {p.stat().st_size if p.is_file() else '-'}B sha256={digest} {'일치' if same else '불일치'}")
        print("대조:", "전부 일치" if ok else "불일치 있음")
        return 0 if ok else 1

    manifest = l3.fetch_shards(raw_l3, args.shards, revision=args.revision, kit_raw_dir=args.raw_dir)
    print(f"출력: {raw_l3}")
    print(json.dumps({"revision": manifest["revision"], "files": manifest["files"], "kit_consistency": manifest["kit_consistency"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
