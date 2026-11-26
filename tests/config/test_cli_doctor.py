"""Check that the CLI doctor reports unusable bundled external friends."""

from futurework.cli import main
from futurework.integrations.agent_backends.subprocess_backend import SubprocessBackend


def test_doctor_returns_failure_for_unavailable_backend(tmp_path, monkeypatch, capsys):
    async def unavailable(self):
        return {"ok": False, "error": "configuration invalid"}

    monkeypatch.setattr(SubprocessBackend, "health", unavailable)
    assert main(["--home", str(tmp_path / "home"), "doctor"]) == 1
    output = capsys.readouterr().out
    assert "openclaw (openclaw): unavailable" in output
    assert "configuration invalid" in output
