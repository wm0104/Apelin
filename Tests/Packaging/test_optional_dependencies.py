#!/usr/bin/env python3
"""Exercise the delivered-package policy through its command-line boundary."""
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
VERIFY = ROOT / 'Scripts/verify-optional-deb.py'
VERSION = re.search(r'^MARKETING_VERSION\s*=\s*(\S+)', (ROOT / 'Configuration/Version.xcconfig').read_text(), re.M)[1]


class OptionalDependenciesTests(unittest.TestCase):
    def run_check(self, text, *, deb=False, succeeds=True):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            control = root / 'DEBIAN/control'
            control.parent.mkdir()
            control.write_text(text)
            if deb:
                package = root.parent / (root.name + '.deb')
                try:
                    subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(root), str(package)], check=True, capture_output=True)
                    result = subprocess.run([sys.executable, str(VERIFY), '--deb', str(package)], capture_output=True, text=True)
                finally:
                    package.unlink(missing_ok=True)
            else:
                result = subprocess.run([sys.executable, str(VERIFY), '--control', str(control)], capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)

    def control(self, **changes):
        fields = {'Package': 'wiki.qaq.apelin', 'Version': VERSION, 'Architecture': 'iphoneos-arm64e', 'Maintainer': 'Test <test@example.invalid>', 'Description': 'Fixture', 'Depends': 'firmware (>= 16.0), uikittools, launchctl', 'Recommends': 'wiki.qaq.apelin.dev.app'}
        fields.update(changes)
        return ''.join(f'{key}: {value}\n' for key, value in fields.items())

    def test_template_accepts_optional_apps(self):
        self.run_check(self.control(Suggests='wiki.qaq.irisin, wiki.qaq.fila'))

    def test_template_rejects_each_hard_dependency(self):
        for field in ('Depends', 'Pre-Depends'):
            for name in ('wiki.qaq.irisin', 'wiki.qaq.fila'):
                with self.subTest(field=field, name=name):
                    self.run_check(self.control(**{field: f'firmware,\n {name}:any (>= 4.7.3) | other'}), succeeds=False)

    def test_similar_names_are_not_the_optional_apps(self):
        self.run_check(self.control(Depends='wiki.qaq.irisin-tools, wiki.qaq.fila-helper'))

    def test_duplicate_fields_are_rejected(self):
        self.run_check(self.control() + 'Depends: wiki.qaq.irisin\n', succeeds=False)

    def test_real_deb_matches_policy(self):
        self.run_check(self.control(), deb=True)

    def test_real_deb_rejects_wrong_identity_version_architecture_and_dependencies(self):
        for changes in ({'Package': 'other'}, {'Version': '0.0.0'}, {'Architecture': 'iphoneos-arm64'}, {'Depends': 'wiki.qaq.irisin (>= 4.7.3)'}, {'Pre-Depends': 'wiki.qaq.fila'}):
            with self.subTest(changes=changes):
                self.run_check(self.control(**changes), deb=True, succeeds=False)


if __name__ == '__main__':
    unittest.main()
