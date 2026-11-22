"""固定格式的结构化事件日志(JSONL,一行一个事件,只追加)。

每个事件的公共字段: schema_version, seq, type, sim_time, 以及该类型的必填字段。
字段表见 EVENT_FIELDS;写入时校验,多字段或缺字段都直接报错。
"""

import json
import os

from modules import utils

SCHEMA_VERSION = 1

EVENT_FIELDS = {
    # 一次运行的开头:实验参数与运行模式(natural 自然相遇 / relay 接力链)
    "run_start": ["run", "mode", "params"],
    # 一句话(逐字原文,仅供打分;智能体默认读不到)
    "utterance": ["conversation_id", "turn", "speaker", "listener", "text", "source"],
    # 说话前取回的记忆(取回环节)
    "memory_retrieve": ["conversation_id", "turn", "agent", "listener", "node_ids", "texts"],
    # 写入记忆的一条内容(存储环节);conversation_id 仅对话类记忆有值
    "memory_write": ["agent", "node_id", "node_type", "text", "conversation_id", "stored_form"],
    # 记忆整合的一次判定 ADD/UPDATE/CONFLICT/NOOP
    "consolidation": ["agent", "action", "new_node_id", "old_node_id", "reason"],
    # 反思产生的一条想法
    "reflection": ["agent", "node_id", "text", "evidence"],
    # 模型调用失败(重试耗尽)
    "llm_failure": ["agent", "caller", "model", "attempts", "error"],
    # 一次运行(或续跑的一段)的结尾:valid=false 表示本次运行作废,不得进入统计
    "run_end": ["run", "valid", "failures", "error"],
}


class EventLog:
    def __init__(self, path):
        self.path = path
        self._seq = 0
        self._failures = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path):
            events = read_events(path)
            self._seq = len(events)
            self._failures = sum(1 for e in events if e["type"] == "llm_failure")

    @property
    def failures(self):
        return self._failures

    def log(self, event_type, **fields):
        expected = EVENT_FIELDS[event_type]
        if sorted(fields) != sorted(expected):
            raise ValueError(
                "event '{}' fields {} != schema {}".format(
                    event_type, sorted(fields), sorted(expected)
                )
            )
        record = {
            "schema_version": SCHEMA_VERSION,
            "seq": self._seq,
            "type": event_type,
            "sim_time": utils.get_timer().get_date("%Y%m%d-%H:%M:%S"),
        }
        record.update(fields)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._seq += 1
        if event_type == "llm_failure":
            self._failures += 1
        return record

    def start_run(self, run, mode, params):
        return self.log("run_start", run=run, mode=mode, params=params)

    def end_run(self, run, error=None):
        """error: 让运行中止的异常文本;正常跑完为 None。"""
        return self.log(
            "run_end", run=run, valid=self._failures == 0 and error is None,
            failures=self._failures, error=error,
        )


class _NoEventLog:
    """未开启测量的入口(如采访脚本 interview.py)使用:不写任何事件。"""

    failures = 0

    def log(self, event_type, **fields):
        return None


_event_log = _NoEventLog()


def set_event_log(log):
    global _event_log
    _event_log = log
    return log


def get_event_log():
    return _event_log


def read_events(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
