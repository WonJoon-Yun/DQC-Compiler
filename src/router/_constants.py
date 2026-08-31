from collections import defaultdict
from primitive import Gate, Executable
from utils import atomic_json_dump, build_comm_topology_from_chiplets, build_comm_topology_from_chiplets_with_channels, get_manhattan_distance, logger
from tracer import Tracer
from route import BenchmarkSetup, schedule_blocks
from route.constants import compute_routing_cost
from route.route.qucomm import build_qucomm_execution_window
from analysis.inter_block_distance import (compute_execution_layers_from_dag, compute_inter_block_distance_metric)
from .optim.block_routing.iris import Metrics, RoutingState, _normalize_channels_struct_only
from .optim.early_execution import pipeline_optimization, remove_duplicate_rows
MAX_BLOCK_LIMIT = int(1e10)
HAS_PREP_FILE = None
directions = {'E': (1, 0), 'W': (-1, 0), 'N': (0, 1), 'S': (0, -1)}
opp_dir = {'E': 'W', 'W': 'E', 'N': 'S', 'S': 'N'}
AggNodes = defaultdict(list)