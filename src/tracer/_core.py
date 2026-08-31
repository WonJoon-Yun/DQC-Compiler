import os
import pandas as pd
TRACER_BASE_COLUMNS = ['count', 'layer_idx', 'atom0', 'atom1', 'pos0', 'pos1', 'optype', 'start_time', 'end_time', 'is_moveback', 'display_optype']
TRACER_FIDELITY_COLUMNS = ['op_fidelity', 'op_infidelity', 'cum_local_cnots', 'cum_transfers', 'cum_remote_cnots', 'cum_relocates', 'cum_fidelity_local_2q', 'cum_fidelity_transfer', 'cum_fidelity_remote_2q', 'cum_fidelity_relocation', 'cum_fidelity_deco', 'cum_fidelity_total']
TRACER_COLUMNS = TRACER_BASE_COLUMNS + TRACER_FIDELITY_COLUMNS + []

class TracerCore:
    """Core data-management mixin for Tracer: append, query, save."""

    def __init__(self, args):
        self.tracer = []
        self._df = None
        self.count = 0
        self.args = args
        self._row_annotations = {}

    def append(self, layer_idx, atom0, atom1, pos0, pos1, optype, start_time, end_time, is_moveback, fidelity=None):
        """Append one event row."""
        fidelity = fidelity or {}
        display_optype = 'Local Ops' if optype in {'Local CNOT', 'Local SWAP'} else optype
        self.tracer.append([self.count, layer_idx, atom0, atom1, pos0, pos1, optype, start_time, end_time, is_moveback, display_optype, *[fidelity.get(col) for col in TRACER_FIDELITY_COLUMNS]])
        self.count += 1
        self._df = None

    def to_dataframe(self, sort_by_count=True):
        """Build a DataFrame snapshot for the tracer."""
        if self._df is None:
            normalized_rows = []
            for row in self.tracer:
                values = list(row)
                if len(values) < len(TRACER_COLUMNS):
                    values.extend([None] * (len(TRACER_COLUMNS) - len(values)))
                elif len(values) > len(TRACER_COLUMNS):
                    values = values[:len(TRACER_COLUMNS)]
                normalized_rows.append(values)
            self._df = pd.DataFrame(normalized_rows, columns=TRACER_COLUMNS)
            if self._row_annotations:
                annotation_rows = []
                for (count, payload) in sorted(self._row_annotations.items()):
                    row = {'count': int(count)}
                    row.update(payload)
                    annotation_rows.append(row)
                if annotation_rows:
                    annotation_df = pd.DataFrame(annotation_rows)
                    self._df = self._df.drop(columns=[col for col in annotation_df.columns if col != 'count' and col in self._df.columns])
                    self._df = self._df.merge(annotation_df, on='count', how='left')
                    for col in TRACER_COLUMNS:
                        if col not in self._df.columns:
                            self._df[col] = None
                    self._df = self._df[TRACER_COLUMNS]
        if sort_by_count:
            return self._df.sort_values('count').reset_index(drop=True)
        else:
            return self._df

    def clear(self):
        """Clear the tracer buffer."""
        self.tracer = []
        self._df = None
        self.count = 0
        self._row_annotations = {}

    def summary(self):
        """Summary count by operation type."""
        df = self.to_dataframe()
        return df.groupby('optype').size().reset_index(name='count')

    def _k_suffix(self):
        return f'{self.args.K1}-{self.args.K2}'

    def save(self, output_dir=None):
        """Save tracer as JSON and CSV."""
        if output_dir is None:
            raise ValueError('output_dir is required for Tracer.save()')
        os.makedirs(output_dir, exist_ok=True)
        base = f'{output_dir}/Tracer-{self._k_suffix()}'
        df = self.to_dataframe()
        df.to_json(f'{base}.json', orient='records')
        df.to_csv(f'{base}.csv', index=False)
    def annotate_rows(self, annotations):
        if not annotations:
            return
        for count, payload in annotations.items():
            self._row_annotations[int(count)] = dict(payload)
        self._df = None
