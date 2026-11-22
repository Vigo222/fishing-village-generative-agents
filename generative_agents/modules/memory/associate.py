"""generative_agents.memory.associate"""

import datetime
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
from llama_index.core.indices.vector_store.retrievers import VectorIndexRetriever

from modules.storage.index import LlamaIndex
from modules import utils
from .event import Event


class Concept:
    def __init__(
        self,
        describe,
        node_id,
        node_type,
        subject,
        predicate,
        object,
        address,
        poignancy,
        create=None,
        expire=None,
        access=None,
        status="active",
        conflict_with=None,
        superseded_by=None,
    ):
        self.node_id = node_id
        self.node_type = node_type
        self.event = Event(
            subject, predicate, object, describe=describe, address=address.split(":")
        )
        self.poignancy = poignancy
        # 记忆整合标记(加性、可选、默认无害;旧节点无这些 metadata 键即走默认值)
        self.status = status
        self.conflict_with = conflict_with
        self.superseded_by = superseded_by
        self.create = utils.to_date(create) if create else utils.get_timer().get_date()
        if expire:
            self.expire = utils.to_date(expire)
        else:
            self.expire = self.create + datetime.timedelta(days=30)
        self.access = utils.to_date(access) if access else self.create

    def abstract(self):
        return {
            "{}(P.{})".format(self.node_type, self.poignancy): str(self.event),
            "duration": "{} ~ {} (access: {})".format(
                self.create.strftime("%Y%m%d-%H:%M"),
                self.expire.strftime("%Y%m%d-%H:%M"),
                self.access.strftime("%Y%m%d-%H:%M"),
            ),
        }

    def __str__(self):
        return utils.dump_dict(self.abstract())

    @property
    def describe(self):
        return self.event.get_describe()

    @classmethod
    def from_node(cls, node):
        return cls(node.text, node.id_, **node.metadata)

    @classmethod
    def from_event(cls, node_id, node_type, event, poignancy):
        return cls(
            event.get_describe(),
            node_id,
            node_type,
            event.subject,
            event.predicate,
            event.object,
            ":".join(event.address),
            poignancy,
        )


class AssociateRetriever(BaseRetriever):
    def __init__(self, config, *args, **kwargs) -> None:
        self._config = config
        self._vector_retriever = VectorIndexRetriever(*args, **kwargs)
        super().__init__()

    def _retrieve(self, query_bundle):
        """Retrieve nodes given query."""

        nodes = self._vector_retriever.retrieve(query_bundle)
        if not nodes:
            return []
        nodes = sorted(
            nodes, key=lambda n: utils.to_date(n.metadata["access"]), reverse=True
        )
        # get scores
        fac = self._config["recency_decay"]
        recency_scores = self._normalize(
            [fac**i for i in range(1, len(nodes) + 1)], self._config["recency_weight"]
        )
        relevance_scores = self._normalize(
            [n.score for n in nodes], self._config["relevance_weight"]
        )
        importance_scores = self._normalize(
            [n.metadata["poignancy"] for n in nodes], self._config["importance_weight"]
        )
        final_scores = {
            n.id_: r1 + r2 + i
            for n, r1, r2, i in zip(
                nodes, recency_scores, relevance_scores, importance_scores
            )
        }
        # re-rank nodes
        nodes = sorted(nodes, key=lambda n: final_scores[n.id_], reverse=True)
        nodes = nodes[: self._config["retrieve_max"]]
        for n in nodes:
            n.metadata["access"] = utils.get_timer().get_date("%Y%m%d-%H:%M:%S")
        return nodes

    def _normalize(self, data, factor=1, t_min=0, t_max=1):
        min_val, max_val = min(data), max(data)
        diff = max_val - min_val
        if diff == 0:
            return [(t_max - t_min) * factor / 2 for _ in data]
        return [(d - min_val) * (t_max - t_min) * factor / diff + t_min for d in data]


class Associate:
    def __init__(
        self,
        path,
        embedding,
        retention=8,
        max_memory=-1,
        max_importance=10,
        recency_decay=0.995,
        recency_weight=0.5,
        relevance_weight=3,
        importance_weight=2,
        memory=None,
        consolidate=None,
        consolidation_log=None,
        superseded=None,
        recall_chats=False,
    ):
        # 对话类记忆是否进入通用取回(实验参数 chat_recall)
        self.recall_chats = recall_chats
        self._index = LlamaIndex(embedding, path)
        self.memory = memory or {"event": [], "thought": [], "chat": []}
        self.cleanup_index()
        self.retention = retention
        self.max_memory = max_memory
        self.max_importance = max_importance
        # 记忆整合(选题1)配置与日志;默认关闭,需 config 显式开启
        self.consolidate_config = consolidate or {"enabled": False}
        self.consolidation_log = consolidation_log or []
        self.superseded = superseded or []  # UPDATE 过时记录 {old_id,new_id},审计用
        self._retrieve_config = {
            "recency_decay": recency_decay,
            "recency_weight": recency_weight,
            "relevance_weight": relevance_weight,
            "importance_weight": importance_weight,
        }

    def abstract(self):
        des = {"nodes": self._index.nodes_num}
        for t in ["event", "chat", "thought"]:
            des[t] = [self.find_concept(c).describe for c in self.memory[t]]
        return des

    def __str__(self):
        return utils.dump_dict(self.abstract())

    def cleanup_index(self):
        node_ids = self._index.cleanup()
        self.memory = {
            n_type: [n for n in nodes if n not in node_ids]
            for n_type, nodes in self.memory.items()
        }

    def add_node(
        self,
        node_type,
        event,
        poignancy,
        create=None,
        expire=None,
        filling=None,
        status="active",
        conflict_with=None,
    ):
        create = create or utils.get_timer().get_date()
        expire = expire or (create + datetime.timedelta(days=30))
        metadata = {
            "node_type": node_type,
            "subject": event.subject,
            "predicate": event.predicate,
            "object": event.object,
            "address": ":".join(event.address),
            "poignancy": poignancy,
            "create": create.strftime("%Y%m%d-%H:%M:%S"),
            "expire": expire.strftime("%Y%m%d-%H:%M:%S"),
            "access": create.strftime("%Y%m%d-%H:%M:%S"),
            "status": status,
        }
        if conflict_with:
            metadata["conflict_with"] = conflict_with
        node = self._index.add_node(event.get_describe(), metadata)
        memory = self.memory[node_type]
        memory.insert(0, node.id_)
        if len(memory) >= self.max_memory > 0:
            self._index.remove_nodes(memory[self.max_memory:])
            self.memory[node_type] = memory[: self.max_memory - 1]
        return self.to_concept(node)

    # ------------------------------------------------------------------
    # 记忆整合(选题1):候选召回 + 软过时 + 冲突标注 + 日志(均无 LLM)
    # ------------------------------------------------------------------

    def consolidate_candidates(self, event, node_type, top_k=4, threshold=0.6):
        """对新记忆做向量检索,返回近期同类、相似度≥阈值的候选(纯相似度,不经三因子重排)"""
        ids = self.memory.get(node_type, [])
        if not ids:
            return []
        filters = MetadataFilters(
            filters=[ExactMatchFilter(key="node_type", value=node_type)]
        )
        nodes = self._index.retrieve(
            event.get_describe(), similarity_top_k=top_k, filters=filters, node_ids=ids
        )
        out = []
        for n in nodes:
            score = getattr(n, "score", None)
            if score is not None and score >= threshold:
                out.append(self.to_concept(n))
        return out

    def supersede(self, old_id, new_id):
        """UPDATE:把旧节点移出检索候选列表(不动三因子公式),即不再被任何检索召回。
        注:llama-index docstore 的 node.metadata 原地修改不回写,故"过时"不靠 in-node
        标记,而靠①移出候选 ②consolidation_log 记录(含 old_id/new_id)做审计/副实验。
        旧节点实体仍留在 docstore(可经 node_id 回查),但不再进入任何候选集合。"""
        self.superseded.append({"old_id": old_id, "new_id": new_id})
        for ids in self.memory.values():
            if old_id in ids:
                ids.remove(old_id)

    def log_consolidation(self, action, new_concept, old_concept=None, reason=""):
        self.consolidation_log.append({
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M:%S"),
            "action": action,
            "new": new_concept.describe if new_concept else "",
            "new_id": new_concept.node_id if new_concept else "",
            "old": old_concept.describe if old_concept else "",
            "old_id": old_concept.node_id if old_concept else "",
            "reason": reason,
        })

    def to_concept(self, node):
        return Concept.from_node(node)

    def find_concept(self, node_id):
        return self.to_concept(self._index.find_node(node_id))

    def _retrieve_nodes(self, node_type, text=None):
        if text:
            filters = MetadataFilters(
                filters=[ExactMatchFilter(key="node_type", value=node_type)]
            )
            nodes = self._index.retrieve(
                text, filters=filters, node_ids=self.memory[node_type]
            )
        else:
            nodes = [self._index.find_node(n) for n in self.memory[node_type]]
        return [self.to_concept(n) for n in nodes[: self.retention]]

    def retrieve_events(self, text=None):
        return self._retrieve_nodes("event", text)

    def retrieve_thoughts(self, text=None):
        return self._retrieve_nodes("thought", text)

    def retrieve_chats(self, name=None):
        text = ("对话 " + name) if name else None
        return self._retrieve_nodes("chat", text)

    def retrieve_focus(self, focus, retrieve_max=30, reduce_all=True):
        def _create_retriever(*args, **kwargs):
            self._retrieve_config["retrieve_max"] = retrieve_max
            return AssociateRetriever(self._retrieve_config, *args, **kwargs)

        retrieved = {}
        node_ids = self.memory["event"] + self.memory["thought"]
        if self.recall_chats:
            node_ids = node_ids + self.memory["chat"]
        for text in focus:
            nodes = self._index.retrieve(
                text,
                similarity_top_k=len(node_ids),
                node_ids=node_ids,
                retriever_creator=_create_retriever,
            )
            if reduce_all:
                retrieved.update({n.id_: n for n in nodes})
            else:
                retrieved[text] = nodes
        if reduce_all:
            return [self.to_concept(v) for v in retrieved.values()]
        return {
            text: [self.to_concept(n) for n in nodes]
            for text, nodes, in retrieved.items()
        }

    def get_relation(self, node):
        return {
            "node": node,
            "events": self.retrieve_events(node.describe),
            "thoughts": self.retrieve_thoughts(node.describe),
        }

    def to_dict(self):
        self._index.save()
        return {
            "memory": self.memory,
            "consolidation_log": self.consolidation_log,
            "superseded": self.superseded,
        }

    @property
    def index(self):
        return self._index
