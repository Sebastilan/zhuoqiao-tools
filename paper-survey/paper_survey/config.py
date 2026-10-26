"""配置读取:环境变量优先,其次包目录或当前目录的 .env;只取值,不打印。"""
import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
_loaded = {}


def _load_env():
    if _loaded:
        return _loaded
    _loaded["_"] = ""
    for f in (Path.cwd() / ".env", _PKG / ".env"):
        if not f.is_file():
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            _loaded.setdefault(k, v)
    return _loaded


def get(name, default=""):
    v = os.environ.get(name)
    if v is None:
        v = _load_env().get(name, "")
    return v if v != "" else default


def get_list(name):
    return [x.strip() for x in get(name).split(",") if x.strip()]


def get_int(name, default):
    try:
        return int(get(name, str(default)))
    except ValueError:
        return default


def secret_values():
    """所有密钥类配置的值(供写页面前自查不泄密);只返回 ≥8 字符的。"""
    names = ("LLM_API_KEY", "SERPER_API_KEY", "OPENALEX_API_KEY", "S2_API_KEY")
    out = []
    for n in names:
        out += [x for x in get_list(n) if len(x) >= 8]
    return out
