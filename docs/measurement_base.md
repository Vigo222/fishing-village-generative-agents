# 测量底座(与场景无关的基础层)

目的:测一句话在多智能体系统里**在哪一环丢了信息**——听到、存进记忆、取回、转述。
渔村/校园只是测量场地,底座不依赖任何具体场景。

## 1. 结构化事件日志 `events.jsonl`

每次运行在结果目录下写一个 `events.jsonl`(一行一个事件,只追加,字段固定,写入时校验)。
**打分只读这个文件**,不读仿真内部状态,也不做关键词匹配。

| 事件 `type` | 含义 | 主要字段 |
|---|---|---|
| `run_start` | 一次运行开始 | `run`, `mode`(`natural` 自然相遇 / `relay` 接力链), `params`(实验参数) |
| `utterance` | 说出的一句话(**逐字原文**) | `conversation_id`, `turn`, `speaker`, `listener`, `text`, `source`(`agent` 智能体自己说的 / `scripted` 实验给定的源消息) |
| `memory_write` | 写入记忆的一条内容 | `agent`, `node_id`, `node_type`, `text`, `conversation_id`, `stored_form`(`summary` 摘要 / `verbatim` 原文) |
| `memory_retrieve` | 说话前取回的记忆 | `agent`, `listener`, `node_ids`, `texts` |
| `consolidation` | 记忆整合的一次判定 | `agent`, `action`(ADD/UPDATE/CONFLICT/NOOP), `new_node_id`, `old_node_id`, `reason` |
| `reflection` | 反思产生的一条想法 | `agent`, `node_id`, `text`, `evidence` |
| `llm_failure` | 模型调用失败(重试耗尽) | `agent`, `caller`, `model`, `attempts`, `error` |
| `run_end` | 运行结束 | `valid`(false = 本次运行作废), `failures`, `error` |

所有事件都带 `schema_version`、`seq`(序号)、`sim_time`(仿真时间)。字段表在
`modules/measure/eventlog.py` 的 `EVENT_FIELDS`。

逐字原文只写进日志。默认条件下智能体事后能读到的只有自己存下的摘要(反思时读的也是摘要)。

## 2. 实验参数(记忆层开关)

写在一个 JSON 里(默认值在 `data/config.json` 的 `agent.experiment`,示例见
`data/experiments/example/params.json`),用 `--experiment 文件` 传入:

| 参数 | 取值 | 含义 |
|---|---|---|
| `summary_mode` | `summary` / `verbatim` | 对话存成摘要,还是存逐字原文(智能体可读原文的条件) |
| `summary_max_chars` | 正整数 | 摘要字数上限(原来写死的 100) |
| `consolidate` | true / false | 记忆整合开关 |
| `reflect` | true / false | 反思开关 |
| `chat_recall` | `partner_only` / `all` | 对话记忆只在再遇到同一个人时取回(原行为),还是进入通用取回 |

参数会原样记在 `run_start` 事件里。具体要跑哪些组合(因子表)未定,这里不限制。

## 3. 两种运行模式

- 自然相遇: `python start.py --name xxx --experiment params.json ...`,日志在 `results/checkpoints/xxx/events.jsonl`。
  消息用 `--message seed.json` 播种:文件只有 `step`(第几步)、`source`(场外消息源)、`listener`(哪位居民)、`message`(原文)四项,
  多出任何字段直接报错;到那一步时这位居民"听到"原文,走的是接力链第一跳同一段代码。
- 接力链(受控传话,源消息 → A → B → C): `python relay.py --name xxx --spec relay.json --experiment params.json`,
  日志在 `results/relay/xxx/events.jsonl`。不需要地图和日程;存储、整合、反思与自然相遇共用
  `modules/memory_ops.py` 同一份代码。接力链里只要开了反思,每次听完就反思一次(自然相遇里仍按重要性累计触发)。

## 4. 事实槽与打分

事实槽(答案表,如 `data/experiments/example/facts.json`)只交给 `score.py`:

```
python score.py --events results/relay/xxx/events.jsonl --facts facts.json --out scores.json
```

`score.py` 对日志里每条"说出的话 / 写入的记忆 / 取回的记忆 / 反思"逐条事实让评分模型判断是否保留,
输出逐条判定和各环节保留率。评分模型在 `data/config.json` 的 `scoring.llm` 里配置,和被测模型相同时 `score.py` 拒绝运行。
仿真和接力链的输入里没有事实槽(接力链说明文件多出任何字段会直接报错),
所以事实槽不可能进入提示词或记忆。

## 5. 失败处理

模型调用重试耗尽时不再返回"嗯"、False、默认日程之类的替代值:抛出 `LLMCallError`,
写一条 `llm_failure` 事件,运行中止并在 `run_end` 里标 `valid: false`。`score.py` 拒绝给无效或没跑完的运行打分。
模型输出不合格(空、不在候选列表里)同样先重试、耗尽即失败。向量检索出错也不再吞成"空结果"。

## 6. 测试

```
cd generative_agents && python -m pytest tests
```

不联网(模型与向量模型都是假的),覆盖日志格式、各开关、接力链、失败作废、打分流程。
