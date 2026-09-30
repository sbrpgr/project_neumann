"""E3-L1y 후속④: 캐시 임시 파일 고유화(queries·extract). 같은 키를 여러 스레드가 동시에 써도 깨진 파일·예외가 없다.

임시 파일 이름 `{key}.{pid}.{thread_id}.{uuid4 앞 8자}.tmp` → os.replace로 원자 교체. 실패하면 임시 파일을 지운다.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from neumann.analyze import extract as extract_mod
from neumann.analyze import queries as queries_mod
from neumann.llm import LLMResult

KEY = "a" * 64
N_THREADS = 12
ROUNDS = 25


def _result(i: int) -> LLMResult:
    data = {"queries": [f"q{i}-{j}" for j in range(20)], "pad": "x" * (2000 + i)}  # 스레드마다 길이가 다른 내용
    return LLMResult(ok=True, data=data, provider="openai", model="gpt-6.1-sol", task="query_axes", effort="low")


def _issues(i: int) -> list[dict[str, Any]]:
    return [{"excerpt_id": f"ex{i}-{j}", "risk_code": "R2", "note": "y" * (500 + i)} for j in range(10)]


WRITERS = {
    "queries": lambda d, i: queries_mod._cache_write(d, KEY, _result(i), f"plan{i}"),
    "extract": lambda d, i: extract_mod._cache_write(d, KEY, _issues(i), "gpt-6.1-sol"),
}


def _check_final(module: str, text: str) -> int:
    """파일 내용이 한 쓰기의 온전한 내용인지. 어느 스레드 것인지 돌려준다."""
    data = json.loads(text)
    if module == "queries":
        i = int(data["plan_id"][4:])
        assert data["data"] == _result(i).data
    else:
        i = int(data["issues"][0]["excerpt_id"][2:].split("-")[0])
        assert data["issues"] == _issues(i)
    return i


@pytest.mark.parametrize("module", sorted(WRITERS))
def test_concurrent_writes_same_key_no_torn_file_no_exception(module, tmp_path, caplog):
    write = WRITERS[module]
    barrier = threading.Barrier(N_THREADS + 2)
    errors: list[BaseException] = []
    torn: list[str] = []
    stop = threading.Event()
    final = tmp_path / f"{KEY}.json"

    def writer(i: int) -> None:
        try:
            barrier.wait()
            for _ in range(ROUNDS):
                out = write(tmp_path, i)
                if module == "queries":
                    assert out is True
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        barrier.wait()
        while not stop.is_set():
            try:
                text = final.read_text(encoding="utf-8")
            except OSError:
                continue  # 아직 없음·교체 순간(Windows) — 읽기 쪽은 캐시 없음으로 넘긴다
            try:
                _check_final(module, text)  # 빈 파일·반쯤 쓴 파일이면 실패
            except (ValueError, AssertionError, KeyError, IndexError):
                torn.append(text[:80])
            time.sleep(0.001)

    ws = [threading.Thread(target=writer, args=(i,)) for i in range(N_THREADS)]
    rs = [threading.Thread(target=reader) for _ in range(2)]
    for t in ws + rs:
        t.start()
    for t in ws:
        t.join()
    stop.set()
    for t in rs:
        t.join()
    assert errors == []
    assert torn == [], torn[:3]  # 읽는 쪽이 반쯤 쓴 파일을 본 적이 없다
    assert "캐시 쓰기 실패" not in caplog.text  # 교체가 거부돼 쓰기를 포기한 적도 없다
    assert 0 <= _check_final(module, final.read_text(encoding="utf-8")) < N_THREADS
    assert sorted(p.name for p in tmp_path.iterdir()) == [final.name]  # 임시 파일이 남지 않는다


@pytest.mark.parametrize("module", sorted(WRITERS))
def test_tmp_name_is_unique_per_writer_and_replaced_atomically(module, tmp_path, monkeypatch):
    seen: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((Path(src).name, Path(dst).name))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    ths = [threading.Thread(target=WRITERS[module], args=(tmp_path, i)) for i in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    pat = re.compile(rf"^{KEY}\.{os.getpid()}\.\d+\.[0-9a-f]{{8}}\.tmp$")
    assert all(pat.match(src) and dst == f"{KEY}.json" for src, dst in seen), seen
    assert len({src for src, _ in seen}) == 4  # 쓰는 쪽마다 다른 임시 파일(재시도는 같은 이름)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{KEY}.json"]


@pytest.mark.parametrize("module", sorted(WRITERS))
def test_replace_failure_is_contained_and_cleans_tmp(module, tmp_path, monkeypatch, caplog):
    calls = {"n": 0}

    def deny(src, dst):
        calls["n"] += 1
        raise PermissionError("C:\\Users\\alice\\locked")

    monkeypatch.setattr(os, "replace", deny)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    out = WRITERS[module](tmp_path, 1)  # 예외가 밖으로 나오지 않는다
    if module == "queries":
        assert out is False
    mod = queries_mod if module == "queries" else extract_mod
    assert calls["n"] == mod._REPLACE_TRIES > 1  # 재시도 뒤 포기
    assert list(tmp_path.iterdir()) == []  # 임시 파일 정리, 캐시 파일 없음
    assert "캐시 쓰기 실패: PermissionError" in caplog.text and "alice" not in caplog.text


def test_cache_readers_accept_atomic_files(tmp_path):
    """새 쓰기 방식으로 쓴 파일을 기존 읽기 함수가 그대로 읽는다."""
    extract_mod._cache_write(tmp_path, KEY, _issues(3), "gpt-6.1-sol")
    assert extract_mod._cache_read(tmp_path, KEY) == _issues(3)
    qdir = tmp_path / "q"
    assert queries_mod._cache_write(qdir, KEY, _result(2), "plan2")
    assert json.loads((qdir / f"{KEY}.json").read_text(encoding="utf-8"))["data"] == _result(2).data
