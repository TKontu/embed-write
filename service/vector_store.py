"""CA-01/CA-02 append-only LMDB vectors; unwired by design until SV-02.

Each put uses one write transaction; calls allocate O(dims) vector memory.
Keys must fit LMDB's key-size limit. Eviction is deferred.
"""
from collections.abc import Iterator
from dataclasses import dataclass
import json
import os
import struct

import lmdb

from service.vectors import Level, LevelVector


def _keyspace_prefix(model_id: str, model_version: str) -> bytes:
    if not isinstance(model_id, str) or not isinstance(model_version, str):
        raise TypeError('model identity must be strings')
    # ASCII JSON preserves all Python strings, including Unicode and separators.
    identity = json.dumps([model_id, model_version], ensure_ascii=True,
                          separators=(',', ':')).encode('ascii')
    return struct.pack('>I', len(identity)) + identity


@dataclass(frozen=True)
class VectorKey:
    model_id: str
    model_version: str
    level: Level
    content_hash: str
    dims: int

    def __post_init__(self):
        if not all(isinstance(value, str) for value in
                   (self.model_id, self.model_version, self.content_hash)):
            raise TypeError('model identity and content hash must be strings')
        if not isinstance(self.level, Level):
            raise TypeError('level must be a Level')
        if type(self.dims) is not int or self.dims <= 0:
            raise ValueError('dims must be a positive integer')

    def encode(self) -> bytes:
        """Encode typed fields without separator collisions, including Unicode."""
        suffix = json.dumps([self.level.value, self.content_hash, self.dims],
                            ensure_ascii=True, separators=(',', ':')).encode('ascii')
        return _keyspace_prefix(self.model_id, self.model_version) + suffix


class AppendOnlyError(ValueError):
    """An existing cache key cannot be assigned a different vector."""


class VectorStore:
    def __init__(self, path, map_size=1024 * 1024 * 1024):
        self._env = lmdb.open(os.fspath(path), map_size=map_size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        """Release the environment; repeated closes are harmless."""
        self._env.close()

    def put(self, key: VectorKey, vector: LevelVector) -> None:
        if vector.level is not key.level or len(vector.values) != key.dims:
            raise ValueError('vector dimensions and level must match key')
        # A newline terminates the JSON metadata; the remaining bytes are f64 LE.
        header = json.dumps([vector.level.value, len(vector.values)],
                            separators=(',', ':')).encode('ascii') + b'\n'
        value = header + struct.pack(f'<{key.dims}d', *vector.values)
        with self._env.begin(write=True) as txn:
            encoded = key.encode()
            existing = txn.get(encoded)
            if existing is not None:
                if existing != value:
                    raise AppendOnlyError('cache key already contains a different vector')
                return
            txn.put(encoded, value, overwrite=False)

    def keys(self, model_id: str, model_version: str) -> Iterator[VectorKey]:
        """Stream one keyspace in a read snapshot, retaining O(1) keys.

        Exhaust or close the iterator before closing this store. A paused iterator
        retains its read transaction, which can delay LMDB page reclamation.
        """
        prefix = _keyspace_prefix(model_id, model_version)
        with self._env.begin() as txn:
            with txn.cursor() as cursor:
                found = cursor.set_range(prefix)
                while found:
                    encoded = cursor.key()
                    if not encoded.startswith(prefix):
                        break
                    level, content_hash, dims = json.loads(encoded[len(prefix):])
                    yield VectorKey(model_id, model_version, Level(level), content_hash, dims)
                    found = cursor.next()

    def get(self, key: VectorKey) -> LevelVector | None:
        with self._env.begin() as txn:
            value = txn.get(key.encode())
        if value is None:
            return None
        header, payload = value.split(b'\n', 1)
        level, dims = json.loads(header)
        if level != key.level.value or dims != key.dims or len(payload) != key.dims * 8:
            raise ValueError('stored vector dimensions and level must match key')
        return LevelVector(key.level, struct.unpack(f'<{key.dims}d', payload))
