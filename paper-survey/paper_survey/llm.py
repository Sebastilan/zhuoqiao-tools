"""大模型调用:任意 OpenAI 兼容 /chat/completions 接口。

LLM_BASE_URL 写到 /v1 为止(如 https://api.openai.com/v1),LLM_MODEL 选一个便宜快的模型:
评分是一篇一次调用,一次调研约 300–600 次。LLM_EXTRA_BODY 可给 JSON 透传额外字段
(如 {"reasoning_effort": "none"} 关掉思考)。错误信息只含状态码,不含地址和 key。
"""
import json
import threading
import time
import urllib.error
import urllib.request

import config

_cfg = {}
_sem = [None]
_lock = threading.Lock()


class LLMError(Exception):
    pass


def _conf():
    with _lock:
        if not _cfg:
            base = config.get("LLM_BASE_URL").rstrip("/")
            key = config.get("LLM_API_KEY")
            model = config.get("LLM_MODEL")
            if not (base and model):
                raise LLMError("缺配置:LLM_BASE_URL / LLM_MODEL(见 .env.example)")
            extra = config.get("LLM_EXTRA_BODY")
            _cfg.update(url=base + "/chat/completions", key=key, model=model,
                        extra=json.loads(extra) if extra else {})
            _sem[0] = threading.BoundedSemaphore(concurrency())
    return _cfg


def concurrency():
    """并发上限:按你的接口限流调;默认 16。"""
    return max(1, config.get_int("LLM_CONCURRENCY", 16))


def body_for(messages, max_tokens, model, extra):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    body.update(extra or {})
    return body


def chat(messages, max_tokens=1500, timeout=120, retries=2):
    c = _conf()
    data = json.dumps(body_for(messages, max_tokens, c["model"], c["extra"])).encode()
    headers = {"Content-Type": "application/json"}
    if c["key"]:
        headers["Authorization"] = "Bearer " + c["key"]
    last = "无"
    for attempt in range(retries + 1):
        req = urllib.request.Request(c["url"], data=data, method="POST", headers=headers)
        try:
            with _sem[0], urllib.request.urlopen(req, timeout=timeout) as r:
                js = json.loads(r.read())
            return (js["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (400, 401, 403, 404):
                break                      # 配置错,重试无用
        except Exception as e:
            last = type(e).__name__
        time.sleep(1.0 + attempt * 2)
    raise LLMError(f"llm 失败: {last}")
