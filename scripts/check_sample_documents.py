"""Check selected files with an explicitly chosen checkout's upload extractor.

Example: --extractor-root C:/Users/User/Desktop/project_neumann
No analysis, server, providers, .env reads, or network access are needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(extractor_root: Path) -> dict:
    for name in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS"):
        os.environ.pop(name, None)
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
    sys.path.insert(0, str(extractor_root / "src"))
    from neumann.config import Settings

    Settings.model_config["env_file"] = None
    from neumann.api.upload import UploadRejected, _clean, extract_plan

    def deny(*_args, **_kwargs):
        raise RuntimeError("Document verification must not open network connections")

    socket.socket.connect = deny
    registry = json.loads((ROOT / "src/neumann/api/templates/samples.json").read_text(encoding="utf-8"))
    extractor = extractor_root / "src/neumann/api/upload.py"
    commit = subprocess.check_output(["git", "-c", f"safe.directory={extractor_root.as_posix()}",
                                      "rev-parse", "HEAD"], cwd=extractor_root, text=True).strip()
    output = {"extractor_commit": commit, "extractor_sha256": hashlib.sha256(extractor.read_bytes()).hexdigest(),
              "documents": []}
    compact = lambda t: re.sub(r"\s+", "", unicodedata.normalize("NFC", t))
    for item in registry["samples"]:
        if item["status"] != "featured" or item["kind"] != "plan":
            continue
        expected = (ROOT / item["path"]).read_text(encoding="utf-8")
        for fmt, filename in item["documents"].items():
            path = ROOT / "src/neumann/api/templates/samples/docs" / filename
            measurement = {"id": item["id"], "format": fmt, "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            try:
                result = extract_plan(filename, path.read_bytes())
            except UploadRejected as exc:
                measurement.update(status=exc.status_code, reason=exc.message)
                if fmt != "hwpx" or exc.status_code != 415:
                    raise
            else:
                same = compact(result.text) == compact(expected)
                if not same:
                    raise RuntimeError(filename + ": original characters changed")
                exact = result.text == _clean(expected, collapse_blank=True)
                if fmt == "docx" and not exact:
                    raise RuntimeError(filename + ": paragraph text changed")
                measurement.update(status=200, original_nonspace_equal=same, clean_text_exact=exact,
                                   pages=result.pages, warnings=list(result.warnings))
            output["documents"].append(measurement)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.extractor_root.resolve())
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
