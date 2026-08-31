from ._common import dataclass
@dataclass(slots=True)
class Metrics:
    relocates: int
    recnots: int
    releases: int
W_RECNOT, W_RELOC, W_RELEASE = 1.77, 1, 1
W_IMBALANCE = 1