# E6-pres5 one-command deck build: numbers_frozen.json -> content.json -> stage1.pptx -> pptx + pdf (+ png).
# usage (from data/deck):  python build/pres5_build.py <numbers_frozen.json> [--png]
#   base content : _backup_E6-pres5_20261001_0300/build/content.json (E6-pres3 final, never edited)
#   kit original : 노이만_본선자료/발표자료/본선_발표자료.pptx (read only)
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DECK = os.path.dirname(HERE)
PY = sys.executable
NUM = os.path.abspath(sys.argv[1])
PNG = "--png" in sys.argv[2:]
BASE = os.path.join(DECK, "_backup_E6-pres5_20261001_0300", "build", "content.json")
KIT = "C:/Users/User/Desktop/노이만_본선자료/발표자료/본선_발표자료.pptx"


def run(*args):
    print(">", " ".join(os.path.basename(a) if os.path.isabs(a) else a for a in args), flush=True)
    subprocess.run([PY, *args], check=True, cwd=DECK)


run(os.path.join(HERE, "pres5_content.py"), BASE, os.path.join(HERE, "content.json"), NUM)
run(os.path.join(HERE, "build_deck.py"), KIT, os.path.join(HERE, "content.json"),
    os.path.join(HERE, "stage1.pptx"), os.path.join(HERE, "img"))
png_dir = os.path.join(DECK, "preview") if PNG else "-"
if PNG:
    for f in glob.glob(os.path.join(png_dir, "slide_*.png")):
        os.remove(f)  # 쪽 수가 줄면 옛 PNG가 남지 않게
run(os.path.join(HERE, "finalize.py"), os.path.join(HERE, "stage1.pptx"),
    os.path.join(DECK, "본선_발표자료_작업본.pptx"), os.path.join(DECK, "본선_발표자료_작업본.pdf"), png_dir, "1920")
print("done")
