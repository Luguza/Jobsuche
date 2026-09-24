import json
from types import SimpleNamespace

from jobmap.scoring import score_companies


def company(key, name, **extra):
    return {"key": key, "name": name, "sources": ["osm"], "tags": [], **extra}


class FakeMessages:
    def __init__(self, scores, stop_reason="end_turn"):
        self.scores, self.stop_reason, self.requests = scores, stop_reason, []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        user = kwargs["messages"][0]["content"]
        ids = [json.loads(line)["id"] for line in user.splitlines()[1:]]
        results = [{"id": i, "score": self.scores.get(i, 5), "reason": f"Begründung {i}"} for i in ids]
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps({"results": results}))])


def fake_client(scores, **kw):
    messages = FakeMessages(scores, **kw)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages), messages=messages), messages


def test_keyword_fallback_without_llm(cfg):
    companies = [company("akku", "Akku-Simulation GmbH"), company("baecker", "Bäckerei Schmidt")]
    cache = score_companies(companies, cfg, {}, use_llm=False)
    assert cache == {}
    assert companies[0]["score"] > companies[1]["score"]
    assert companies[0]["score_method"] == "stichwörter"


def test_claude_scores_are_cached_and_reused(cfg):
    client, messages = fake_client({"a": 12, "b": 3})
    companies = [company("a", "A GmbH", job_refs=["1"]), company("b", "B GmbH")]
    cache = score_companies(companies, cfg, {}, client=client)
    assert companies[0]["score"] == 10  # auf 0-10 begrenzt
    assert companies[0]["score_method"] == "claude"
    assert set(cache) == {"a", "b"} and cache["b"]["model"] == cfg["scoring"]["llm"]["model"]
    request = messages.requests[0]
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert request["output_config"]["format"]["type"] == "json_schema"

    # Zweiter Lauf: nur die neue Firma wird angefragt
    companies = [company("a", "A GmbH"), company("b", "B GmbH"), company("c", "C GmbH")]
    score_companies(companies, cfg, cache, client=client)
    assert len(messages.requests) == 2
    assert '"id": "c"' in messages.requests[1]["messages"][0]["content"]
    assert '"id": "a"' not in messages.requests[1]["messages"][0]["content"]


def test_refusal_keeps_keyword_score_and_does_not_cache(cfg):
    client, _ = fake_client({"a": 9}, stop_reason="refusal")
    companies = [company("a", "Batterie Simulation GmbH")]
    cache = score_companies(companies, cfg, {}, client=client)
    assert cache == {}
    assert companies[0]["score_method"] == "stichwörter"


def test_manual_score_from_seed(cfg):
    companies = [company("s", "Seed GmbH", manual_score=8, manual_reason="Kenne ich")]
    score_companies(companies, cfg, {}, use_llm=False)
    assert companies[0]["score"] == 8 and companies[0]["score_method"] == "manuell"
