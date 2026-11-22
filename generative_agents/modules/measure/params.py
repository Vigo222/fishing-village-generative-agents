"""记忆层实验参数:全部由配置/命令行给出,代码里不写死。"""

from dataclasses import dataclass, asdict

SUMMARY_MODES = ("summary", "verbatim")
CHAT_RECALL = ("partner_only", "all")


@dataclass(frozen=True)
class ExperimentParams:
    # summary: 对话存成不超过 summary_max_chars 字的摘要;verbatim: 存逐字原文(智能体可读原文)
    summary_mode: str = "summary"
    summary_max_chars: int = 100
    # 记忆整合(新记忆与旧记忆去重/更新/标冲突)开关
    consolidate: bool = True
    # 反思(把近期记忆提炼成想法)开关
    reflect: bool = True
    # 对话类记忆何时能被取回:partner_only=只在再次遇到同一个人时(原代码行为);
    # all=和事件、想法一样进入通用取回
    chat_recall: str = "partner_only"

    def __post_init__(self):
        if self.summary_mode not in SUMMARY_MODES:
            raise ValueError("summary_mode must be one of {}".format(SUMMARY_MODES))
        if self.chat_recall not in CHAT_RECALL:
            raise ValueError("chat_recall must be one of {}".format(CHAT_RECALL))
        if not isinstance(self.summary_max_chars, int) or self.summary_max_chars <= 0:
            raise ValueError("summary_max_chars must be a positive integer")
        for key in ("consolidate", "reflect"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError("{} must be true/false".format(key))

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def to_dict(self):
        return asdict(self)

    def apply_to_agent_config(self, agent_config):
        """把参数写进智能体配置(agent_base),这是参数进入仿真的唯一入口。"""
        agent_config["experiment"] = self.to_dict()
        agent_config["think"]["reflect"] = self.reflect
        agent_config["associate"]["consolidate"]["enabled"] = self.consolidate
        agent_config["associate"]["recall_chats"] = self.chat_recall == "all"
        return agent_config
