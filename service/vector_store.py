"""CA-01 LMDB vectors; unwired by design until SV-02/CA-02.

Each put uses one write transaction; calls allocate O(dims) vector memory.
Keys must fit LMDB's key-size limit. Eviction and append-only policy are deferred.
"""
from dataclasses import dataclass
import json
import os
import struct

import lmdb

from service.vectors import Level, LevelVector


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
        return json.dumps([self.model_id, self.model_version, self.level.value,
                           self.content_hash, self.dims],
                          ensure_ascii=True, separators=(',', ':')).encode('ascii')


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
            txn.put(key.encode(), value)

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
