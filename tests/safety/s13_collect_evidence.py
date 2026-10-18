#!/usr/bin/env python3
"""Compact sanitized S13 harness output, preserving individual timing samples/counts.
Run after all harnesses finish: --input-dir DIR --output-dir DIR.
Resource traces are aggregated by endpoint class; their original file SHA is kept.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', required=True, type=Path)
parser.add_argument('--output-dir', required=True, type=Path)
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)
inputs = {
    'node-base.json': 'base-expanded-compact.json', 'node-candidate.json': 'candidate-final.json',
    'network-base.json': 'metadata-network-base.json', 'network-candidate.json': 'metadata-network-candidate-final.json',
    'browser-base.json': 'browser-base-useful.json', 'browser-candidate.json': 'browser-candidate-final.json',
    'editor-base.json': 'editor-base.json', 'editor-candidate.json': 'editor-candidate-final.json',
    'resource-base.json': 'resource-base.json', 'resource-candidate.json': 'resource-candidate-current.json',
    'browser-resource.json': 'browser-resource-final.json',
    'waveform-base.json': 'waveform-base.json', 'waveform-candidate.json': 'waveform-candidate.json',
}

def endpoint(path):
    path = re.sub(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', ':id', path)
    return re.sub(r'/\d+(?=/|$)', '/:number', path)


def compact(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ['resources', 'completeRefreshResources'] and isinstance(item, list):
                groups = {}
                for row in item:
                    kind = endpoint(row['path'])
                    group = groups.setdefault(kind, {'path': kind, 'requests': 0, 'bytes': 0, 'transferBytes': 0, 'sumDurationMs': 0})
                    group['requests'] += 1
                    group['bytes'] += row.get('bytes', 0)
                    group['transferBytes'] += row.get('transferBytes', 0)
                    group['sumDurationMs'] += row.get('durationMs', 0)
                result[key] = list(groups.values())
            else:
                result[key] = compact(item)
        return result
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value

for dest, source in inputs.items():
    raw = (args.input_dir / source).read_bytes()
    data = json.loads(raw)
    assert 'checkpoint' not in data['kind'], f'{source}: incomplete harness'
    if source == 'resource-base.json':
        data['maxReservedPartBytes'] = None
        data['maxSlots'] = None
        data['slotInstrumentation'] = 'NOT_MEASURED on unchanged base'
    data = compact(data)
    data['collection'] = {'inputSha256': hashlib.sha256(raw).hexdigest(),
        'resourceAggregation': 'endpoint class counts/body bytes/transfer bytes/sum durations per original phase; individual phase timings and repository counters preserved. Resource duration sums overlap, not wall-clock.'}
    (args.output_dir / dest).write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
print('S13 evidence collected:', len(inputs), 'files')
