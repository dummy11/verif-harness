"""Short-lived, per-thread Store operation reuse; never an authority or a TTL cache."""

from functools import wraps
import sqlite3


class StoreConnection(sqlite3.Connection):
    """SQLite's context manager commits but normally leaves the connection open."""

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def store_operation(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.operation():
            return method(self, *args, **kwargs)
    return run
