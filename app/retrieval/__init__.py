def hybrid_search(*args, **kwargs):
    from .hybrid import hybrid_search as _hybrid_search

    return _hybrid_search(*args, **kwargs)


def get_store():
    from .hybrid import get_store as _get_store

    return _get_store()


def MemoryHybridStore(*args, **kwargs):
    from .hybrid import MemoryHybridStore as _MemoryHybridStore

    return _MemoryHybridStore(*args, **kwargs)


def Document(*args, **kwargs):
    from .hybrid import Document as _Document

    return _Document(*args, **kwargs)


__all__ = ["hybrid_search", "get_store", "MemoryHybridStore", "Document"]
