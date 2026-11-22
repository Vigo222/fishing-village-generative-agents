"""接力链模式(受控传话):源消息 -> A -> B -> C ...

与场景无关:不需要地图、日程、移动,只跑"听到 -> 存进记忆 -> (反思) -> 取回 -> 转述"。
存储、整合、反思用的是和自然相遇同一份代码(modules/memory_ops.py),
所以这里测到的记忆层行为就是仿真里的记忆层行为。

链条说明文件(--spec)只描述谁传给谁、源消息原文和各人人设;
事实槽(答案表)不在这里,只交给 score.py,因此不可能进入提示词或记忆。

用法: python relay.py --name relay-test --spec data/experiments/example/relay.json \\
                      --experiment data/experiments/example/params.json
"""

import os
import copy
import json
import argparse

from dotenv import load_dotenv, find_dotenv

from modules import memory, prompt, utils
from modules.memory_ops import MemoryOps
from modules.model.llm_model import create_llm_model
from modules.measure import EventLog, ExperimentParams, set_event_log

SPEC_KEYS = {"start", "gap_minutes", "chain", "source", "message", "agents"}
RELAY_ADDRESS = ["relay"]


def load_spec(path):
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    if set(spec) != SPEC_KEYS:
        raise ValueError(
            "relay spec keys must be exactly {}, got {}".format(sorted(SPEC_KEYS), sorted(spec))
        )
    if len(spec["chain"]) < 2 or len(set(spec["chain"])) != len(spec["chain"]):
        raise ValueError("chain needs at least 2 distinct agents")
    for name in spec["chain"]:
        if set(spec["agents"][name]) != {"currently", "scratch"}:
            raise ValueError("agent '{}' must have exactly: currently, scratch".format(name))
    return spec


class RelayAgent(MemoryOps):
    def __init__(self, name, persona, agent_config, storage_root, logger, llm=None, llm_fast=None):
        self.name = name
        self.logger = logger
        self.params = ExperimentParams.from_dict(agent_config["experiment"])
        self.conversation_id = None
        self.chats = []
        self.scratch = prompt.Scratch(name, persona["currently"], persona["scratch"])
        self.associate = memory.Associate(
            os.path.join(storage_root, name, "associate"), **agent_config["associate"]
        )
        think = agent_config["think"]
        self._llm = llm or create_llm_model(think["llm"])
        self._llm_fast = llm_fast or (
            create_llm_model(think["llm_fast"]) if think.get("llm_fast") else self._llm
        )
        self.fast_callers = set(think.get("fast_callers", ["poignancy_chat"]))

    def _route_llm(self, func_hint):
        return self._llm_fast if func_hint in self.fast_callers else self._llm

    def current_address(self):
        return RELAY_ADDRESS

    def hear(self, speaker, text, conversation_id, event_log, source):
        """听到一句话并存进记忆;逐字原文只进事件日志。"""
        self.conversation_id = conversation_id
        event_log.log(
            "utterance", conversation_id=conversation_id, turn=0,
            speaker=speaker, listener=self.name, text=text, source=source,
        )
        chats = [(speaker, text)]
        stored = self._chat_memory_text(chats)
        event = memory.Event(self.name, "对话", speaker, describe=stored, address=RELAY_ADDRESS)
        self._add_concept("chat", event)
        self.chats.extend(self._readable_chats(chats, stored, speaker))
        if self.params.reflect:
            self._reflect_chats()
        self.chats = []

    def retell(self, source, listener, conversation_id, event_log):
        """取回关于 source 的记忆,转述给 listener。只能用取回到的内容。"""
        self.conversation_id = conversation_id
        nodes, seen = [], set()
        candidates = self.associate.retrieve_chats(source) + self.associate.retrieve_focus(
            ["{} 告诉 {} 的事情".format(source, self.name)], 15
        )
        for node in candidates:
            if node.node_id not in seen:
                seen.add(node.node_id)
                nodes.append(node)
        event_log.log(
            "memory_retrieve", conversation_id=conversation_id, turn=0,
            agent=self.name, listener=listener,
            node_ids=[n.node_id for n in nodes], texts=[n.describe for n in nodes],
        )
        return self.completion("relay_retell", source, listener, [n.describe for n in nodes])


def run_relay(name, spec, agent_config, out_dir, logger, llm=None, llm_fast=None):
    """跑一条接力链,返回事件日志路径。llm/llm_fast 仅供测试注入。"""
    params = ExperimentParams.from_dict(agent_config["experiment"])
    agent_config = params.apply_to_agent_config(copy.deepcopy(agent_config))
    timer = utils.set_timer(spec["start"])
    event_log = set_event_log(EventLog(os.path.join(out_dir, "events.jsonl")))
    event_log.start_run(name, "relay", params.to_dict())
    try:
        agents = {
            n: RelayAgent(n, spec["agents"][n], agent_config, out_dir, logger, llm, llm_fast)
            for n in spec["chain"]
        }
        speaker, text, source = spec["source"], spec["message"], "scripted"
        for hop, listener in enumerate(spec["chain"]):
            conv_id = "hop{}|{}|{}".format(hop, speaker, listener)
            agents[listener].hear(speaker, text, conv_id, event_log, source)
            if hop + 1 == len(spec["chain"]):
                break
            timer.forward(spec["gap_minutes"])
            next_listener = spec["chain"][hop + 1]
            next_conv = "hop{}|{}|{}".format(hop + 1, listener, next_listener)
            text = agents[listener].retell(speaker, next_listener, next_conv, event_log)
            speaker, source = listener, "agent"
        for agent in agents.values():
            agent.associate.index.save()
    except BaseException as e:
        event_log.end_run(name, error="{}: {}".format(type(e).__name__, e))
        raise
    event_log.end_run(name)
    return event_log.path


if __name__ == "__main__":
    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="controlled relay chain")
    parser.add_argument("--name", type=str, required=True)
    parser.add_argument("--spec", type=str, required=True, help="relay chain spec JSON")
    parser.add_argument("--experiment", type=str, default="", help="experiment parameters JSON; empty=use data/config.json")
    parser.add_argument("--temp", type=float, default=None)
    parser.add_argument("--verbose", type=str, default="info")
    args = parser.parse_args()

    with open("data/config.json", "r", encoding="utf-8") as f:
        agent_config = json.load(f)["agent"]
    if args.experiment:
        with open(args.experiment, "r", encoding="utf-8") as f:
            agent_config["experiment"] = json.load(f)
    if args.temp is not None:
        for key in ("llm", "llm_fast"):
            if key in agent_config["think"]:
                agent_config["think"][key]["temperature"] = args.temp

    out_dir = "results/relay/{}".format(args.name)
    if os.path.exists(out_dir):
        raise SystemExit("'{}' already exists, choose a new --name".format(out_dir))
    path = run_relay(args.name, load_spec(args.spec), agent_config, out_dir, utils.create_io_logger(args.verbose))
    print("events:", path)
