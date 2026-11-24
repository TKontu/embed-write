"""Per-level whitening and all-but-the-top arms for gate G-03 (NM-02).

Production caller: the G-03 runner arm; unwired by design until G-03 wiring.
Persisting an adopted transform with the genre is NM-03 (to_dict/from_dict
are its input).

Fitting streams the input once: memory is O(d^2) for the running mean and
covariance and never holds the corpus. Eigendecomposition uses pure-Python
cyclic Jacobi, O(d^3) per sweep; that cost is untested at d=768 (residual).
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
import math

from service.vectors import Level, LevelVector

WHITENING = 'whitening'
ABTT = 'abtt'


class WhiteningError(ValueError):
    """Fit or apply input is empty, inconsistent, non-finite or too small."""


def _values(vector, level: Level, dims: int | None) -> tuple[float, ...]:
    if isinstance(vector, LevelVector):
        if vector.level is not level:
            raise WhiteningError(f'vector level {vector.level.value} != {level.value}')
        vector = vector.values
    values = tuple(float(v) for v in vector)
    if not values:
        raise WhiteningError('vectors must be non-empty')
    if not all(math.isfinite(v) for v in values):
        raise WhiteningError('vector components must be finite')
    if dims is not None and len(values) != dims:
        raise WhiteningError(f'mismatched dimensions: expected {dims}, got {len(values)}')
    return values


def _moments(vectors: Iterable, level: Level):
    """One-pass Welford mean and sample covariance (n - 1)."""
    if not isinstance(level, Level):
        raise TypeError('level must be a Level')
    n = 0
    dims = None
    mean: list[float] = []
    m2: list[list[float]] = []
    for vector in vectors:
        x = _values(vector, level, dims)
        if dims is None:
            dims = len(x)
            mean = [0.0] * dims
            m2 = [[0.0] * dims for _ in range(dims)]
        n += 1
        delta = [x[i] - mean[i] for i in range(dims)]
        for i in range(dims):
            mean[i] += delta[i] / n
        delta2 = [x[i] - mean[i] for i in range(dims)]
        for i in range(dims):
            row, di = m2[i], delta[i]
            for j in range(dims):
                row[j] += di * delta2[j]
    if n == 0:
        raise WhiteningError('cannot fit on empty input')
    if n < 2:
        raise WhiteningError(f'need at least 2 vectors to fit, got {n}')
    cov = [[(m2[i][j] + m2[j][i]) / (2 * (n - 1)) for j in range(dims)] for i in range(dims)]
    return n, dims, tuple(mean), cov


def _jacobi(a: list[list[float]], tol: float = 1e-12, max_sweeps: int = 100):
    """Eigen-decompose symmetric a; return (eigenvalues, eigenvectors) descending."""
    d = len(a)
    a = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(d)] for i in range(d)]
    scale = max((abs(x) for row in a for x in row), default=0.0) or 1.0
    for _ in range(max_sweeps):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(d) for j in range(d) if i != j))
        if off <= tol * scale:
            break
        for p in range(d - 1):
            for q in range(p + 1, d):
                apq = a[p][q]
                if abs(apq) <= 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * apq)
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(d):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(d):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(d):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    order = sorted(range(d), key=lambda i: -a[i][i])
    values = [a[i][i] for i in order]
    vectors = [[v[k][i] for k in range(d)] for i in order]  # rows are eigenvectors
    return values, vectors


def _as_matrix(rows) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(x) for x in row) for row in rows)


@dataclass(frozen=True)
class Transform:
    """A fitted per-level transform. whitening uses matrix; abtt uses components."""

    kind: str
    level: Level
    dims: int
    mean: tuple[float, ...]
    matrix: tuple[tuple[float, ...], ...] = ()
    components: tuple[tuple[float, ...], ...] = ()
    n_fitted: int = 0

    def __post_init__(self):
        if self.kind not in (WHITENING, ABTT):
            raise WhiteningError(f'unknown transform kind {self.kind!r}')
        if not isinstance(self.level, Level):
            raise TypeError('level must be a Level')
        if self.n_fitted < 2:
            raise WhiteningError('n_fitted must be at least 2')
        if len(self.mean) != self.dims:
            raise WhiteningError('mean length does not match dims')
        rows = self.matrix if self.kind == WHITENING else self.components
        if self.kind == WHITENING and len(rows) != self.dims:
            raise WhiteningError('whitening matrix must be dims x dims')
        if any(len(row) != self.dims for row in rows):
            raise WhiteningError('transform rows must have dims columns')

    def apply(self, vector) -> list[float]:
        x = _values(vector, self.level, self.dims)
        centered = [x[i] - self.mean[i] for i in range(self.dims)]
        if self.kind == WHITENING:
            return [math.fsum(r[j] * centered[j] for j in range(self.dims)) for r in self.matrix]
        out = centered
        for u in self.components:
            proj = math.fsum(u[j] * centered[j] for j in range(self.dims))
            out = [out[j] - proj * u[j] for j in range(self.dims)]
        return out

    def apply_batch(self, vectors: Iterable) -> Iterator[list[float]]:
        """Yield transformed vectors lazily; O(d) memory beyond the transform."""
        for vector in vectors:
            yield self.apply(vector)

    def to_dict(self) -> dict:
        return {
            'kind': self.kind,
            'level': self.level.value,
            'dims': self.dims,
            'mean': list(self.mean),
            'matrix': [list(r) for r in self.matrix],
            'components': [list(r) for r in self.components],
            'n_fitted': self.n_fitted,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Transform':
        return cls(
            kind=data['kind'],
            level=Level(data['level']),
            dims=int(data['dims']),
            mean=tuple(float(x) for x in data['mean']),
            matrix=_as_matrix(data.get('matrix', ())),
            components=_as_matrix(data.get('components', ())),
            n_fitted=int(data['n_fitted']),
        )


def fit_whitening(vectors: Iterable, level: Level, eps: float = 1e-6) -> Transform:
    """Fit ZCA whitening W = E diag(1/sqrt(lambda + eps)) E^T on one level."""
    if not (math.isfinite(eps) and eps >= 0):
        raise WhiteningError('eps must be finite and non-negative')
    n, dims, mean, cov = _moments(vectors, level)
    values, vecs = _jacobi(cov)
    inv = [1 / math.sqrt(max(lam, 0.0) + eps) if max(lam, 0.0) + eps > 0 else 0.0
           for lam in values]
    matrix = [[math.fsum(vecs[k][i] * inv[k] * vecs[k][j] for k in range(dims))
               for j in range(dims)] for i in range(dims)]
    return Transform(WHITENING, level, dims, mean, matrix=_as_matrix(matrix), n_fitted=n)


def fit_abtt(vectors: Iterable, level: Level, n_components: int = 2) -> Transform:
    """Fit all-but-the-top (Mu & Viswanath 2018): remove mean and top-D directions."""
    if not isinstance(n_components, int) or n_components < 0:
        raise WhiteningError('n_components must be a non-negative int')
    n, dims, mean, cov = _moments(vectors, level)
    if n_components >= dims:
        raise WhiteningError(f'n_components ({n_components}) must be < dims ({dims})')
    _, vecs = _jacobi(cov)
    return Transform(ABTT, level, dims, mean, components=_as_matrix(vecs[:n_components]),
                     n_fitted=n)
