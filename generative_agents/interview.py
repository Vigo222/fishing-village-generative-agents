"""采访通道(自研功能③):模拟结束后,向任一智能体(含注入的用户分身)提问,
基于其记忆流 + 人设单次作答。完全离线、不碰模拟主流程,符合"暂停/结束后采访"形态。

用法:
  python interview.py --name <run> --agent 用户分身 --question "你今天过得怎么样?"
  python interview.py --name <run> --agent 老陈            # 进入交互问答(空行退出)
"""
import os
import sys
import json
import glob
import argparse

from dotenv import load_dotenv, find_dotenv

from modules import utils
from modules.memory.associate import Associate
from modules.model.llm_model import create_llm_model
from modules.prompt.scratch import Scratch

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(find_dotenv())


def latest_checkpoint(run_name):
    files = sorted(glob.glob(f"results/checkpoints/{run_name}/simulate-*.json"))
    if not files:
        raise FileNotFoundError(f"找不到运行 '{run_name}' 的存档")
    return json.load(open(files[-1], encoding="utf-8"))


def build_interviewee(run_name, agent_name):
    cfg = json.load(open("data/config.json", encoding="utf-8"))["agent"]
    ckpt = latest_checkpoint(run_name)

    if agent_name not in ckpt["agents"]:
        raise KeyError(f"'{agent_name}' 不在该运行中。在场的有: {list(ckpt['agents'].keys())}")
    saved = ckpt["agents"][agent_name]

    # 时钟设到存档时刻,保证 Associate 清理逻辑不误删运行期记忆
    utils.set_timer(start=ckpt["time"])

    # 人设(scratch 取静态 agent.json,currently 取存档里运行后的最新状态)
    persona = utils.load_dict(
        f"frontend/static/assets/village/agents/{agent_name.replace(' ', '_')}/agent.json"
    )
    scratch = Scratch(agent_name, saved.get("currently", persona["currently"]), persona["scratch"])

    # 记忆库:指向该运行该 agent 的持久化向量库 + 存档里的 memory 索引
    storage = f"results/checkpoints/{run_name}/storage/{agent_name}/associate"
    associate = Associate(
        storage,
        cfg["associate"]["embedding"],
        retention=cfg["associate"].get("retention", 8),
        memory=saved.get("associate", {}).get("memory"),
    )

    # 采访用旗舰模型、温度 0.5(求自然腔调)
    llm_cfg = dict(cfg["think"]["llm"])
    llm_cfg["temperature"] = 0.5
    llm = create_llm_model(llm_cfg)
    return scratch, associate, llm


def answer(scratch, associate, llm, question, top_k=15):
    # 检索与问题最相关的记忆;空则回退到近期事件/对话/想法
    memories = associate.retrieve_focus([question], retrieve_max=top_k)
    if not memories:
        memories = (associate.retrieve_events() + associate.retrieve_chats()
                    + associate.retrieve_thoughts())
    res = scratch.prompt_interview(question, memories)._asdict()
    return llm.completion(**res), len(memories)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="运行名(results/checkpoints 下)")
    ap.add_argument("--agent", required=True, help="受访智能体名(含 用户分身)")
    ap.add_argument("--question", default="", help="单次提问;留空进入交互模式")
    args = ap.parse_args()

    scratch, associate, llm = build_interviewee(args.name, args.agent)

    def ask(q):
        ans, n = answer(scratch, associate, llm, q)
        print(f"\n【{args.agent}】（检索到 {n} 条相关记忆）\n{ans}\n")

    if args.question:
        ask(args.question)
    else:
        print(f"=== 采访 {args.agent}(运行 {args.name});直接输入问题,空行退出 ===")
        while True:
            try:
                q = input("问> ").strip()
            except EOFError:
                break
            if not q:
                break
            ask(q)


if __name__ == "__main__":
    main()
