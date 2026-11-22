class LLMCallError(RuntimeError):
    """模型调用重试耗尽。不返回任何替代值,由上层记录并把本次运行标为无效。"""

    def __init__(self, caller, model, attempts, last_error):
        self.caller = caller
        self.model = model
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            "LLM call '{}' ({}) failed after {} attempts: {}".format(
                caller, model, attempts, last_error
            )
        )
