"""测量底座的测试:不联网,模型和向量模型都用假的。"""

import json

import pytest
from llama_index.core import MockEmbedding

import relay
import score
from modules.storage import index as index_module
from modules.model.llm_model import LLMModel
from modules.measure import EventLog, ExperimentParams, LLMCallError, read_events, set_event_log, load_seed_message

SPEC = "data/experiments/example/relay.json"


class FakeLLM(LLMModel):
    """按返回类型给固定答案,并记下收到的每个提示词。"""

    def __init__(self, fail_on=None):
        self.prompts = []
        self.fail_on = fail_on
        super().__init__({"model": "fake", "base_url": "", "api_key": ""})

    def setup(self, config):
        return None

    def _completion(self, prompt, return_type=None, **kwargs):
        kind = return_type.__name__
        self.prompts.append((kind, prompt))
        if kind == self.fail_on:
            raise RuntimeError("boom")
        if kind == "PoignancyChatResponse" or kind == "PoignancyEventResponse":
            return 5
        if kind == "memory_consolidateResponse":
            return ["ADD", "-1", "new"]
        return "<{}>".format(kind)


@pytest.fixture
def agent_config(monkeypatch):
    monkeypatch.setattr(index_module, "OpenAIEmbedding", lambda **kw: MockEmbedding(embed_dim=8))
    with open("data/config.json", "r", encoding="utf-8") as f:
        return json.load(f)["agent"]


def run(tmp_path, agent_config, llm, **params):
    agent_config["experiment"].update(params)
    spec = relay.load_spec(SPEC)
    path = relay.run_relay("t", spec, agent_config, str(tmp_path / "out"), _Logger(), llm, llm)
    return spec, read_events(path)


class _Logger:
    def info(self, *a):
        pass

    debug = warning = error = info


def test_event_log_rejects_wrong_fields(tmp_path):
    log = EventLog(str(tmp_path / "e.jsonl"))
    with pytest.raises(ValueError):
        log.log("utterance", speaker="a", text="x")
    with pytest.raises(KeyError):
        log.log("made_up", x=1)


def test_params_validation():
    with pytest.raises(ValueError):
        ExperimentParams(summary_mode="keywords")
    with pytest.raises(ValueError):
        ExperimentParams(summary_max_chars=0)
    with pytest.raises(TypeError):
        ExperimentParams.from_dict({"unknown_switch": 1})


def test_llm_failure_raises_instead_of_fallback():
    llm = FakeLLM(fail_on="X")
    X = type("X", (), {})
    with pytest.raises(LLMCallError) as e:
        llm.completion("p", retry=3, return_type=X, caller="generate_chat")
    assert e.value.attempts == 3 and "boom" in str(e.value)
    # 回调拒绝模型输出(返回 None)同样算失败,不给替代值
    with pytest.raises(LLMCallError):
        FakeLLM().completion("p", retry=2, callback=lambda r: None, return_type=X)


def test_relay_chain_logs_every_stage(tmp_path, agent_config):
    llm = FakeLLM()
    spec, events = run(tmp_path, agent_config, llm, summary_max_chars=37, reflect=False)
    types = [e["type"] for e in events]
    assert types[0] == "run_start" and events[0]["mode"] == "relay"
    assert events[-1]["type"] == "run_end" and events[-1]["valid"] is True
    said = [e for e in events if e["type"] == "utterance"]
    assert [(e["speaker"], e["listener"]) for e in said] == [("通知员", "甲"), ("甲", "乙"), ("乙", "丙")]
    assert said[0]["text"] == spec["message"] and said[0]["source"] == "scripted"
    stored = [e for e in events if e["type"] == "memory_write"]
    assert [e["agent"] for e in stored] == ["甲", "乙", "丙"]
    assert all(e["stored_form"] == "summary" and e["conversation_id"] for e in stored)
    assert [e["agent"] for e in events if e["type"] == "memory_retrieve"] == ["甲", "乙"]
    assert "reflection" not in types
    # 摘要长度来自参数
    assert any("不超过37字" in p for k, p in llm.prompts if k == "summarize_chatsResponse")
    # 默认条件下,逐字原文只在"听到并做摘要"那一步出现,转述时读不到
    retell_prompts = [p for k, p in llm.prompts if k == "relay_retellResponse"]
    assert len(retell_prompts) == 2
    assert all(spec["message"] not in p for p in retell_prompts)
    assert all("<summarize_chatsResponse>" in p for p in retell_prompts)


def test_verbatim_condition_lets_agent_read_original(tmp_path, agent_config):
    llm = FakeLLM()
    spec, events = run(tmp_path, agent_config, llm, summary_mode="verbatim", reflect=False)
    assert not [k for k, _ in llm.prompts if k == "summarize_chatsResponse"]
    first_retell = [p for k, p in llm.prompts if k == "relay_retellResponse"][0]
    assert spec["message"] in first_retell
    assert all(e["stored_form"] == "verbatim" for e in events if e["type"] == "memory_write")


def test_reflection_switch(tmp_path, agent_config):
    _, events = run(tmp_path, agent_config, FakeLLM(), reflect=True)
    reflections = [e for e in events if e["type"] == "reflection"]
    assert {e["agent"] for e in reflections} == {"甲", "乙", "丙"}
    assert events[0]["params"]["reflect"] is True


def test_consolidation_switch(tmp_path, agent_config):
    _, off = run(tmp_path / "off", agent_config, FakeLLM(), consolidate=False, reflect=False)
    assert not [e for e in off if e["type"] == "consolidation"]


def test_failed_model_call_invalidates_run(tmp_path, agent_config):
    agent_config["experiment"]["reflect"] = False
    spec = relay.load_spec(SPEC)
    out = str(tmp_path / "out")
    with pytest.raises(LLMCallError):
        relay.run_relay("t", spec, agent_config, out, _Logger(), FakeLLM("relay_retellResponse"), FakeLLM())
    events = read_events(out + "/events.jsonl")
    failure = [e for e in events if e["type"] == "llm_failure"]
    assert len(failure) == 1 and failure[0]["caller"] == "relay_retell" and failure[0]["agent"] == "甲"
    assert events[-1]["type"] == "run_end" and events[-1]["valid"] is False
    # 没有任何替代的话被说出口
    assert len([e for e in events if e["type"] == "utterance"]) == 1
    with pytest.raises(ValueError):
        score.score_events(events, [{"id": "f", "statement": "s"}], lambda f, t: True)


def test_fact_slots_cannot_enter_a_run(tmp_path):
    spec = json.load(open(SPEC, encoding="utf-8"))
    spec["facts"] = [{"id": "time", "statement": "x"}]
    bad = tmp_path / "spec.json"
    bad.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        relay.load_spec(str(bad))


def test_scoring_reads_only_the_event_log(tmp_path, agent_config):
    _, events = run(tmp_path, agent_config, FakeLLM(), reflect=False)
    facts = [{"id": "place", "statement": "图书馆二楼"}, {"id": "none", "statement": "不存在"}]
    seen = []

    def judge(fact, text):
        seen.append(text)
        return fact == "图书馆二楼" and "图书馆二楼" in text  # 假评分员,仅用于测试流程

    result = score.score_events(events, facts, judge)
    assert set(result["summary"]) == {"said", "stored", "retrieved"}
    assert result["summary"]["said"] == {"present": 1, "total": 6, "retention": 1 / 6}
    assert len(result["rows"]) == (3 + 3 + 2) * 2


def test_seed_message_spec_rejects_fact_slots(tmp_path):
    seed = {"step": 1, "source": "通知员", "listener": "甲", "message": "m"}
    good = tmp_path / "seed.json"
    good.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    assert load_seed_message(str(good)) == seed
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(dict(seed, facts=[]), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_seed_message(str(bad))


def test_scoring_config_uses_a_model_that_is_not_under_test():
    with open("data/config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    think = config["agent"]["think"]
    assert config["scoring"]["llm"]["model"] not in {think["llm"]["model"], think["llm_fast"]["model"]}
