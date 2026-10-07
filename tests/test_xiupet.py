import base64
import subprocess

from scripts import xiupet


def test_windows_uninstall_defers_deletion_until_manager_exits(tmp_path, monkeypatch, capsys):
    project = tmp_path / "Spirit Pet's install"
    project.mkdir()
    shortcut = tmp_path / "xiupet.cmd"
    shortcut.write_text("launcher", encoding="utf-8")
    (project / ".xiupet-command").write_text(str(shortcut), encoding="utf-8")
    calls = []
    monkeypatch.setattr(xiupet, "_IS_WINDOWS", True)
    monkeypatch.setattr(xiupet, "stop", lambda path: calls.append(("stop", path)) or 0)
    monkeypatch.setattr(
        xiupet, "_schedule_windows_removal",
        lambda path, command: calls.append(("schedule", path, command)),
    )
    monkeypatch.setattr(xiupet.shutil, "rmtree", lambda *_: (_ for _ in ()).throw(AssertionError("direct removal")))

    assert xiupet.uninstall(project, yes=True) == 0
    assert calls == [("stop", project), ("schedule", project, shortcut)]
    assert project.is_dir() and shortcut.is_file()
    assert "Uninstall scheduled" in capsys.readouterr().out


def test_windows_removal_command_uses_encoded_escaped_paths(tmp_path, monkeypatch):
    project = tmp_path / "Pet's project"
    shortcut = tmp_path / "xiupet.cmd"
    calls = []
    monkeypatch.setattr(xiupet.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs)))

    xiupet._schedule_windows_removal(project, shortcut)

    command, options = calls[0]
    assert command[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    script = base64.b64decode(command[-1]).decode("utf-16le")
    assert "Start-Sleep -Seconds 2" in script
    assert str(project).replace("'", "''") in script
    assert str(shortcut) in script
    assert options["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
