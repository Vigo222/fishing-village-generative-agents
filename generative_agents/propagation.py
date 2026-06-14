"""副实验:信息传播追踪。从某次运行的 conversation.json 提取"陌生人(用户分身)
来到/来意"这条信息在村中的传播链:谁先知道、谁传给谁、何时。产出传播网络图 +
传播速度(获知人数累积)。零额外跑批,复用主实验存档。

用法:python propagation.py --name <run> [--out results/compressed/<run>]

注:谁传给谁的判定是基于"对话时间序 + 参与方 + 内容涉及陌生人"的启发式推断
(对话中已知者→未知者),非绝对真值;报告中如实标注为推断。
"""
import os
import sys
import json
import glob
import argparse

sys.stdout.reconfigure(encoding="utf-8")

STRANGER = "用户分身"
KEYWORDS = ["用户分身", "陌生", "外来", "生面孔", "客商", "收海货", "收鱼",
            "寻亲", "寻找", "妹妹", "阿妹", "失散"]


def parse_participants(key):
    # key 形如 "老陈 -> 阿香 @ the Ville，码头，..."
    head = key.split(" @ ")[0]
    if " -> " in head:
        a, b = head.split(" -> ", 1)
        return a.strip(), b.strip()
    return head.strip(), None


def load_conversations(run_name):
    path = f"results/checkpoints/{run_name}/conversation.json"
    conv = json.load(open(path, encoding="utf-8"))
    items = []  # (time, speaker, listener, text)
    for t in sorted(conv.keys()):
        for entry in conv[t]:
            for key, chats in entry.items():
                a, b = parse_participants(key)
                text = " ".join(c[1] for c in chats)
                items.append((t, a, b, text))
    return items


def trace(items):
    """返回 first_known{name:time}、edges[(src,dst,time)]、knowers 顺序"""
    knowers = {STRANGER}          # 分身是信息源
    first_known = {}
    edges = []
    order = []
    for t, a, b, text in items:
        related = (a == STRANGER or b == STRANGER
                   or any(k in text for k in KEYWORDS))
        if not related or b is None:
            continue
        a_knew, b_knew = a in knowers, b in knowers
        # 已知者 → 未知者(信息传递)
        if a_knew and not b_knew:
            edges.append((a, b, t)); first_known[b] = t; order.append((b, t))
        elif b_knew and not a_knew:
            edges.append((b, a, t)); first_known[a] = t; order.append((a, t))
        elif not a_knew and not b_knew:
            # 两边都还不知道却谈及陌生人:以发起者为源记一条
            edges.append((a, b, t)); first_known[b] = t; order.append((b, t))
            first_known.setdefault(a, t)
        knowers.update([a, b])
    return first_known, edges, order


def draw(edges, first_known, out_png):
    try:
        import networkx as nx
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception as e:
        print(f"[图] 跳过(缺 networkx/matplotlib: {e});数据见 JSON")
        return False
    g = nx.DiGraph()
    g.add_node(STRANGER)
    for s, d, t in edges:
        g.add_edge(s, d, time=t)
    pos = nx.spring_layout(g, seed=1)
    plt.figure(figsize=(8, 6))
    colors = ["#e07a5f" if n == STRANGER else "#81b29a" for n in g.nodes()]
    nx.draw(g, pos, with_labels=True, node_color=colors, node_size=2200,
            font_family="SimHei", font_size=12, arrowsize=20, edge_color="#3d405b")
    elabels = {(s, d): t.split("-")[-1] for s, d, t in edges}
    nx.draw_networkx_edge_labels(g, pos, edge_labels=elabels, font_size=9, font_family="SimHei")
    plt.title("陌生人信息传播网络(边标注传播时刻)", fontfamily="SimHei")
    plt.tight_layout()
    plt.savefig(out_png, dpi=120)
    plt.close()
    print(f"[图] 已保存: {out_png}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out_dir = args.out or f"results/compressed/{args.name}"
    os.makedirs(out_dir, exist_ok=True)

    items = load_conversations(args.name)
    first_known, edges, order = trace(items)

    residents = {k: v for k, v in first_known.items() if k != STRANGER}
    print(f"=== 运行 {args.name} 传播追踪 ===")
    print(f"涉及陌生人的对话场次: {sum(1 for t,a,b,x in items if a==STRANGER or b==STRANGER or any(k in x for k in KEYWORDS))}")
    print(f"\n获知顺序(传播链):")
    for name, t in sorted(residents.items(), key=lambda kv: kv[1]):
        print(f"  {t}  {name}")
    print(f"\n传播广度: {len(residents)} 名居民获知")
    print(f"传播边(推断 谁→谁):")
    for s, d, t in edges:
        print(f"  {t}  {s} → {d}")

    result = {
        "run": args.name,
        "first_known": first_known,
        "edges": [{"src": s, "dst": d, "time": t} for s, d, t in edges],
        "breadth": len(residents),
    }
    with open(f"{out_dir}/propagation.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[数据] 已保存: {out_dir}/propagation.json")
    draw(edges, first_known, f"{out_dir}/propagation.png")


if __name__ == "__main__":
    main()
