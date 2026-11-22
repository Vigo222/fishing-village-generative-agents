"""跑后打分:只读结构化事件日志(events.jsonl)和事实槽答案表(facts.json)。

对日志里每条带文本的事件(说出的话、写入的记忆、取回的记忆、反思),
逐条事实判断"这段文本有没有把这条事实说对",得到信息在哪一环丢失。
判断由评分模型完成(不做关键词匹配);评分模型调用失败则整次打分报错,不出结果。
事实槽只在这里被读取,仿真和接力链都不接触它。

用法: python score.py --events results/relay/<name>/events.jsonl \\
                      --facts data/experiments/example/facts.json --out scores.json
"""

import json
import argparse
from string import Template

from pydantic import BaseModel, Field

from modules.measure import read_events, SCHEMA_VERSION

# 事件类型 -> 测量环节
STAGES = {
    "utterance": "said",          # 说出口(对听的人来说就是"听到")
    "memory_write": "stored",     # 存进记忆
    "memory_retrieve": "retrieved",  # 说话前取回
    "reflection": "reflected",    # 反思产物
}


def event_text(event):
    if event["type"] == "memory_retrieve":
        return "\n".join(event["texts"])
    return event["text"]


def event_agent(event):
    return event["speaker"] if event["type"] == "utterance" else event["agent"]


def check_run(events):
    """无效或没跑完的运行不能打分。"""
    if not events or events[0]["type"] != "run_start":
        raise ValueError("event log does not start with run_start")
    if any(e["schema_version"] != SCHEMA_VERSION for e in events):
        raise ValueError("event log schema_version mismatch")
    ends = [e for e in events if e["type"] == "run_end"]
    starts = [e for e in events if e["type"] == "run_start"]
    if len(ends) != len(starts) or events[-1]["type"] != "run_end":
        raise ValueError("run did not finish (missing run_end)")
    if not all(e["valid"] for e in ends):
        raise ValueError("run is marked invalid; it must not be scored")


def score_events(events, facts, judge, stages=None):
    """judge(fact_statement, text) -> bool。返回逐条判定和按环节汇总的保留率。"""
    check_run(events)
    stages = set(stages or STAGES.values())
    rows = []
    for e in events:
        stage = STAGES.get(e["type"])
        if stage not in stages:
            continue
        if e["type"] == "memory_write" and e["conversation_id"] is None:
            continue  # 与对话无关的记忆(日常事件)不在测量范围
        text = event_text(e)
        for fact in facts:
            rows.append({
                "seq": e["seq"], "stage": stage, "agent": event_agent(e),
                "conversation_id": e.get("conversation_id"),
                "fact_id": fact["id"],
                "present": bool(text) and judge(fact["statement"], text),
            })
    summary = {}
    for r in rows:
        s = summary.setdefault(r["stage"], {"present": 0, "total": 0})
        s["total"] += 1
        s["present"] += int(r["present"])
    for s in summary.values():
        s["retention"] = s["present"] / s["total"]
    return {"rows": rows, "summary": summary}


def make_llm_judge(llm):
    with open("data/prompts/score_fact.txt", "r", encoding="utf-8") as f:
        template = Template(f.read())

    class score_factResponse(BaseModel):
        res: bool = Field(description="文本是否表达了该事实")

    def judge(fact, text):
        return llm.completion(
            template.substitute(fact=fact, text=text),
            return_type=score_factResponse, caller="score_fact",
        )

    return judge


if __name__ == "__main__":
    from dotenv import load_dotenv, find_dotenv
    from modules.model.llm_model import create_llm_model

    load_dotenv(find_dotenv())
    parser = argparse.ArgumentParser(description="post-run scoring from the event log")
    parser.add_argument("--events", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.facts, "r", encoding="utf-8") as f:
        facts = json.load(f)["facts"]
    with open("data/config.json", "r", encoding="utf-8") as f:
        llm_config = json.load(f)["agent"]["think"]["llm"]
    llm_config["temperature"] = 0
    result = score_events(read_events(args.events), facts, make_llm_judge(create_llm_model(llm_config)))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
