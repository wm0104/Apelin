"""Exercise the workflow's actual shell against disposable local Git remotes.

Standard library only; TMPDIR must point outside the checkout, inside this project.
These tests do not build with Xcode or execute GitHub Actions.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
TARGET = "build/apelin-fila-optional"
REPO_URL = "https://github.com/wm0104/Apelin.git"
UPSTREAM_URL = "https://github.com/owngoal-dev/Apelin.git"


def script(step_id):
    text = WORKFLOW.read_text()
    match = re.search(
        rf"^        id: {step_id}\n.*?^        run: \|\n((?:          [^\n]*\n|\n)+)",
        text, re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing executable step: {step_id}")
    return textwrap.dedent(match.group(1))


def run(*args, cwd, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class WorkflowContractTests(unittest.TestCase):
    def test_manual_single_job_and_single_artifact(self):
        text = WORKFLOW.read_text()
        self.assertRegex(text, r"on:\n  workflow_dispatch:\s*\n")
        self.assertNotRegex(text, r"(?m)^  (push|pull_request):")
        self.assertEqual(re.findall(r"(?m)^  ([\w-]+):\n", text.split("jobs:\n")[1]), ["sync-build"])
        for guard in ("github.event_name == 'workflow_dispatch'",
                      "github.repository == 'wm0104/Apelin'",
                      "github.ref == 'refs/heads/build/apelin-fila-optional'"):
            self.assertIn(guard, text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("group: apelin-sync-build-apelin-fila-optional", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("DISPATCH_SHA: ${{ github.sha }}", text)
        self.assertEqual(text.count("actions/upload-artifact@v4"), 1)
        self.assertIn("path: ${{ steps.package.outputs.deb }}", text)
        self.assertIn("name: apelin-arm64e-${{ github.run_id }}", text)
        self.assertIn("overwrite: true", text)
        self.assertIn('>> "$GITHUB_STEP_SUMMARY"', text)
        packaging_tests = "python3 -B -m unittest discover -s Tests/Packaging -p 'test_*.py' -v"
        self.assertIn(packaging_tests, text)
        self.assertLess(text.index("Install packaging dependencies"), text.index(packaging_tests))
        self.assertLess(text.index(packaging_tests), text.index("make deb FLAVOR=roothide"))
        self.assertIn("if-no-files-found: error", text)
        self.assertNotIn("make deb-all", text)
        self.assertNotIn("Archive dSYMs", text)
        self.assertIn("make harness SWIFTPM_SCRATCH=", text)
        self.assertIn("make old-runtime", text)
        self.assertIn("make deb FLAVOR=roothide CONFIGURATION=Release SKIP_HARNESS=1", text)
        self.assertIn("--control Packaging/DEBIAN/control", text)
        self.assertIn('--deb "$deb"', text)
        self.assertLess(text.index("id: package"), text.index("id: publish"))
        self.assertLess(text.index("id: publish"), text.index("actions/upload-artifact@v4"))

    def test_all_inline_shell_is_valid_bash(self):
        text = WORKFLOW.read_text()
        blocks = re.findall(r"^        run: \|\n((?:          .*\n|\n)+)", text, re.MULTILINE)
        self.assertGreaterEqual(len(blocks), 5)
        for block in blocks:
            result = subprocess.run(["bash", "-n"], input=textwrap.dedent(block),
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class SyncBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="workflow-git-"))
        # iOS-mounted folders do not support Python's fd-based rmtree reliably.
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", 'fixture="$1"; rm -rf -- "${fixture:?}"',
             "cleanup", str(self.directory)], check=True))
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=str(self.directory / "gitconfig"),
                        GIT_TERMINAL_PROMPT="0")
        self.origin = self.directory / "optional.git"
        self.upstream = self.directory / "upstream.git"
        self.seed = self.directory / "seed"
        self.work = self.directory / "work"
        self.git("init", "--bare", str(self.origin))
        self.git("init", "--bare", str(self.upstream))
        self.git("init", "-b", "main", str(self.seed))
        self.git("config", "user.name", "Upstream Author", cwd=self.seed)
        self.git("config", "user.email", "upstream@example.invalid", cwd=self.seed)
        (self.seed / "shared.txt").write_text("base\n")
        self.commit(self.seed, "initial")
        self.git("push", str(self.upstream), "HEAD:refs/heads/main", cwd=self.seed)
        self.git("push", str(self.origin), f"HEAD:refs/heads/{TARGET}", cwd=self.seed)
        self.git("clone", "--branch", TARGET, str(self.origin), str(self.work))
        self.base = self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip()
        # URL rewriting is only in the disposable test environment. Production
        # shell retains its fixed HTTPS URLs and has no local-remote override.
        self.env.update({
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": f"url.{self.origin}.insteadOf",
            "GIT_CONFIG_VALUE_0": REPO_URL,
            "GIT_CONFIG_KEY_1": f"url.{self.upstream}.insteadOf",
            "GIT_CONFIG_VALUE_1": UPSTREAM_URL,
            "GITHUB_OUTPUT": str(self.directory / "outputs"),
            "GITHUB_STEP_SUMMARY": str(self.directory / "summary"),
            "DISPATCH_SHA": self.base,
        })

    def git(self, *args, cwd=None, check=True):
        return run("git", *args, cwd=cwd or self.directory, env=self.env, check=check)

    def commit(self, directory, message):
        # Only disposable fixtures are staged/committed, never the real checkout.
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "add", ".", cwd=directory)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", message, cwd=directory)

    def shell(self, step):
        return run("bash", "-euo", "pipefail", "-c", script(step),
                   cwd=self.work, env=self.env, check=False)

    def sync(self):
        result = self.shell("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        self.env.update(BASE_SHA=values["base"], BUILD_SHA=values["head"])
        return values

    def remote_head(self):
        return self.git("rev-parse", f"refs/heads/{TARGET}", cwd=self.origin).stdout.strip()

    def upstream_change(self, filename="upstream.txt", contents="new\n"):
        (self.seed / filename).write_text(contents)
        self.commit(self.seed, "upstream update")
        head = self.git("rev-parse", "HEAD", cwd=self.seed).stdout.strip()
        self.git("push", str(self.upstream), "HEAD:refs/heads/main", cwd=self.seed)
        return head

    def test_no_update_keeps_head_and_pushes_noop(self):
        values = self.sync()
        self.assertEqual(values["head"], self.base)
        result = self.shell("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_head(), self.base)

    def test_clean_merge_preserves_parents_and_authorship(self):
        upstream = self.upstream_change()
        values = self.sync()
        parents = self.git("rev-list", "--parents", "-n", "1", "HEAD", cwd=self.work).stdout.split()
        self.assertEqual(parents[1:], [self.base, upstream])
        identity = self.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", "HEAD", cwd=self.work).stdout.strip()
        self.assertEqual(identity, "Codex <noreply@openai.com>|Codex <noreply@openai.com>")
        self.assertEqual(self.git("show", "-s", "--format=%an", upstream, cwd=self.work).stdout.strip(), "Fixture")
        result = self.shell("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_head(), values["head"])

    def test_conflict_stops_without_changing_remote(self):
        self.upstream_change("shared.txt", "upstream\n")
        (self.work / "shared.txt").write_text("optional\n")
        self.commit(self.work, "optional update")
        self.git("push", str(self.origin), f"HEAD:refs/heads/{TARGET}", cwd=self.work)
        base = self.remote_head()
        self.env["DISPATCH_SHA"] = base
        result = self.shell("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_head(), base)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip(), base)
        self.assertTrue((self.work / ".git/MERGE_HEAD").exists())

    def test_remote_advance_rejects_even_fast_forward_update(self):
        self.upstream_change()
        self.sync()
        # Simulate another run advancing to an ancestor of our merge: even
        # though a normal push could fast-forward, the base guard must refuse.
        upstream = self.git("rev-parse", "HEAD^2", cwd=self.work).stdout.strip()
        self.git("push", str(self.origin), f"{upstream}:refs/heads/{TARGET}", cwd=self.work)
        result = self.shell("publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since sync began", result.stderr)
        self.assertEqual(self.remote_head(), upstream)

    def test_checkout_behind_initial_remote_stops(self):
        self.upstream_change()
        self.git("push", str(self.origin), f"HEAD:refs/heads/{TARGET}", cwd=self.seed)
        result = self.shell("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed during checkout", result.stderr)

    def test_queued_dispatch_rejects_a_newer_checkout_and_remote(self):
        dispatched = self.base
        advanced = self.upstream_change()
        self.git("push", str(self.origin), f"HEAD:refs/heads/{TARGET}", cwd=self.seed)
        self.git("fetch", str(self.origin), f"refs/heads/{TARGET}", cwd=self.work)
        self.git("merge", "--ff-only", "FETCH_HEAD", cwd=self.work)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.work).stdout.strip(), advanced)
        self.env["DISPATCH_SHA"] = dispatched
        result = self.shell("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed since dispatch", result.stderr)
        self.assertEqual(self.remote_head(), advanced)
        self.assertFalse(Path(self.env["GITHUB_OUTPUT"]).exists())

    def test_changed_build_head_is_not_pushed(self):
        self.sync()
        (self.work / "after-build.txt").write_text("not validated\n")
        self.commit(self.work, "unexpected commit")
        result = self.shell("publish")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_head(), self.base)


class PackageOutputTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="workflow-package-"))
        self.addCleanup(lambda: subprocess.run(
            ["bash", "-c", 'fixture="$1"; rm -rf -- "${fixture:?}"',
             "cleanup", str(self.directory)], check=True))
        (self.directory / "build/Packages").mkdir(parents=True)
        (self.directory / "bin").mkdir()
        make = self.directory / "bin/make"
        make.write_text("#!/bin/sh\nprintf '0.4.9\\n'\n")
        make.chmod(0o755)
        (self.directory / "Scripts").mkdir()
        # Stub only the separate package verifier: these tests exercise the
        # output-set guard, not DEB metadata or signatures (tested separately).
        (self.directory / "Scripts/verify-optional-deb.py").write_text(
            "import sys\nassert sys.argv[1] == '--deb'\n")
        self.env = dict(os.environ, PATH=f"{self.directory / 'bin'}:{os.environ['PATH']}",
                        GITHUB_OUTPUT=str(self.directory / "output"))
        self.deb = self.directory / "build/Packages/wiki.qaq.apelin_0.4.9_iphoneos-arm64e.deb"

    def package(self):
        return run("bash", "-euo", "pipefail", "-c", script("package"),
                   cwd=self.directory, env=self.env, check=False)

    def test_exactly_one_correct_regular_file_is_selected(self):
        self.deb.write_bytes(b"fixture, not a native DEB")
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory / "output").read_text(),
                         "deb=build/Packages/wiki.qaq.apelin_0.4.9_iphoneos-arm64e.deb\n")
        self.assertEqual(len(list(self.deb.parent.iterdir())), 1)

    def test_empty_output_is_rejected(self):
        self.assertNotEqual(self.package().returncode, 0)

    def test_extra_hidden_file_is_rejected(self):
        self.deb.write_bytes(b"fixture")
        (self.deb.parent / ".unexpected").write_text("extra")
        self.assertNotEqual(self.package().returncode, 0)

    def test_wrong_architecture_is_rejected(self):
        (self.deb.parent / "wiki.qaq.apelin_0.4.9_iphoneos-arm64.deb").write_bytes(b"fixture")
        self.assertNotEqual(self.package().returncode, 0)

    def test_directory_is_rejected(self):
        self.deb.mkdir()
        self.assertNotEqual(self.package().returncode, 0)

    def test_symlink_is_rejected(self):
        target = self.directory / "outside.deb"
        target.write_bytes(b"fixture")
        self.deb.symlink_to(target)
        self.assertNotEqual(self.package().returncode, 0)


if __name__ == "__main__":
    unittest.main()
