"""The test drive is the ordering round; CI must run it, not just ship it.

A walkthrough script nobody executes rots into documentation of a product
that used to work. This runs the real thing and fails the build when the
round breaks.
"""
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "test_drive.py"


def _run(env_extra=None, tmp=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp)}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT)],
                          capture_output=True, text=True, env=env,
                          cwd=str(REPO))


def test_the_whole_ordering_round_passes(tmp_path):
    """Sheet → Send → plan → override → confirm → outputs → history."""
    proc = _run(tmp=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checks passed" in proc.stdout


def test_it_runs_without_an_api_key(tmp_path):
    """Anyone can take the test drive before any credential exists."""
    proc = _run(tmp=tmp_path)
    assert "GOOGLE_API_KEY" not in str(proc.stdout)
    assert proc.returncode == 0


def test_every_step_of_the_round_is_reported(tmp_path):
    """The output is the deliverable — a person reads it to decide whether
    the build is demo-ready. Losing a step silently is the failure mode."""
    proc = _run(tmp=tmp_path)
    for step in ("prefilled", "hits Send", "WHY that vendor",
                 "rules actually bind", "Savings are honest",
                 "overrides a line", "does not send it",
                 "however they like", "still there tomorrow"):
        assert step in proc.stdout, f"step missing from output: {step}"


def test_it_fails_loudly_when_the_round_breaks(tmp_path, monkeypatch):
    """A green suite that cannot go red proves nothing. Break the rule
    engine's exclusion handling and the drive must fail, not pass."""
    broken = tmp_path / "repo"
    subprocess.run(["cp", "-R", str(REPO), str(broken)], check=True,
                   capture_output=True)
    rules = broken / "core" / "rules.py"
    src = rules.read_text()
    # make every exclusion advisory — a manager's "never buy from X" stops
    # binding, which is exactly the bug this fixture caught for real
    old = 'target = (_condition(rule) or {}).get("vendor")'
    assert old in src
    rules.write_text(src.replace(old, 'target = None', 1))

    proc = subprocess.run([sys.executable, str(broken / "scripts" / "test_drive.py")],
                          capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                          cwd=str(broken))
    assert proc.returncode != 0, "the test drive passed on a broken rule engine"
    assert "checks failed" in proc.stdout
