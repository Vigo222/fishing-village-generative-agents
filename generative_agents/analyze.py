"""主实验指标提取与 A/B 对比(实验设计第五节;条件2:两组用同一脚本、同一逻辑)。
从 exp-{arm}-s{seed} 的存档 + conversation.json 提取对两组公平的因变量,按臂聚合
(均值±标准差),输出对比表 + analyze.json。纯离线,零额外跑批。

用法:python analyze.py            # 处理 results/checkpoints 下所有 exp-* 运行
"""
import os
import sys
import json
import glob
import math
import argparse

sys.stdout.reconfigure(encoding="utf-8")

STRANGER = "用户分身"
CKPT = "results/checkpoints"
# 涉陌生人(存在/来意)关键词
RELATED = ["用户分身", "陌生", "外来", "生面孔", "客商", "收海货", "收鱼",
           "寻亲", "寻找", "妹妹", "阿妹", "失散"]
# 真实来意关键词(认知准确性:识破"寻亲")
TRUE_INTENT = ["寻亲", "寻找", "妹妹", "阿妹", "失散"]
RESIDENTS = ["老陈", "阿香", "符大爷", "小林", "吴婆婆"]


def parse_pair(key):
    head = key.split(" @ ")[0]
    return head.split(" -> ", 1) if " -> " in head else (head, None)


def step_of(time_str, start="20240213-09:30", stride=30):
    import datetime
    t0 = datetime.datetime.strptime(start, "%Y%m%d-%H:%M")
    t = datetime.datetime.strptime(time_str, "%Y%m%d-%H:%M")
    return int((t - t0).total_seconds() / 60 / stride) + 1


def analyze_run(name):
    conv_path = f"{CKPT}/{name}/conversation.json"
    if not os.path.exists(conv_path):
        return None
    conv = json.load(open(conv_path, encoding="utf-8"))

    learned_exist, learned_true, initiated = {}, {}, {}
    for t in sorted(conv.keys()):
        for entry in conv[t]:
            for key, chats in entry.items():
                a, b = parse_pair(key)
                text = " ".join(c[1] for c in chats)
                related = (a == STRANGER or b == STRANGER or any(k in text for k in RELATED))
                if not related:
                    continue
                for who in (a, b):
                    if who in RESIDENTS:
                        learned_exist.setdefault(who, step_of(t))
                        if any(k in text for k in TRUE_INTENT):
                            learned_true.setdefault(who, step_of(t))
                # 居民主动找分身搭话(发起方=居民,响应方=分身)
                if a in RESIDENTS and b == STRANGER:
                    initiated[a] = initiated.get(a, 0) + 1

    # 认知更新:居民 consolidation_log 中涉陌生人的 UPDATE/CONFLICT
    upd_conf = 0
    files = sorted(glob.glob(f"{CKPT}/{name}/simulate-*.json"))
    if files:
        d = json.load(open(files[-1], encoding="utf-8"))
        for rname in RESIDENTS:
            log = d["agents"].get(rname, {}).get("associate", {}).get("consolidation_log", [])
            for l in log:
                if l["action"] in ("UPDATE", "CONFLICT") and \
                   any(k in (l.get("new", "") + l.get("old", "")) for k in RELATED):
                    upd_conf += 1

    return {
        "breadth": len(learned_exist),                       # 知道陌生人存在的居民数
        "true_intent_count": len(learned_true),              # 识破"寻亲"的居民数
        "mean_exist_step": round(sum(learned_exist.values()) / len(learned_exist), 2) if learned_exist else None,
        "mean_true_step": round(sum(learned_true.values()) / len(learned_true), 2) if learned_true else None,
        "initiated_total": sum(initiated.values()),          # 居民主动搭话总次数
        "update_conflict": upd_conf,                         # 认知更新条数
    }


def agg(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return ("-", "-")
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))
    return (round(m, 2), round(sd, 2))


def main():
    argparse.ArgumentParser().parse_args()
    arms = {"on": [], "off": []}
    for name in sorted(os.path.basename(p) for p in glob.glob(f"{CKPT}/exp-*")):
        for arm in arms:
            if name.startswith(f"exp-{arm}-"):
                r = analyze_run(name)
                if r:
                    r["run"] = name
                    arms[arm].append(r)

    metrics = [("传播广度(知存在居民数)", "breadth"),
               ("识破寻亲居民数", "true_intent_count"),
               ("平均获知步(越小越快)", "mean_exist_step"),
               ("平均识破步", "mean_true_step"),
               ("居民主动搭话总数", "initiated_total"),
               ("认知更新(UPDATE/CONFLICT)", "update_conflict")]

    print("=== 主实验 A/B 对比(均值±标准差;A=反思开 n={}, B=反思关 n={})===".format(
        len(arms["on"]), len(arms["off"])))
    print(f"{'指标':28s} {'A 反思开':>16s} {'B 反思关':>16s}")
    summary = {}
    for label, key in metrics:
        am, asd = agg([r[key] for r in arms["on"]])
        bm, bsd = agg([r[key] for r in arms["off"]])
        summary[key] = {"A_mean": am, "A_sd": asd, "B_mean": bm, "B_sd": bsd}
        print(f"{label:28s} {f'{am}±{asd}':>16s} {f'{bm}±{bsd}':>16s}")

    out = {"per_run": arms, "summary": summary}
    os.makedirs("results/compressed", exist_ok=True)
    with open("results/compressed/analyze.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n[数据] results/compressed/analyze.json")
    if not arms["on"] and not arms["off"]:
        print("(尚无 exp-* 运行;跑批后再执行)")


if __name__ == "__main__":
    main()
