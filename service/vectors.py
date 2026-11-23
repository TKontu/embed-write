"""I2 level-safe vectors; unwired by design until EM-01 returns LevelVector.

Operations use O(d) memory. Raw dot products retain float overflow limits;
cosine normalizes first to avoid overflow in the vector norms.
"""

from dataclasses import dataclass
from enum import Enum
import math

from service.normalize import l2_normalize


class Level(Enum):
    SENTENCE = 'sentence'
    BLOCK = 'block'
    SECTION = 'section'


class CrossLevelError(TypeError):
    """An operation attempted to compare different granularity levels."""


@dataclass(frozen=True, eq=False)
class LevelVector:
    level: Level
    values: tuple[float, ...]

    def __post_init__(self):
        if not isinstance(self.level, Level):
            raise TypeError('level must be a Level')
        values = tuple(float(value) for value in self.values)
        if not values or not all(math.isfinite(value) for value in values):
            raise ValueError('values must be non-empty and finite')
        object.__setattr__(self, 'values', values)

    def __eq__(self, other):
        if not isinstance(other, LevelVector):
            return NotImplemented
        _same_level(self, other)
        return self.values == other.values

    __hash__ = None


def _same_level(a: LevelVector, b: LevelVector) -> None:
    if a.level is not b.level:
        raise CrossLevelError(f'Cannot compare {a.level.name} with {b.level.name}')


def _compatible(a: LevelVector, b: LevelVector) -> None:
    _same_level(a, b)
    if len(a.values) != len(b.values):
        raise ValueError('Vector dimensions must match')


def dot(a: LevelVector, b: LevelVector) -> float:
    """Compute a same-level inner product."""
    _compatible(a, b)
    return math.fsum(x * y for x, y in zip(a.values, b.values))


def normalized(v: LevelVector) -> LevelVector:
    """Return a unit vector at the original level; reject zero vectors."""
    return LevelVector(v.level, l2_normalize(v.values))


def cosine(a: LevelVector, b: LevelVector) -> float:
    """Compute same-level cosine similarity; reject zero vectors."""
    _compatible(a, b)
    return dot(normalized(a), normalized(b))
