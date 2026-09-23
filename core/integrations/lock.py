"""Bloqueio em processo para impedir sincronizações concorrentes."""
import threading
from contextlib import contextmanager


class SyncAlreadyRunning(RuntimeError):
    pass


class SyncLockRegistry:
    _guard = threading.Lock()
    _active = set()

    @classmethod
    @contextmanager
    def acquire(cls, key: str):
        with cls._guard:
            if key in cls._active:
                raise SyncAlreadyRunning("Já existe uma sincronização em andamento para esta instalação.")
            cls._active.add(key)
        try:
            yield
        finally:
            with cls._guard:
                cls._active.discard(key)

    @classmethod
    def is_active(cls) -> bool:
        with cls._guard:
            return bool(cls._active)
