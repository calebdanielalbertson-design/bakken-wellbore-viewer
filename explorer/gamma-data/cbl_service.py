"""Conventional cement-bond amplitude on observed VERT geometry, in raw mV.

Requires cbl-catalog.json beside this module and the existing survey index.
Zero amplitude is preserved. No bond quality or cement integrity is inferred.
"""
from pathlib import Path
import json
import numpy as np
import gamma_service as gamma

class CBLStore(gamma.GammaStore):
    def __init__(self):
        self.catalog = json.loads((Path(__file__).resolve().parent / 'cbl-catalog.json').read_text(encoding='utf8'))
        self.index = np.load(gamma.BASE / 'survey-index.npy', mmap_mode='r')
        self.records = gamma.dbf_rows()
        self.cache = {}

    def _read_curve(self, source):
        d, values, stats, flags = super()._read_curve(source, mask_zero_flatlines=False)
        stats['validZeroSamples'] = int(np.count_nonzero(np.isfinite(values) & (values == 0)))
        flags = [flag.replace('gamma', 'CBL amplitude') for flag in flags]
        flags.append('Raw amplitude in mV; no cement-bond quality or integrity classification applied')
        return d, values, stats, flags

    def get_well(self, permit, source_id=None, step=5):
        try:
            result = super().get_well(permit, source_id=source_id, step=step)
        except ValueError as exc:
            raise ValueError(str(exc).replace('gamma', 'CBL amplitude')) from exc
        result['measurement'] = 'CBL amplitude'
        result['measurementLabel'] = 'CBL amplitude'
        result['measurementKind'] = 'cbl_amplitude'
        result['unit'] = 'mV'
        result['flags'] = [flag.replace('Gamma', 'CBL amplitude').replace('gamma', 'CBL amplitude') for flag in result['flags']]
        result['sampling'] = ('Raw conventional CBL amplitude linearly interpolated at %.0f ft MD spacing; '
                              'valid zero amplitude retained; null intervals break the tube; no bond-quality classification') % result['stats']['displayStepFt']
        result['stats']['validZeroDisplaySamples'] = sum(p[4] == 0 for path in result['paths'] for p in path['points'])
        return result
