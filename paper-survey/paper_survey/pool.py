"""轮转 key 池。线程安全。额度耗尽或鉴权失败的 key 由调用方 kill,之后不再轮到它。"""
import threading


class KeyPool:
    def __init__(self, keys):
        self._keys = list(keys)
        self._i = 0
        self._dead = set()
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            alive = [k for k in self._keys if k not in self._dead]
            if not alive:
                return None
            key = alive[self._i % len(alive)]
            self._i += 1
            return key

    def kill(self, key):
        with self._lock:
            self._dead.add(key)

    def alive(self):
        with self._lock:
            return len(self._keys) - len(self._dead)
