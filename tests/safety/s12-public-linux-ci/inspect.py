"""Read-only archive inspection. Never imports or executes packaged code."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

EXPECTED = 'a9d2251edcb6b96695eb15511f4bf36e55e9365b53de036c1c53637f52214083'
PREFIX = 'S12-PUBLIC-LINUX-HARNESS-R1-20261014/'
PINS = {
    'scripts/linux-supervisor-regressions.py': '05b0342f8b77817415a06d09b2db334979b62ed56414335278fb75a59adece00',
    'scripts/common.py': 'd8943a4dfb4af0a8033a2cb8d8ae9275812ab3e1b1bd4e33c37a92ea1c967373',
    'scripts/owned-supervisor.py': '307bf48b8da626b23606865d6618994ad383de37f938075718cd3928bb54986a',
    'operator-copy/deploy/s10a/s12_recovery.py': 'fd50b2990e4df84e30be9553eed1e297e00a652554eb582aa2ada0e371997984',
}

def require(ok):
    if not ok:
        raise ValueError('STATIC_ARCHIVE_INSPECTION_FAILED')

def main():
    require(len(sys.argv) == 2)
    archive = Path(sys.argv[1])
    require(archive.stat().st_size == 16137)
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == EXPECTED)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        require(len(members) == 9)
        require(len({m.name for m in members}) == 9)
        require(all(m.isfile() and m.name.startswith(PREFIX)
                    and '..' not in PurePosixPath(m.name).parts
                    and 0 <= m.size <= 100000 for m in members))
        data = {m.name[len(PREFIX):]: tar.extractfile(m).read() for m in members}
    require(set(data) == set(PINS) | {'manifest.json', 'planned-inputs/bindings.json',
                                   'README.md', 'SOURCE-LOCKS.json', 'SHA256SUMS'})
    rows = data['SHA256SUMS'].decode().splitlines()
    require(len(rows) == 8)
    pairs = [row.split('  ', 1) for row in rows]
    require(all(len(pair) == 2 for pair in pairs))
    require(len({name for _, name in pairs}) == 8)
    require({name for _, name in pairs} == set(data) - {'SHA256SUMS'})
    for digest, name in pairs:
        require(hashlib.sha256(data[name]).hexdigest() == digest)
    for name, digest in PINS.items():
        require(hashlib.sha256(data[name]).hexdigest() == digest)
        ast.parse(data[name])
    require(data['manifest.json'] == b'{"paths":{}}\n')
    require(data['planned-inputs/bindings.json'] == b'{"approved":false}\n')
    locks = json.loads(data['SOURCE-LOCKS.json'])
    require(locks['original_code_sha256'] == PINS)
    require(locks['code_or_guards_changed'] is False)
    print(json.dumps({'archive_static_verified': True, 'sha256': EXPECTED,
                      'files': 9, 'checksum_entries': 8,
                      'linux_harness_status': 'NOT RUN'}))

if __name__ == '__main__':
    main()
