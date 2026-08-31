def simulate_consume_path(path, ch_sim):
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        ch_sim[(u, v)] = ch_sim.get((u, v), 0) + 1
        ch_sim[(v, u)] = ch_sim.get((v, u), 0) - 1
def sim_channel_valid(ch_sim):
    """Check that all channel values remain > 0 in simulation."""
    return all(val > 0 for val in ch_sim.values())