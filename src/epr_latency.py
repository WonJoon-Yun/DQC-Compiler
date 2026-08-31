"""Paper-consistent EPR-generation latency helpers."""
from dataclasses import dataclass
from typing import Dict, Literal
AtomSystem = Literal['Rb', 'Yb']

@dataclass(frozen=True)
class EprLatencyBreakdown:
    load_and_move_us: float
    state_preparation_us: float
    entanglement_attempt_us: float
    depump_us: float

    @property
    def total_us(self) -> float:
        return self.load_and_move_us + self.state_preparation_us + self.entanglement_attempt_us + self.depump_us
_BREAKDOWNS_US: Dict[AtomSystem, EprLatencyBreakdown] = {'Rb': EprLatencyBreakdown(load_and_move_us=100.0, state_preparation_us=3.0, entanglement_attempt_us=12.0, depump_us=6.0), 'Yb': EprLatencyBreakdown(load_and_move_us=100.0, state_preparation_us=2.1, entanglement_attempt_us=1.0, depump_us=6.0)}

def get_epr_latency_breakdown_us(atom_system: AtomSystem) -> EprLatencyBreakdown:
    """Return the EPR-generation latency breakdown in microseconds."""
    if atom_system not in _BREAKDOWNS_US:
        raise ValueError(f'Unknown atom_system={atom_system!r}; expected one of {list(_BREAKDOWNS_US.keys())}')
    return _BREAKDOWNS_US[atom_system]

def get_total_epr_generation_us(atom_system: AtomSystem) -> float:
    return get_epr_latency_breakdown_us(atom_system).total_us

def get_total_epr_generation_seconds(atom_system: AtomSystem) -> float:
    return get_total_epr_generation_us(atom_system) * 1e-06