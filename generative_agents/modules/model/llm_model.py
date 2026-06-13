"""generative_agents.model.llm_model"""

import os
import time
import re
import requests
from magentic import prompt


def resolve_env(value):
    """配置值形如 ${VAR} 时从环境变量解析(API key 不入 git/存档)"""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


class LLMModel:
    def __init__(self, config):
        self._api_key = resolve_env(config["api_key"])
        self._base_url = resolve_env(config["base_url"])
        self._model = config["model"]
        self._summary = {"total": [0, 0, 0]}

        self._handle = self.setup(config)
        self._enabled = True

    def setup(self, config):
        raise NotImplementedError(
            "setup is not support for " + str(self.__class__)
        )

    def completion(
        self,
        prompt,
        retry=10,
        callback=None,
        failsafe=None,
        return_type=None,
        caller="llm_normal",
        **kwargs
    ):
        response = None
        self._summary.setdefault(caller, [0, 0, 0])
        for _ in range(retry):
            try:
                output = self._completion(prompt, return_type, **kwargs)
                self._summary["total"][0] += 1
                self._summary[caller][0] += 1
                if callback:
                    response = callback(output)
                else:
                    response = output
            except Exception as e:
                print(f"LLMModel.completion() caused an error: {e}")
                time.sleep(5)
                response = None
                continue
            if response is not None:
                break
        pos = 2 if response is None else 1
        self._summary["total"][pos] += 1
        self._summary[caller][pos] += 1
        return response or failsafe

    def _completion(self, prompt, return_type, **kwargs):
        raise NotImplementedError(
            "_completion is not support for " + str(self.__class__)
        )

    def is_available(self):
        return self._enabled  # and self._summary["total"][2] <= 10

    def get_summary(self):
        des = {}
        for k, v in self._summary.items():
            des[k] = "S:{},F:{}/R:{}".format(v[1], v[2], v[0])
        return {"model": self._model, "summary": des}

    def disable(self):
        self._enabled = False


class OpenAILLMModel(LLMModel):
    def setup(self, config):
        from magentic import OpenaiChatModel

        return OpenaiChatModel(self._model, api_key=self._api_key, base_url=self._base_url)

    def _completion(self, _prompt, return_type, temperature=0.5):
        @prompt(
            "{_prompt}",
            model=self._handle
        )
        def response(_prompt: str) -> return_type: ...
        output = response(_prompt).res
        return output


class OllamaLLMModel(LLMModel):
    def setup(self, config):
        return None

    def ollama_chat(self, messages, temperature, response_format=None):
        headers = {
            "Content-Type": "application/json"
        }
        # 经 OpenAI 兼容中转(如云雾)时需带 Bearer 认证;本地 Ollama 无 key 时自动跳过
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        params = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            params["response_format"] = response_format

        response = requests.post(
            url=f"{self._base_url}/chat/completions",
            headers=headers,
            json=params,
            stream=False,
            timeout=300
        )
        return response.json()

    def _completion(self, prompt, return_type, temperature=0.5):
        import json
        
        # Generate JSON schema from the Pydantic model for structured output
        response_format = None
        if return_type is not None:
            try:
                schema = return_type.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": return_type.__name__,
                        "strict": True,
                        "schema": schema
                    }
                }
            except Exception:
                pass
        
        messages = [{"role": "user", "content": prompt}]
        response = self.ollama_chat(messages=messages, temperature=temperature, response_format=response_format)
        
        if response and len(response.get("choices", [])) > 0:
            ret = response["choices"][0]["message"]["content"]
            # 从输出结果中过滤掉<think>标签内的文字，以免影响后续逻辑
            ret = re.sub(r"<think>.*</think>", "", ret, flags=re.DOTALL)
            
            # Parse and validate the response using the Pydantic model
            if return_type is not None:
                try:
                    # Try to parse as JSON and validate with Pydantic
                    parsed = json.loads(ret)
                    validated = return_type.model_validate(parsed)
                    return validated.res
                except json.JSONDecodeError:
                    # If JSON parsing fails, try to extract JSON from the text
                    json_match = re.search(r'\{.*\}', ret, re.DOTALL)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group())
                            validated = return_type.model_validate(parsed)
                            return validated.res
                        except (json.JSONDecodeError, Exception):
                            pass
                    # If all parsing fails, return the raw text
                    return ret
                except Exception as e:
                    print(f"OllamaLLMModel: Failed to validate response: {e}")
                    return ret
            return ret
        return ""


class OpenAIJSONModel(LLMModel):
    """OpenAI 兼容接口的纯文本+宽松JSON解析路径(快速档/国产模型自实现)。

    用于 magentic 工具调用不兼容、且中转上游不稳定支持 response_format 的模型
    (实测 deepseek-v4-flash:magentic 强制工具调用 2/6,response_format 随机报
    'does not support';纯文本+宽松解析 8/8)。不发 tools、不发 response_format,
    把期望的 {"res": ...} 形状以自然语言注入提示词,再从返回文本中宽松提取并用
    Pydantic 校验。这正是阶段0裁决预案"按 JSON 方式自实现"的落地形态。
    """

    def setup(self, config):
        return None

    @staticmethod
    def _shape_hint(schema):
        t = schema.get("type")
        if t == "integer":
            return "整数"
        if t == "number":
            return "数字"
        if t == "boolean":
            return "true 或 false"
        if t == "string":
            return '"字符串"'
        if t == "array":
            if "prefixItems" in schema:  # 定长元组 Tuple[...]
                return "[" + ", ".join(
                    OpenAIJSONModel._shape_hint(it) for it in schema["prefixItems"]
                ) + "]"
            return "[" + OpenAIJSONModel._shape_hint(schema.get("items", {})) + ", ...]"
        if t == "object":
            return "{键: 值, ...}"
        return "值"

    def _format_hint(self, return_type):
        try:
            schema = return_type.model_json_schema()
            res_schema = schema.get("properties", {}).get("res", {})
            shape = self._shape_hint(res_schema)
        except Exception:
            shape = "值"
        return (
            '\n\n请严格只返回一个JSON对象,不要包含任何额外的解释、前后缀或代码块标记,'
            '格式为: {{"res": {}}}'.format(shape)
        )

    def chat(self, messages, temperature):
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        params = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        response = requests.post(
            url=f"{self._base_url}/chat/completions",
            headers=headers,
            json=params,
            stream=False,
            timeout=300,
        )
        if response.status_code != 200:
            raise RuntimeError(
                "HTTP {}: {}".format(response.status_code, response.text[:200])
            )
        return response.json()

    def _completion(self, prompt, return_type, temperature=0.5):
        import json

        full_prompt = prompt + (self._format_hint(return_type) if return_type else "")
        response = self.chat([{"role": "user", "content": full_prompt}], temperature)
        if not response.get("choices"):
            raise RuntimeError("empty choices: {}".format(str(response)[:200]))

        ret = response["choices"][0]["message"].get("content") or ""
        # 去除推理标签与代码块围栏(deepseek-v4-flash 等推理模型)
        ret = re.sub(r"<think>.*?</think>", "", ret, flags=re.DOTALL)
        ret = re.sub(r"```(?:json)?|```", "", ret).strip()

        def _validate(text):
            parsed = json.loads(text)
            return return_type.model_validate(parsed).res

        if return_type is None:
            return ret
        try:
            return _validate(ret)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", ret, re.DOTALL)
            if match:
                return _validate(match.group())  # 仍失败则抛出,由外层 retry/ failsafe 兜底
            raise


def create_llm_model(llm_config):
    """Create llm model"""

    provider = llm_config["provider"]
    if provider == "ollama":
        return OllamaLLMModel(llm_config)
    elif provider == "openai":
        return OpenAILLMModel(llm_config)
    elif provider == "openai_json":
        return OpenAIJSONModel(llm_config)
    else:
        raise NotImplementedError(
            "llm provider {} is not supported".format(provider)
        )
