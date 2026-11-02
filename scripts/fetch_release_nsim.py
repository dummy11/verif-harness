#!/usr/bin/env python3
"""Fetch exactly the NSIM wheel and installer in this release's manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    directory = parser.parse_args().output
    directory.mkdir(parents=True, exist_ok=True)
    nsim = json.loads((Path(__file__).resolve().parents[1] / 'release.json').read_text())['nsim']
    for name, url, expected in ((nsim['wheel'], nsim['wheel_url'], nsim['wheel_sha256']),
                                ('nsim-install.py', nsim['installer_url'], nsim['installer_sha256'])):
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit(f'Release checksum mismatch: {name}')
        target = directory / name
        if target.exists() and target.read_bytes() != data:
            raise SystemExit(f'Refusing to replace {name}')
        target.write_bytes(data)
    print('Pinned NSIM artifacts verified')


if __name__ == '__main__':
    main()
