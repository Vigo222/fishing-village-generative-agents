"""记忆层的公共操作:写入记忆、记忆整合、对话反思、模型调用。

自然相遇(modules/agent.py 的 Agent)和接力链(relay.py 的 RelayAgent)共用这一份,
保证两种模式下"听到的话怎样变成记忆"走的是同一段代码。
使用者需提供: name, scratch, associate, logger, chats, params, conversation_id,
_route_llm(func_hint), current_address()。
"""

from modules import memory, utils
from modules.measure import get_event_log, LLMCallError


class MemoryOps:
    def completion(self, func_hint, *args, **kwargs):
        assert hasattr(
            self.scratch, "prompt_" + func_hint
        ), "Can not find func prompt_{} from scratch".format(func_hint)
        func = getattr(self.scratch, "prompt_" + func_hint)
        res = func(*args, **kwargs)._asdict()
        llm = self._route_llm(func_hint)
        title = "{}.{}".format(self.name, func_hint)
        self.logger.info("{} -> {} ({})".format(self.name, func_hint, llm._model))
        try:
            output = llm.completion(caller=func_hint, **res)
        except LLMCallError as e:
            # 不用任何替代值:记一条失败事件,异常继续上抛,由入口把本次运行标为无效
            get_event_log().log(
                "llm_failure", agent=self.name, caller=func_hint, model=e.model,
                attempts=e.attempts, error=str(e.last_error),
            )
            raise
        msg = {"<PROMPT>": "\n" + res["prompt"] + "\n", "response": output}
        self.logger.debug(utils.block_msg(title, msg))
        return output

    def _chat_memory_text(self, chats):
        """一段对话存进记忆时的文本:摘要(长度可配)或逐字原文。"""
        if self.params.summary_mode == "verbatim":
            return "\n".join("{}: {}".format(n, t) for n, t in chats)
        return self.completion("summarize_chats", chats, self.params.summary_max_chars)

    def _readable_chats(self, chats, stored_text, other_name):
        """智能体事后(反思时)能读到的对话内容:默认只有存下来的摘要,不是原文。"""
        if self.params.summary_mode == "verbatim":
            return list(chats)
        return [(other_name, stored_text)]

    def _add_thought(self, thought, evidence=None):
        event = self.make_event(self.name, thought, self.current_address())
        node = self._add_concept("thought", event, filling=evidence)
        get_event_log().log(
            "reflection", agent=self.name, node_id=node.node_id,
            text=node.describe, evidence=list(evidence or []),
        )
        return node

    def _reflect_chats(self):
        """反思的对话部分:把可读的对话内容提炼成两条想法,然后清空待反思对话。"""
        if self.chats:
            recorded, evidence = set(), []
            for name, _ in self.chats:
                if name == self.name or name in recorded:
                    continue
                recorded.add(name)
                res = self.associate.retrieve_chats(name)
                if res and len(res) > 0:
                    node = res[-1]
                    evidence.append(node.node_id)
            thought = self.completion("reflect_chat_planing", self.chats)
            self._add_thought(f"对于 {self.name} 的计划：{thought}", evidence)
            thought = self.completion("reflect_chat_memory", self.chats)
            self._add_thought(f"{self.name} {thought}", evidence)
        self.chats = []

    def _log_memory_write(self, e_type, node):
        is_chat = e_type == "chat"
        get_event_log().log(
            "memory_write", agent=self.name, node_id=node.node_id, node_type=e_type,
            text=node.describe,
            conversation_id=self.conversation_id if is_chat else None,
            stored_form=self.params.summary_mode if is_chat else None,
        )

    def _log_consolidation(self, action, new, old, reason):
        self.associate.log_consolidation(action, new, old, reason)
        get_event_log().log(
            "consolidation", agent=self.name, action=action,
            new_node_id=new.node_id if new else None,
            old_node_id=old.node_id if old else None, reason=reason,
        )

    # create action && object events
    def make_event(self, subject, describe, address):
        # emoji = self.completion("describe_emoji", describe)
        # return self.completion(
        #     "describe_event", subject, subject + describe, address, emoji
        # )

        e_describe = describe.replace("(", "").replace(")", "").replace("<", "").replace(">", "")
        if e_describe.startswith(subject + "此时"):
            e_describe = e_describe[len(subject + "此时"):]
        if e_describe.startswith(subject):
            e_describe = e_describe[len(subject):]
        event = memory.Event(
            subject, "此时", e_describe, describe=describe, address=address
        )
        return event

    def _add_concept(
        self,
        e_type,
        event,
        create=None,
        expire=None,
        filling=None,
    ):
        if event.fit(None, "is", "idle"):
            poignancy = 1
        elif event.fit(None, "此时", "空闲"):
            poignancy = 1
        elif e_type == "chat":
            poignancy = self.completion("poignancy_chat", event)
        else:
            poignancy = self.completion("poignancy_event", event)
        self.logger.debug("{} add associate {}".format(self.name, event))

        # 记忆整合(选题1):仅对配置范围内的类型(event/chat,绝不碰 thought)
        cfg = self.associate.consolidate_config
        # 物件状态事件(subject 即该 tile 上的对象,如"烹饪区/烧水炉/渔船泊位")是环境噪声,
        # 不参与整合——只整合"人物/实体"相关记忆,避免物件状态churn与误判冲突
        is_object_event = (
            e_type == "event" and event.address and event.subject == event.address[-1]
        )
        if cfg.get("enabled") and e_type in cfg.get("scope", ["event"]) and not is_object_event:
            consolidated = self._consolidate_memory(e_type, event, poignancy, create, expire, filling)
            if consolidated is not None:
                return consolidated

        node = self.associate.add_node(
            e_type,
            event,
            poignancy,
            create=create,
            expire=expire,
            filling=filling,
        )
        self._log_memory_write(e_type, node)
        return node

    def _consolidate_memory(self, e_type, event, poignancy, create, expire, filling):
        """整合判定与执行。返回 Concept(已处理)或 None(无候选→交回常规 ADD)"""
        cfg = self.associate.consolidate_config
        candidates = self.associate.consolidate_candidates(
            event, e_type,
            top_k=cfg.get("max_candidates", 4),
            threshold=cfg.get("sim_threshold", 0.6),
        )
        if not candidates:
            return None  # 无相似候选,不调 LLM,走常规 ADD(控成本)

        verdict = self.completion("memory_consolidate", event, candidates)
        action = str(verdict[0]).strip().upper()
        try:
            target = int(verdict[1])
        except (ValueError, IndexError):
            target = -1
        reason = verdict[2] if len(verdict) > 2 else ""
        old = candidates[target] if 0 <= target < len(candidates) else None

        if action == "NOOP" and old is not None:
            self._log_consolidation("NOOP", None, old, reason)
            self.logger.info("{} 记忆整合 NOOP(去重): {}".format(self.name, event.get_describe()))
            return old  # 去重:不新增,返回命中的旧记忆

        node = self.associate.add_node(
            e_type, event, poignancy, create=create, expire=expire, filling=filling,
            conflict_with=old.node_id if (action == "CONFLICT" and old) else None,
        )
        self._log_memory_write(e_type, node)
        if action == "UPDATE" and old is not None:
            # event:旧记忆过时、移出候选;chat:不 supersede(保护对话系统读的
            # retrieve_chats / 60分钟搭话冷却),两条并存,仅靠 consolidation_log 记录更新
            if e_type == "event":
                self.associate.supersede(old.node_id, node.node_id)
            self._log_consolidation("UPDATE", node, old, reason)
            self.logger.info("{} 记忆整合 UPDATE({}): '{}' → '{}'".format(
                self.name, e_type, old.describe, node.describe))
        elif action == "CONFLICT" and old is not None:
            # 新节点已在 add_node 时写入 conflict_with=old.node_id(创建即持久);
            # 反向标记靠 consolidation_log 记录冲突对(docstore 原地改 metadata 不可靠)
            self._log_consolidation("CONFLICT", node, old, reason)
            self.logger.info("{} 记忆整合 CONFLICT: '{}' ⚔ '{}'".format(
                self.name, old.describe, node.describe))
        else:
            self._log_consolidation("ADD", node, None, reason)
        return node

