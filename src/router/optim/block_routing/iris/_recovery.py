from typing import Any, List, Optional, Sequence, Tuple
from ._channels import (_diff_channels, _normalize_channels_struct_only, _validate_channels_nonneg)
from ._common import (VERBOSE_SEARCH, Block, GateRow, Pos, QuCommFn, dataclass)
from ._cost import Metrics
from ._state import (RoutingState, _recompute_state_hash)
@dataclass(slots=True)
class RecoveryConfig:
    lookahead_restore_path: Any
    get_agg_node_func: Any
    num_comm_qubits: int
    min_comm_value: int = 1
    max_comm_value: int = 8
    K_restore: int = 1
    verbose: bool = False
    restore_iter_cap: int = 1000
    use_all_qubits: bool = False
    micro_unlock_steps: Optional[int] = None