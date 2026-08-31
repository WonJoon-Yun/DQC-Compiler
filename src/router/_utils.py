import functools
def _qucomm_window_lookahead_depth(args):
    base_depth = args.qucomm_gate_lookahead_depth if getattr(args, "qucomm_enable_gate_lookahead", False) else 0
    if (
        base_depth > 0
        and getattr(args, "qucomm_enable_gate_foresight", False)
        and getattr(args, "qucomm_gate_lookahead_option", "opt0") == "opt1"
    ):
        return base_depth + 1
    return base_depth
def serialize_dict(data):
    def convert_channel_dict(channel_dict):
        if not isinstance(channel_dict, dict): return channel_dict
        result = {}
        for key, value in channel_dict.items():
            if isinstance(key, tuple): str_key = str(key)
            else: str_key = str(key)
            result[str_key] = value
        return result
    def convert_recursive(obj):
        """Recursively convert nested structures."""
        if isinstance(obj, dict): return convert_channel_dict(obj)
        elif isinstance(obj, list): return [convert_recursive(item) for item in obj]
        else: return obj
    return convert_recursive(data)
def routing_method(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)
    return wrapper
BLOCK_ORDER_AND_AGGNODES = []
@functools.lru_cache(maxsize=2048)
def budget_key(src, tgt):
    x1, y1 = src
    x2, y2 = tgt
    dx = x2 - x1  # horizontal direction
    dy = y2 - y1  # vertical direction
    if abs(dx) + abs(dy) != 1: raise ValueError(f"Non-adjacent positions: {src} -> {tgt}")
    if dx == 1: return ((x1, y1, 'E'), (x2, y2, 'W'))
    elif dx == -1: return ((x1, y1, 'W'), (x2, y2, 'E'))
    elif dy == 1: return ((x1, y1, 'N'), (x2, y2, 'S'))
    elif dy == -1: return ((x1, y1, 'S'), (x2, y2, 'N'))
    else: raise ValueError(f"Invalid direction between {src} and {tgt}")