# accounts/utils.py  (NOUVEAU FICHIER)
from contextlib import contextmanager
from threading import local

_local = local()

def _get_flag() -> bool:
    return bool(getattr(_local, "skip_client_user_autocreate", False))

@contextmanager
def skip_client_user_autocreate():
    prev = _get_flag()
    _local.skip_client_user_autocreate = True
    try:
        yield
    finally:
        _local.skip_client_user_autocreate = prev

def should_skip_client_user_autocreate() -> bool:
    return _get_flag()
