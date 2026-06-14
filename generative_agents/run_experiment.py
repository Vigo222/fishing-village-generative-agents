"""主实验跑批驱动:A/B(反思开/关)× 5 seed,带单轮崩溃隔离 + 同 seed 补跑。

设计(对应实验设计文档 + 2026-06-13 裁决):
- 配对:同 seed 给两臂相同随机初始态;两臂因反思分叉=被测信号;5 轮聚合消化 LLM 噪声。
- temp=0:压低 LLM 随机(实验求可复现/可归因;演示另用 0.5)。
- 崩溃隔离:每轮以子进程跑 start.py,一轮挂不拖垮整批;记录崩在哪个 seed/哪一步。
- 幂等补跑:已完成(达 target_step)跳过;部分完成用 --resume 续(resume 位置已修,不漂移);
  未开始则全新跑。次日重跑本脚本即自动补齐未完成轮次。
用法:python run_experiment.py            # 跑全部未完成轮次
      python run_experiment.py --dry-run  # 只看计划与调用量估算,不实际跑
"""
import os
import sys
import json
import glob
import argparse
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ARMS = ["off", "on"]          # 反思关组先跑(更快),再跑反思开组
SEEDS = [1, 2, 3, 4, 5]
TARGET_STEP = 12
STRIDE = 30
INJECT = "用户分身@2"
TEMP = 0
CKPT = "results/checkpoints"
MANIFEST = "results/experiment_manifest.json"
N_AGENTS = 5 + 1              # 5 居民 + 注入分身(注入后)


def last_step(name):
    files = glob.glob(f"{CKPT}/{name}/simulate-*.json")
    steps = []
    for f in files:
        try:
            steps.append(json.load(open(f, encoding="utf-8"))["step"])
        except Exception:
            pass
    return max(steps) if steps else 0


def estimate_calls(arm):
    # 粗估:每 agent 每步 感知/计划/动作 ~6-10 次;反思开再 +~5 次;对话另计。仅供知情。
    per = 12 if arm == "on" else 7
    return N_AGENTS * TARGET_STEP * per


def run_one(arm, seed, dry):
    name = f"exp-{arm}-s{seed}"
    done = last_step(name)
    if done >= TARGET_STEP:
        return {"arm": arm, "seed": seed, "name": name, "status": "skip-done", "last_step": done}
    base = [sys.executable, "start.py", "--name", name, "--reflect", arm,
            "--temp", str(TEMP), "--stride", str(STRIDE), "--verbose", "warn", "--log", "run.log"]
    if done == 0:
        cmd = base + ["--inject", INJECT, "--seed", str(seed), "--step", str(TARGET_STEP)]
        mode = "fresh"
    else:
        cmd = base + ["--resume", "--step", str(TARGET_STEP - done)]  # 补跑剩余步(不再注入)
        mode = f"resume-from-{done}"
    est = estimate_calls(arm)
    print(f"\n>>> [{arm} seed{seed}] {mode};预估调用量 ~{est} 次;{datetime.now():%H:%M:%S}")
    if dry:
        return {"arm": arm, "seed": seed, "name": name, "status": "dry", "mode": mode, "est_calls": est}
    rc = subprocess.run(cmd).returncode
    now = last_step(name)
    status = "done" if now >= TARGET_STEP else "FAILED"
    if status == "FAILED":
        print(f"!!! [{arm} seed{seed}] 崩溃/未完成:止步 step {now}/{TARGET_STEP},returncode={rc}。"
              f"已隔离,继续下一轮;次日重跑本脚本将从 step {now} 用 resume 补跑。")
    return {"arm": arm, "seed": seed, "name": name, "status": status,
            "last_step": now, "returncode": rc, "mode": mode, "est_calls": est}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    results = []
    for arm in ARMS:
        for seed in SEEDS:
            results.append(run_one(arm, seed, args.dry_run))

    os.makedirs(CKPT, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"time": datetime.now().isoformat(), "runs": results}, f,
                  ensure_ascii=False, indent=2)

    print("\n==== 跑批汇总 ====")
    for r in results:
        print(f"  {r['name']}: {r['status']}" +
              (f" (step {r.get('last_step')})" if "last_step" in r else ""))
    failed = [r for r in results if r["status"] == "FAILED"]
    print(f"\n完成 {sum(r['status']=='done' for r in results)} / 跳过 {sum(r['status']=='skip-done' for r in results)}"
          f" / 失败 {len(failed)}。manifest: {MANIFEST}")
    if failed:
        print("失败轮次(次日重跑本脚本自动 resume 补跑):", [r["name"] for r in failed])
    total_est = sum(r.get("est_calls", 0) for r in results if r["status"] in ("fresh", "done", "FAILED", "dry"))
    print(f"本批预估总调用量(粗) ~{sum(estimate_calls(r['arm']) for r in results)} 次(实际见各 run.log 的 llm summary)")


if __name__ == "__main__":
    main()
