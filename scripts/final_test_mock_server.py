"""Disposable loopback mock rehearsal server, real API/engines, fake corpus.

No .env, no original datasets, no embedding downloads, no OpenAI calls.
"""
from __future__ import annotations

import argparse
import os
import socket


def build_app():
    for name in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS"):
        os.environ.pop(name, None)
    os.environ.update(NEUMANN_LLM_PROVIDER="mock", NEUMANN_MAX_CONCURRENT="1",
                      NEUMANN_PUBLIC="0", NEUMANN_WARMUP="0", NEUMANN_RESULT_CACHE="0",
                      NEUMANN_RATE_PER_MIN="0", NEUMANN_JOB_RATE_PER_MIN="0")
    from neumann import config
    config.Settings.model_config["env_file"] = None
    config.get_settings.cache_clear()
    from neumann.index import settings as index_config
    index_config.IndexSettings.model_config["env_file"] = None
    index_config.get_index_settings.cache_clear()
    from neumann import llm
    def forbidden(*args, **kwargs):
        raise RuntimeError("live_calls_forbidden_in_final_test_rehearsal")
    llm.OpenAIProvider.call = forbidden
    from neumann.analyze.backend import FixtureBackend
    from neumann.analyze.revise_records import MemoryRecordStore
    from tests.e3.corpus import build
    from neumann.analyze import revise
    import neumann.pipeline as pipeline
    works, reviews = build()
    # Explicit synthetic cross-domain fixture corpus; never product data.
    vocabulary = " protein ligand binding affinity PDBbind docking neural operator FNO Navier-Stokes weather ERA5 climate"
    works = [w.model_copy(update={"abstract": (w.abstract or "") + vocabulary,
                                 "fields": [*w.fields, "protein", "binding", "weather", "operator"]}) for w in works]
    backend = FixtureBackend(works, reviews)
    revise.default_record_store = lambda: MemoryRecordStore(works=works, reviews=reviews, source="fixture")
    engine = pipeline.run_premortem
    def mock_pipeline(plan_text, filename=None, on_stage=None):
        return engine(plan_text, on_stage=on_stage, provider="mock", backend=backend, cache_dir=None)
    pipeline.run_premortem = mock_pipeline
    from neumann.api import main
    main.MAX_CONCURRENT = 1
    main._sem = None
    return main.app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8156)
    args = parser.parse_args()
    if not 8100 <= args.port <= 8199 or args.port == 8171:
        parser.error("use an available 81xx port other than 8171")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            parser.error("port is already occupied")
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, workers=1,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
