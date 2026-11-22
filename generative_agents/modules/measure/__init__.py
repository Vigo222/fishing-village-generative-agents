"""测量底座(与场景无关):结构化事件日志、实验参数、失败记录。

打分代码(scoring/)只读这里产生的事件日志,不读仿真内部状态。
"""

from .eventlog import EventLog, get_event_log, set_event_log, read_events, SCHEMA_VERSION
from .params import ExperimentParams
from .errors import LLMCallError
