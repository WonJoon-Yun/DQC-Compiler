"""Assertion helpers for schedule_blocks."""

def _validate_scheduler_inputs(n_blocks, blocks, aggs, block_ids, block_levels=None):
    assert n_blocks > 0, f'[ASSERT schedule_blocks] No blocks to process: len(blocks)={len(blocks)}'
    assert len(aggs) >= n_blocks, f'[ASSERT schedule_blocks] Not enough agg nodes: {len(aggs)} < {n_blocks}'
    assert len(block_ids) >= n_blocks, f'[ASSERT schedule_blocks] Not enough block IDs: {len(block_ids)} < {n_blocks}'
    if block_levels is not None:
        assert len(block_levels) >= n_blocks, f'[ASSERT schedule_blocks] Not enough block levels: {len(block_levels)} < {n_blocks}'

def _validate_block(block, bid, index, agg_node, connectivity):
    assert len(block) > 0, f'[ASSERT schedule_blocks] Block {bid} (index {index}) is empty!'
    assert agg_node in connectivity.nodes, f'[ASSERT schedule_blocks] agg_node {agg_node} for block {bid} not in connectivity!'

def _validate_route_result(detailed_rows, channel_dict, num_relocates, num_recnots, num_epr_release, bid):
    assert isinstance(detailed_rows, list), f'[ASSERT schedule_blocks] Block {bid}: detailed_rows is not a list'
    assert isinstance(channel_dict, dict), f'[ASSERT schedule_blocks] Block {bid}: channel_dict is not a dict'
    assert num_relocates >= 0, f'[ASSERT schedule_blocks] Block {bid}: num_relocates={num_relocates} < 0'
    assert num_recnots >= 0, f'[ASSERT schedule_blocks] Block {bid}: num_recnots={num_recnots} < 0'
    assert num_epr_release >= 0, f'[ASSERT schedule_blocks] Block {bid}: num_epr_release={num_epr_release} < 0'

def _validate_aggregate(done_ids, n_blocks, per_block_metrics, total_relocates, total_recnots, total_releases, channel_dict, combined_schedule):
    assert len(done_ids) == n_blocks, f'[ASSERT schedule_blocks] Processed {len(done_ids)} blocks but expected {n_blocks}'
    sum_reloc = sum((m.relocates for m in per_block_metrics))
    sum_recnot = sum((m.recnots for m in per_block_metrics))
    sum_release = sum((m.releases for m in per_block_metrics))
    assert total_relocates == sum_reloc, f'[ASSERT schedule_blocks] total_relocates={total_relocates} != sum(per_block)={sum_reloc}'
    assert total_recnots == sum_recnot, f'[ASSERT schedule_blocks] total_recnots={total_recnots} != sum(per_block)={sum_recnot}'
    assert total_releases == sum_release, f'[ASSERT schedule_blocks] total_releases={total_releases} != sum(per_block)={sum_release}'
    for (edge, val) in channel_dict.items():
        assert val > 0, f'[ASSERT schedule_blocks] Final channel_dict has non-positive value at edge {edge}: {val}'
    assert len(combined_schedule) == n_blocks, f'[ASSERT schedule_blocks] combined_schedule has {len(combined_schedule)} segments but expected {n_blocks}'

