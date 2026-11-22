#!/usr/bin/env python3
"""Keep Irisin/Fila optional and verify the single roothide package we ship."""
import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPTIONAL = re.compile(r'(?<![a-z0-9+.-])wiki\.qaq\.(?:irisin|fila)(?![a-z0-9+.-])')


def fields(text):
    result = {}
    key = None
    for line in text.splitlines():
        if not line:
            continue
        if line[0].isspace() and key:
            result[key] += ' ' + line.strip()
            continue
        key, separator, value = line.partition(':')
        key = key.lower()
        if not separator or key in result:
            raise ValueError('malformed or duplicate control field: ' + key)
        result[key] = value.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--control', type=pathlib.Path)
    source.add_argument('--deb', type=pathlib.Path)
    args = parser.parse_args()
    text = subprocess.check_output(['dpkg-deb', '--field', str(args.deb)], text=True) if args.deb else args.control.read_text()
    control = fields(text)
    if control.get('package') != 'wiki.qaq.apelin':
        raise ValueError('Package must be wiki.qaq.apelin')
    for key in ('depends', 'pre-depends'):
        if OPTIONAL.search(control.get(key, '')):
            raise ValueError('Irisin and Fila must not occur in ' + key)
    if args.deb:
        config = (ROOT / 'Configuration/Version.xcconfig').read_text()
        version = re.search(r'^MARKETING_VERSION\s*=\s*(\S+)', config, re.M)
        if not version or control.get('version') != version[1]:
            raise ValueError('Version must match Configuration/Version.xcconfig')
        if control.get('architecture') != 'iphoneos-arm64e':
            raise ValueError('Architecture must be iphoneos-arm64e')
    print('Verified optional Irisin/Fila dependencies' + (' and arm64e DEB identity/version' if args.deb else ' in control template'))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('error: ' + str(error), file=sys.stderr)
        sys.exit(1)
