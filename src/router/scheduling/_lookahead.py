"""Lookahead scheduling mixin — extracted from _baseline.py."""
from uuid import uuid4

class LookaheadMixin:

    def GetQuCommLookaheadIR(self, routing_result, verbose=False, cnt=0):
        if not hasattr(self, 'TIME'):
            self.TIME = 0
        import pandas as pd
        routing_result = pd.DataFrame(routing_result)
        LookaheadIRs = []
        try:
            unique_time = sorted(set(routing_result['Time']))
        except Exception:
            raise ValueError(f'[GetQuCommLookaheadIR] routing_result: {routing_result}') from None
        TMAX = max(unique_time)
        for t in unique_time:
            LookaheadIR = {}
            move_scheduled = set()
            sub_df = routing_result[routing_result['Time'] == t]
            for g in sub_df.itertuples():
                (block_id, sidx, spos, sposnext, tidx, tpos, tposnext, op) = (g.BlockID, g.SIdx, g.SPos, g.SNextPos, g.TIdx, g.TPos, g.TNextPos, g.CNOT)
                if op:
                    LookaheadIR[sidx, tidx] = {'SIdx': sidx, 'TIdx': tidx, 'SPos': spos, 'TPos': tpos, 'Operation': 'CNOT', 'OptSPos': spos, 'OptTPos': tpos, 'BeforeOperationSourcePath': [spos], 'BeforeOperationTargetPath': [tpos], 'AfterOperationSourcePath': [], 'AfterOperationTargetPath': [], 'UniqueID': f'{self.TIME + t + 1}_{block_id}_{sidx}_{tidx}_{uuid4().hex}_CNOT', 'NextOperation': None, 'Cops': 0}
                else:
                    if spos != sposnext and (sidx, spos, sposnext, block_id) not in move_scheduled:
                        LookaheadIR[sidx, sidx] = {'SIdx': sidx, 'TIdx': sidx, 'SPos': spos, 'TPos': spos, 'OptSPos': sposnext, 'OptTPos': sposnext, 'BeforeOperationSourcePath': [spos, sposnext], 'BeforeOperationTargetPath': [], 'AfterOperationSourcePath': [], 'AfterOperationTargetPath': [], 'UniqueID': f'{self.TIME + t + 1}_{block_id}_{sidx}_{tidx}_{uuid4().hex}', 'NextOperation': True, 'Cops': self.args.time_int_SWAP}
                        move_scheduled.add((sidx, spos, sposnext, block_id))
                    if tpos != tposnext and (tidx, tpos, tposnext, block_id) not in move_scheduled:
                        LookaheadIR[tidx, tidx] = {'SIdx': tidx, 'TIdx': tidx, 'SPos': tpos, 'TPos': tpos, 'OptSPos': tposnext, 'OptTPos': tposnext, 'BeforeOperationSourcePath': [tpos, tposnext], 'BeforeOperationTargetPath': [], 'AfterOperationSourcePath': [], 'AfterOperationTargetPath': [], 'UniqueID': f'{self.TIME + t + 1}_{block_id}_{sidx}_{tidx}_{uuid4().hex}', 'NextOperation': True, 'Cops': self.args.time_int_SWAP}
                        move_scheduled.add((tidx, tpos, tposnext, block_id))
                    evicted_atom = getattr(g, 'evicted_atom', None)
                    if evicted_atom is not None and pd.notna(evicted_atom):
                        mover = sidx if spos != sposnext else tidx
                        LookaheadIR[mover, mover]['evicted_atom'] = int(evicted_atom)
            LookaheadIRs.append(LookaheadIR)
        self.TIME += TMAX
        if getattr(self, '_channel_aware_blocks', False) and getattr(self.args, 'schedule_merge_layers', False):
            # Flattening IR groups must keep the next group's tick zero after this one.
            self.TIME += 1
        return LookaheadIRs
