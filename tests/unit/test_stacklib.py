"""The tracing-stack step and the deterministic web gates (stacklib), against the stub toolkit."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from specula import pipelinelib as pl
from specula import stacklib

STUB = Path(__file__).resolve().parents[1] / "fixtures" / "webkit_stub"


class StackCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name).resolve()
        self.toolkit = self.root / "webkit"
        shutil.copytree(STUB, self.toolkit)
        self.work = self.root / "target" / ".specula-output"
        self.work.mkdir(parents=True)
        old = os.environ.get(stacklib.WEBKIT_ENV)
        os.environ[stacklib.WEBKIT_ENV] = str(self.toolkit)
        self.addCleanup(self._restore_env, old)

    @staticmethod
    def _restore_env(old: str | None) -> None:
        if old is None:
            os.environ.pop(stacklib.WEBKIT_ENV, None)
        else:
            os.environ[stacklib.WEBKIT_ENV] = old

    def fixture(self, phase: str) -> None:
        subprocess.run([sys.executable, str(self.toolkit / "fixture.py"), phase, str(self.work)], check=True)

    def replace_tool(self, rel: str, body: str) -> None:
        (self.toolkit / rel).write_text("#!/usr/bin/env python3\nimport sys, json\nfrom pathlib import Path\n" + body)


class TestEnsure(StackCase):
    def test_ensure_records_the_self_tested_stack(self) -> None:
        self.fixture("code_analysis")
        with contextlib.redirect_stdout(io.StringIO()):
            record = stacklib.ensure(self.work)
        state = json.loads(stacklib.state_path(self.work).read_text())
        self.assertEqual(state["run_id"], record["run_id"])
        self.assertTrue(Path(state["out_dir"]).is_relative_to(stacklib.runs_dir(self.work).resolve()))

    def test_missing_config_is_an_error(self) -> None:
        with self.assertRaisesRegex(stacklib.StackError, "missing stack config"):
            stacklib.ensure(self.work)

    def test_failed_self_test_is_an_error(self) -> None:
        self.fixture("code_analysis")
        self.replace_tool(
            "stack/wkstack.py",
            "cmd = sys.argv[1]\n"
            "if cmd == 'status':\n"
            "    print(json.dumps({'running': True, 'selftest': {'ok': False, 'checks': [\n"
            "        {'name': 'pgproxy: probe SQL attributed', 'ok': False}]}}))\n"
            "sys.exit(1 if cmd == 'ensure' else 0)\n",
        )
        with self.assertRaisesRegex(stacklib.StackError, "pgproxy: probe SQL attributed"):
            stacklib.ensure(self.work)
        self.assertFalse(stacklib.state_path(self.work).exists())

    def test_missing_toolkit_is_an_error(self) -> None:
        os.environ[stacklib.WEBKIT_ENV] = str(self.root / "nowhere")
        self.fixture_dir_config()
        with self.assertRaisesRegex(stacklib.StackError, "web toolkit not found"):
            stacklib.ensure(self.work)

    def fixture_dir_config(self) -> None:
        stacklib.config_path(self.work).parent.mkdir(parents=True, exist_ok=True)
        stacklib.config_path(self.work).write_text("[app]\n")


class TestGates(StackCase):
    def setUp(self) -> None:
        super().setUp()
        for phase in ("code_analysis", "spec_generation", "harness_generation"):
            self.fixture(phase)

    def test_fixture_workspace_passes(self) -> None:
        self.assertEqual(stacklib.library_problems(self.work), [])
        self.assertEqual(stacklib.trace_problems(self.work), [])

    def test_edited_library_module_fails(self) -> None:
        with (self.work / "spec" / "WebDB.tla").open("a") as f:
            f.write("\\* edited\n")
        problems = stacklib.library_problems(self.work)
        self.assertEqual(len(problems), 1)
        self.assertIn("read-only", problems[0])

    def test_missing_library_module_fails(self) -> None:
        (self.work / "spec" / "WebTrace.tla").unlink()
        self.assertIn("spec/WebTrace.tla missing", stacklib.library_problems(self.work)[0])

    def test_trace_that_differs_from_its_rebuild_fails(self) -> None:
        # A runner that rebuilds what the recordings say, so an edited trace no longer matches.
        self.replace_tool(
            "workload/runner.py",
            "args = sys.argv\n"
            "traces, out = Path(args[args.index('--traces') + 1]), Path(args[args.index('--out') + 1])\n"
            "for stem in json.loads((traces / 'windows.json').read_text()):\n"
            "    (out / f'{stem}.ndjson').write_text('{\"event\":\"fixture\"}\\n')\n",
        )
        self.assertEqual(stacklib.trace_problems(self.work), [])
        (self.work / "traces" / "fixture.ndjson").write_text('{"event":"edited"}\n')
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("differs from its rebuild" in p for p in problems), problems)

    def test_config_changed_after_recording_fails(self) -> None:
        with stacklib.config_path(self.work).open("a") as f:
            f.write("# changed\n")
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("older stack.toml" in p for p in problems), problems)

    def test_trace_without_window_fails(self) -> None:
        (self.work / "traces" / "extra.ndjson").write_text("{}\n")
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("extra.ndjson: no window" in p for p in problems), problems)

    def test_recording_outside_the_target_stack_fails(self) -> None:
        windows = json.loads((self.work / "traces" / "windows.json").read_text())
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        windows["fixture"]["run_dir"] = str(elsewhere)
        (self.work / "traces" / "windows.json").write_text(json.dumps(windows))
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("outside this target's stack" in p for p in problems), problems)

    def test_failed_self_test_of_the_recording_stack_fails(self) -> None:
        run = Path(json.loads((self.work / "traces" / "windows.json").read_text())["fixture"]["run_dir"])
        st = json.loads((run / "selftest.json").read_text())
        (run / "selftest.json").write_text(json.dumps({**st, "ok": False}))
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("failed the self-test" in p for p in problems), problems)

    def test_failed_coverage_gate_fails(self) -> None:
        self.replace_tool("tracecheck/coverage.py", "print('coverage gate: FAIL')\nsys.exit(1)\n")
        problems = stacklib.trace_problems(self.work)
        self.assertTrue(any("coverage gate failed" in p for p in problems), problems)

    def test_missing_harness_files_fail(self) -> None:
        (self.work / "harness" / "mapping.toml").unlink()
        self.assertIn("harness/mapping.toml missing", stacklib.trace_problems(self.work))


class TestPromptSection(StackCase):
    def test_section_names_the_toolkit_and_stack_commands(self) -> None:
        text = stacklib.prompt_section(self.work)
        self.assertIn(str(self.toolkit), text)
        self.assertIn(f"--config {stacklib.config_path(self.work)} --runs-dir {stacklib.runs_dir(self.work)}", text)
        self.assertIn("never edit them", text)

    def test_no_section_without_a_toolkit(self) -> None:
        os.environ[stacklib.WEBKIT_ENV] = str(self.root / "nowhere")
        self.assertEqual(stacklib.prompt_section(self.work), "")


class TestStackStep(StackCase):
    def pipeline(self, *argv: str) -> pl.Pipeline:
        p = pl.Pipeline()
        p.get_work_dir = lambda _name: str(self.work)  # type: ignore[method-assign]
        p.skip_stack = "--skip-stack" in argv
        p.dry_run = "--dry-run" in argv
        return p

    def run_quiet(self, fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_ensure_stacks_runs_the_self_test(self) -> None:
        self.fixture("code_analysis")
        out = self.run_quiet(self.pipeline().ensure_stacks, ["t"], "Phase 2")
        self.assertIn("self-tested", out)
        self.assertTrue(stacklib.state_path(self.work).is_file())

    def test_a_failing_stack_stops_the_pipeline(self) -> None:
        with self.assertRaises(SystemExit) as exit_:
            self.run_quiet(self.pipeline().ensure_stacks, ["t"], "Phase 2")
        self.assertEqual(exit_.exception.code, 1)

    def test_missing_config_is_tolerated_only_when_allowed(self) -> None:
        out = self.run_quiet(self.pipeline().ensure_stacks, ["t"], "Phase 2", allow_missing=True)
        self.assertIn("no stack config yet", out)

    def test_skip_stack_runs_nothing(self) -> None:
        out = self.run_quiet(self.pipeline("--skip-stack").ensure_stacks, ["t"], "Phase 2")
        self.assertIn("--skip-stack", out)
        self.assertFalse(stacklib.state_path(self.work).exists())

    def test_dry_run_only_logs(self) -> None:
        out = self.run_quiet(self.pipeline("--dry-run").ensure_stacks, ["t"], "Phase 2")
        self.assertIn("[DRY RUN] wkstack ensure", out)

    def test_stop_stacks_brings_the_stack_down_unless_kept(self) -> None:
        self.fixture("code_analysis")
        self.run_quiet(self.pipeline().ensure_stacks, ["t"], "Phase 2")
        state_file = stacklib.runs_dir(self.work) / ".current-stub.json"
        self.assertTrue(state_file.exists())
        kept = self.pipeline()
        kept.keep_stack = True
        self.run_quiet(kept.stop_stacks, ["t"])
        self.assertTrue(state_file.exists())
        self.run_quiet(self.pipeline().stop_stacks, ["t"])
        self.assertFalse(state_file.exists())


if __name__ == "__main__":
    unittest.main()
