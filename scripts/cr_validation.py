"""Validate the future-cost estimator C_R (Eq. 3) against realized costs.

Phase 1: run the normal opt0 pipeline (run.py via runpy) with capture hooks on
schedule_blocks / choose_qucomm_global_foresight_plan, recording per-window
inputs (blocks, start state) and the planner's chosen forced plans.
Phase 2: replay each window's execution-block gates; at every non-local gate
decision with >=2 candidate routes, log per candidate:
  C_g+C_EPR (raw first-step routing cost), C_R (beta-weighted, as used),
  C_R_unweighted (beta=1 over the same remaining set R), est_total, chosen.
Ground truth per candidate: force-select it, then continue "normal scheduling"
(fresh planner re-plan before every subsequent gate, MPC-style) to the end of
the window; realized_R = N_RELOCATE + 1.77*N_ReCNOT over the gates of R.
Outputs: decisions.csv + summary.json (figure built by scripts/plot/fig_12_crval.py).

Usage: python scripts/cr_validation.py n32|n120
"""
import csv
import json
import math
import os
import runpy
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))

CONFIGS = {
    'n32': {
        'circuit': 'bench/qaoa_3reg/qaoa_3reg_n32.qasm', 'name': 'qaoa_3reg_n32',
        'system_qubits_per_chip': '14', 'num_communication_per_link': '3',
    },
    'n120': {
        'circuit': 'bench/qaoa_3reg/qaoa_3reg_n120.qasm', 'name': 'qaoa_3reg_n120',
        'system_qubits_per_chip': '40', 'num_communication_per_link': '5',
    },
}

ALPHA = 1.77
LOOKAHEAD_DEPTH = 4
BEAM_WIDTH = 16
SORT_MODE = 'current_then_total'
PRUNE_MODE = 'selection_sort'
DECAY_MODE = 'linear'
CAND_EVAL = 'all_nodes'
TIEBREAK = 'legacy_direct'
HYBRID = True

CAPTURES = []


def install_hooks():
    import route.scheduler._schedule as sched
    orig_sb = sched.schedule_blocks
    orig_plan = sched.choose_qucomm_global_foresight_plan

    def sb_wrapper(blocks, aggs, block_ids, start_state, connectivity, K, **kw):
        rec = {
            'blocks': blocks, 'aggs': aggs, 'block_ids': block_ids,
            'position_table': start_state.position_table.copy(),
            'channel_dict': start_state.channel_dict.copy(),
            'atom_paths': {k: list(v) for (k, v) in start_state.atom_paths.items()},
            'connectivity': connectivity, 'K': K,
            'block_levels': kw.get('block_levels'),
            'interact_info': kw.get('interact_info'),
            'forced_plans': None,
        }
        CAPTURES.append(rec)
        return orig_sb(blocks, aggs, block_ids, start_state, connectivity, K, **kw)

    def plan_wrapper(**kw):
        out = orig_plan(**kw)
        if CAPTURES:
            CAPTURES[-1]['forced_plans'] = out[0]
        return out

    sched.schedule_blocks = sb_wrapper
    sched.choose_qucomm_global_foresight_plan = plan_wrapper
    import router._iris as ath
    ath.schedule_blocks = sb_wrapper


def run_pipeline(cfg, results_dir):
    sys.argv = ['run.py',
        '--circuit', cfg['circuit'], '--name', cfg['name'],
        '--mapping_method', 'ILP', '--results_dir', results_dir,
        '--numchipletsx', '2', '--numchipletsy', '2',
        '--system_qubits_per_chip', cfg['system_qubits_per_chip'],
        '--num_communication_per_link', cfg['num_communication_per_link'],
        '--max_1d', '10', '--routing_method', 'IRIS4',
        '--disable_oee_refine', '--oee_max_passes', '5', '--oee_tol', '0.0',
        '--K1', '1', '--K2', '6', '--gate_cnt', '0',
        '--qucomm_candidate_eval_mode', CAND_EVAL,
        '--qucomm_one_meet_tiebreak_mode', TIEBREAK,
        '--qucomm_enable_teleport_hybrid',
        '--qucomm_enable_gate_lookahead', '--qucomm_gate_lookahead_depth', str(LOOKAHEAD_DEPTH),
        '--qucomm_gate_lookahead_option', 'opt1',
        '--qucomm_gate_lookahead_beam_width', str(BEAM_WIDTH),
        '--qucomm_gate_lookahead_sort_mode', SORT_MODE,
        '--qucomm_gate_lookahead_prune_mode', PRUNE_MODE,
        '--qucomm_future_block_decay_mode', DECAY_MODE,
        '--qucomm_enable_gate_foresight', '--qucomm_enable_future_touch']
    runpy.run_path(os.path.join(ROOT, 'src', 'run.py'), run_name='__main__')


# ---------------- mini planner (mirror of _choose_..._opt1 beam loop) --------

from route.route.qucomm.foresight_planner._utils import (
    _flatten_all_gate_specs, _snapshot_state, _wrap_simulate_result)
from route.route.qucomm.gate_rollout_planner import (
    _apply_guidance_sort_fields, _candidate_nodes_for_mode, _diversity_prune_beam,
    _enumerate_gate_actions, _future_block_decay_weight,
    _future_specs_within_block_horizon, _mapping_key, _resolve_block_agg,
    simulate_qucomm_gate_transition)
from route.route.qucomm.gate_rollout_planner._guidance import _iris_guidance_step
from route.aggregation import compute_dynamic_agg
from route.cache import GraphCache


def _sim(ctx, gate_spec, future_specs, state, block_agg, forced_action):
    return simulate_qucomm_gate_transition(
        gate_spec=gate_spec, future_gate_specs=future_specs, state=state,
        connectivity=ctx['connectivity'], aggregation_node=block_agg,
        candidate_eval_mode=CAND_EVAL, one_meet_tiebreak_mode=TIEBREAK,
        enable_teleport_hybrid=HYBRID,
        forced_action=forced_action,
        disable_searchspace=False, disable_costfn=False,
        double_count_future_ops=False, disable_future_touch=False)


def _weight(ctx, block_index):
    return _future_block_decay_weight(0, block_index, horizon_depth=LOOKAHEAD_DEPTH,
                                      decay_mode=DECAY_MODE, block_levels=ctx['block_levels'])


def mini_beam(ctx, specs, offset, state, first_action=None):
    """Beam plan over specs[offset:]; returns best branch info."""
    init = {'state': state, '_mk': _mapping_key(state['position_table']), '_ak': (),
            'actions': (), 'cost_vector': [], 'raw_vector': [], 'total_cost': 0.0,
            'sort_cost_vector': [], 'sort_total_cost': 0.0,
            'teleports': 0, 'recnots': 0, 'releases': 0, 'block_aggs': {},
            'prefix_states': {}, 'guidance_total_adjustment': 0.0, 'guidance_trace': ()}
    beam = [init]
    for d in range(offset, len(specs)):
        gate_spec = specs[d]
        future_specs = _future_specs_within_block_horizon(specs, d, LOOKAHEAD_DEPTH)
        w = _weight(ctx, gate_spec['block_index'])
        (s, t) = gate_spec['gate']
        active = {s, t}
        for spec in future_specs:
            active.add(spec['gate'][0]); active.add(spec['gate'][1])
        next_beam = []
        gcache = GraphCache(ctx['connectivity'])
        for node in beam:
            st = node['state']
            block_agg = _resolve_block_agg(node, gate_spec, blocks=ctx['blocks'],
                aggs=ctx['aggs'], connectivity=ctx['connectivity'], start_block_index=0)
            if d == offset and first_action is not None:
                actions = [first_action]
            else:
                pos_s = st['position_table'][s]; pos_t = st['position_table'][t]
                cnodes = _candidate_nodes_for_mode(active, st['position_table'],
                    ctx['connectivity'], gcache, CAND_EVAL)
                dyn_agg = compute_dynamic_agg((s, t), [sp['gate'] for sp in future_specs],
                    st['position_table'], block_agg, ctx['connectivity'], gcache,
                    st['channel_dict'], PRINT_DEBUG=False, candidate_nodes=cnodes)
                actions = _enumerate_gate_actions(s=s, t=t, pos_s=pos_s, pos_t=pos_t,
                    dyn_agg=dyn_agg, future_gates=[sp['gate'] for sp in future_specs],
                    qubit_positions=st['position_table'], active_qubits=active,
                    connectivity=ctx['connectivity'], gcache=gcache,
                    channel_dict=st['channel_dict'], candidate_eval_mode=CAND_EVAL,
                    one_meet_tiebreak_mode=TIEBREAK, candidate_limit=6,
                    disable_searchspace=False, disable_costfn=False,
                    double_count_future_ops=False, disable_future_touch=False)
            for action in actions:
                result = _sim(ctx, gate_spec, future_specs, st, block_agg,
                              None if action['mode'] == 'baseline' else action)
                step_state = _wrap_simulate_result(result)
                g_step = _iris_guidance_step(iris_guidance=None, gate_spec=gate_spec,
                    active_qubits=active, result=result, step_state=step_state, gcache=gcache)
                cv = list(node['cost_vector']) + [result['routing_cost'] * w]
                rv = list(node['raw_vector']) + [
                    result['cost_reloc'] + ALPHA * result['cost_recnot']]
                sel = result['selected_action']
                ak = node['_ak'] + ((gate_spec['block_index'], gate_spec['local_gate_index'],
                                     sel['mode'], sel.get('meeting_node'), sel.get('move_qubit')),)
                child = {'state': step_state, '_mk': _mapping_key(step_state['position_table']),
                         '_ak': ak, 'actions': node['actions'] + ((gate_spec, sel),),
                         'cost_vector': cv, 'raw_vector': rv,
                         'total_cost': round(sum(cv), 8),
                         'teleports': node['teleports'] + result['cost_reloc'] + result['cost_release'],
                         'recnots': node['recnots'] + result['cost_recnot'],
                         'releases': node['releases'] + result['cost_release'],
                         'block_aggs': dict(node['block_aggs']), 'prefix_states': {},
                         'guidance_total_adjustment': 0.0, 'guidance_trace': ()}
                _apply_guidance_sort_fields(child, list(cv), child['total_cost'])
                next_beam.append(child)
        (beam, _meta) = _diversity_prune_beam(next_beam, BEAM_WIDTH, SORT_MODE,
                                              prune_mode=PRUNE_MODE)
    best = min(beam, key=lambda n: (round(n.get('sort_total_cost', n['total_cost']), 8),
                                    n['_ak']))
    return best


def action_key(sel):
    node = sel.get('meeting_node')
    return (sel.get('mode'), tuple(node) if node is not None else None, sel.get('move_qubit'))


def analyze(cfg, out_dir):
    decisions = []
    n_single = 0
    n_local = 0
    n_total_gates = 0
    replay_reloc_total = 0.0
    replay_release_total = 0
    mpc_cache = {}

    for (widx, cap) in enumerate(CAPTURES):
        ctx = {'blocks': cap['blocks'], 'aggs': cap['aggs'],
               'connectivity': cap['connectivity'], 'block_levels': cap['block_levels']}
        specs = _flatten_all_gate_specs(cap['blocks'], cap['block_ids'], start_block_index=0)
        if not specs:
            continue
        state = _snapshot_state(cap['position_table'], cap['channel_dict'],
                                cap['atom_paths'], cap['interact_info'])
        forced = cap['forced_plans'] or {}
        exec_plan = forced.get(0, {})

        def mpc_realized(ctx, specs, start_offset, state0):
            total = 0.0
            st = state0
            for k in range(start_offset, len(specs)):
                plan = mini_beam(ctx, specs, k, st)
                first = plan['actions'][0][1]
                gate_spec = specs[k]
                future_specs = _future_specs_within_block_horizon(specs, k, LOOKAHEAD_DEPTH)
                node = {'block_aggs': {}, 'state': st}
                block_agg = _resolve_block_agg(node, gate_spec, blocks=ctx['blocks'],
                    aggs=ctx['aggs'], connectivity=ctx['connectivity'], start_block_index=0)
                r = _sim(ctx, gate_spec, future_specs, st, block_agg,
                         None if first['mode'] == 'baseline' else first)
                total += r['cost_reloc'] + ALPHA * r['cost_recnot']
                st = _wrap_simulate_result(r)
            return total

        # replay execution block (block_index 0) gates along the actual plan
        n_exec = len(_flatten_all_gate_specs(cap['blocks'][:1], cap['block_ids'][:1]))
        for d in range(n_exec):
            gate_spec = specs[d]
            (s, t) = gate_spec['gate']
            n_total_gates += 1
            future_specs = _future_specs_within_block_horizon(specs, d, LOOKAHEAD_DEPTH)
            node = {'block_aggs': {}, 'state': state}
            block_agg = _resolve_block_agg(node, gate_spec, blocks=ctx['blocks'],
                aggs=ctx['aggs'], connectivity=ctx['connectivity'], start_block_index=0)
            nonlocal_gate = state['position_table'][s] != state['position_table'][t]
            cand_rows = []
            if nonlocal_gate:
                gcache = GraphCache(ctx['connectivity'])
                active = {s, t}
                for spec in future_specs:
                    active.add(spec['gate'][0]); active.add(spec['gate'][1])
                pos_s = state['position_table'][s]; pos_t = state['position_table'][t]
                cnodes = _candidate_nodes_for_mode(active, state['position_table'],
                    ctx['connectivity'], gcache, CAND_EVAL)
                dyn_agg = compute_dynamic_agg((s, t), [sp['gate'] for sp in future_specs],
                    state['position_table'], block_agg, ctx['connectivity'], gcache,
                    state['channel_dict'], PRINT_DEBUG=False, candidate_nodes=cnodes)
                actions = _enumerate_gate_actions(s=s, t=t, pos_s=pos_s, pos_t=pos_t,
                    dyn_agg=dyn_agg, future_gates=[sp['gate'] for sp in future_specs],
                    qubit_positions=state['position_table'], active_qubits=active,
                    connectivity=ctx['connectivity'], gcache=gcache,
                    channel_dict=state['channel_dict'], candidate_eval_mode=CAND_EVAL,
                    one_meet_tiebreak_mode=TIEBREAK, candidate_limit=6,
                    disable_searchspace=False, disable_costfn=False,
                    double_count_future_ops=False, disable_future_touch=False)
                seen_keys = {}
                for action in actions:
                    branch = mini_beam(ctx, specs, d, state,
                                       first_action=action)
                    first_sel = branch['actions'][0][1]
                    key = action_key(first_sel)
                    if key in seen_keys:
                        continue
                    seen_keys[key] = (action, branch)
                if len(seen_keys) >= 2:
                    for (key, (action, branch)) in seen_keys.items():
                        cg_epr = branch['raw_vector'][0]
                        cr_beta = sum(branch['cost_vector'][1:])
                        cr_unw = sum(branch['raw_vector'][1:])
                        est_total = branch['cost_vector'][0] + cr_beta
                        # realized: commit first step, then MPC re-plan per gate
                        r0 = _sim(ctx, gate_spec, future_specs, state, block_agg,
                                  None if action['mode'] == 'baseline' else action)
                        st1 = _wrap_simulate_result(r0)
                        realized_R = mpc_realized(ctx, specs, d + 1, st1)
                        realized_total = (r0['cost_reloc'] + ALPHA * r0['cost_recnot']) + realized_R
                        cand_rows.append({
                            'window': widx, 'depth': d, 'gate': f'{s}-{t}',
                            'cand': str(key), 'C_g_epr': cg_epr,
                            'C_R_beta': round(cr_beta, 6),
                            'C_R_unweighted': round(cr_unw, 6),
                            'est_total': round(est_total, 6),
                            'realized_R': round(realized_R, 6),
                            'realized_total': round(realized_total, 6),
                            'chosen': 0})
                else:
                    n_single += 1
            else:
                n_local += 1

            # execute actual plan action for this gate (deterministic replay)
            fa = exec_plan.get(gate_spec['local_gate_index'])
            r = _sim(ctx, gate_spec, future_specs, state, block_agg, fa)
            replay_reloc_total += r['cost_reloc'] + ALPHA * r['cost_recnot']
            replay_release_total += r['cost_release']
            chosen_key = action_key(r['selected_action'])
            for row in cand_rows:
                if row['cand'] == str(chosen_key):
                    row['chosen'] = 1
            if cand_rows and not any(row['chosen'] for row in cand_rows):
                # chosen action not among logged candidates (e.g. recovery); tag nearest
                cand_rows = []
                n_single += 1
            if cand_rows:
                decisions.append(cand_rows)
            state = _wrap_simulate_result(r)

    # ------- stats -------
    flat = [row for rows in decisions for row in rows]
    n_dec = len(decisions)
    agree = 0
    agree_crdec = 0
    n_crdec = 0
    penalties = []
    for rows in decisions:
        best_est = min(rows, key=lambda r: (r['est_total'], r['cand']))
        best_real = min(rows, key=lambda r: (r['realized_total'], r['cand']))
        chosen = next((r for r in rows if r['chosen']), None)
        ok = best_est['cand'] == best_real['cand']
        agree += int(ok)
        cg = {round(r['C_g_epr'], 6) for r in rows}
        if len(cg) == 1:
            n_crdec += 1
            agree_crdec += int(ok)
        if not ok and chosen is not None:
            penalties.append(chosen['realized_total'] - best_real['realized_total'])
        for r in rows:
            r['disagreement'] = int(not ok)

    def spearman(xs, ys):
        def rank(v):
            order = sorted(range(len(v)), key=lambda i: v[i])
            rk = [0.0] * len(v)
            i = 0
            while i < len(order):
                j = i
                while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                    j += 1
                avg = (i + j) / 2.0 + 1
                for k2 in range(i, j + 1):
                    rk[order[k2]] = avg
                i = j + 1
            return rk
        rx, ry = rank(xs), rank(ys)
        mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
        num = sum((a - mx) * (b - my) for (a, b) in zip(rx, ry))
        den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
        return num / den if den else float('nan')

    rho = spearman([r['C_R_unweighted'] for r in flat], [r['realized_R'] for r in flat]) if flat else float('nan')
    total_teff = replay_reloc_total
    summary = {
        'n_decisions': n_dec, 'n_candidates': len(flat),
        'n_single_candidate': n_single, 'n_local_gates': n_local,
        'n_exec_gates': n_total_gates,
        'agreement': agree / n_dec if n_dec else float('nan'),
        'n_CR_decisive': n_crdec,
        'agreement_CR_decisive': agree_crdec / n_crdec if n_crdec else float('nan'),
        'spearman_rho': rho,
        'mean_penalty': sum(penalties) / len(penalties) if penalties else 0.0,
        'max_penalty': max(penalties) if penalties else 0.0,
        'penalty_share': sum(penalties) / total_teff if total_teff else 0.0,
        'replay_total_teff': total_teff,
        'replay_release_total': replay_release_total,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'decisions.csv'), 'w', newline='') as f:
        wtr = csv.DictWriter(f, fieldnames=list(flat[0].keys()) if flat else ['empty'])
        wtr.writeheader()
        for r in flat:
            wtr.writerow(r)
    with open(os.path.join(out_dir, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=1)
    print('[CR-VALIDATION SUMMARY]')
    for (k, v) in summary.items():
        print(f'  {k}: {v}')
    return summary


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'n32'
    cfg = CONFIGS[which]
    out_dir = os.path.join(ROOT, 'results', 'cr_validation', which)
    install_hooks()
    t0 = time.time()
    run_pipeline(cfg, os.path.join(out_dir, 'pipeline'))
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    print(f'[cr] pipeline done in {time.time()-t0:.1f}s, windows captured: {len(CAPTURES)}')
    t1 = time.time()
    analyze(cfg, out_dir)
    print(f'[cr] analysis done in {time.time()-t1:.1f}s')


if __name__ == '__main__':
    main()
