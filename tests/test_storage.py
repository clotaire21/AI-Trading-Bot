from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class StateStoreTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git/bash required")
    def test_separate_state_branch_roundtrip_without_modifying_source(self):
        script = str(Path("tools/state_branch.sh").resolve())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args, cwd=None):
                return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout
            git("init", "--bare", str(root / "remote.git"))
            source = root / "source"
            git("init", "-b", "main", str(source))
            git("config", "user.name", "Test", cwd=source)
            git("config", "user.email", "test@example.invalid", cwd=source)
            (source / "README.md").write_text("source\n")
            git("add", ".", cwd=source)
            git("commit", "-m", "source", cwd=source)
            git("remote", "add", "origin", str(root / "remote.git"), cwd=source)
            git("push", "origin", "main", cwd=source)
            before = git("rev-parse", "HEAD", cwd=source)
            def state(action, cwd):
                subprocess.run(["bash", script, action], cwd=cwd, check=True, capture_output=True, text=True)
            state("prepare", source)
            (source / "runtime-state/runtime/state.json").write_text('{"paper": true}')
            state("save", source)
            self.assertEqual(git("rev-parse", "HEAD", cwd=source), before)
            self.assertEqual((source / "README.md").read_text(), "source\n")
            second = root / "second"
            git("clone", "--branch", "main", str(root / "remote.git"), str(second))
            state("prepare", second)
            self.assertEqual((second / "runtime-state/runtime/state.json").read_text(), '{"paper": true}')
