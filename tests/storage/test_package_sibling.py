"""Packaging a neighbouring project for email, without its secrets or its data.

These projects were not written to be mailed and nobody had audited them for
it. One holds live Anthropic, Speechmatics, Thymia and Cerebras keys; another
holds a clinical database and a real consultation recording. The packager's
job is to refuse all of it and then *say so inside the archive*, because the
covering note does not survive the journey — the machine it was written on is
the one being deleted.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import package_sibling as ps  # noqa: E402

SECRET_VALUE = "sk-ant-THIS-MUST-NEVER-TRAVEL-0123456789"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project shaped like the real ones: source, a secret, data, junk."""
    root = tmp_path / "someproject"
    (root / "backend").mkdir(parents=True)
    (root / ".venv" / "lib").mkdir(parents=True)

    (root / "README.md").write_text("# someproject\n", encoding="utf-8")
    (root / "backend" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "backend" / ".env").write_text(
        f"ANTHROPIC_API_KEY={SECRET_VALUE}\nALLOWED_ORIGINS=http://localhost\n",
        encoding="utf-8",
    )
    (root / "data.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 2048)
    (root / "consult.wav").write_bytes(b"RIFF" + b"\x00" * 4096)
    (root / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1" + b"\x00" * 64)
    (root / ".venv" / "lib" / "huge.py").write_text("x = 1\n", encoding="utf-8")
    return root


def members(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return zf.namelist()


def contents(archive: Path) -> bytes:
    return archive.read_bytes()


# ------------------------------------------------------------- refusals --

def test_the_secret_value_never_reaches_the_archive(project, tmp_path):
    archive, _ = ps.package(project, tmp_path / "out", only_files=False)

    assert "someproject/backend/.env" not in members(archive)
    assert SECRET_VALUE.encode() not in contents(archive), (
        "a live API key was packaged"
    )


def test_a_template_is_written_with_names_but_no_values(project, tmp_path):
    archive, _ = ps.package(project, tmp_path / "out", only_files=False)

    with zipfile.ZipFile(archive) as zf:
        example = zf.read("someproject/backend/.env.example").decode()

    assert "ANTHROPIC_API_KEY=" in example
    assert "ALLOWED_ORIGINS=" in example
    assert SECRET_VALUE not in example
    # Every key line ends at the '=' — no value survives.
    for line in example.splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.endswith("="), f"a value leaked into the template: {line}"


def test_a_projects_own_example_is_not_overwritten(project, tmp_path):
    """Theirs is authoritative, and a duplicate member makes an invalid zip."""
    (project / "backend" / ".env.example").write_text(
        "# theirs\nANTHROPIC_API_KEY=\n", encoding="utf-8"
    )
    archive, _ = ps.package(project, tmp_path / "out", only_files=False)

    names = members(archive)
    assert names.count("someproject/backend/.env.example") == 1
    with zipfile.ZipFile(archive) as zf:
        assert "# theirs" in zf.read("someproject/backend/.env.example").decode()


def test_data_and_os_junk_are_refused(project, tmp_path):
    archive, report = ps.package(project, tmp_path / "out", only_files=False)
    names = members(archive)

    assert not [n for n in names if n.endswith((".db", ".wav"))]
    assert not [n for n in names if n.endswith(".DS_Store")]
    assert not [n for n in names if "/.venv/" in n]
    assert set(report["excluded"]["data"]) == {"data.db", "consult.wav"}


# ------------------------------------------- the note travels with it --

def test_the_archive_explains_itself(project, tmp_path):
    """The covering note does not survive the journey. The archive must.

    The first version of this tool wrote the explanation into a README beside
    the archives — on the machine being deleted. A recipient unzipped source
    with no record that a `.env` had been removed, no idea the database was
    missing rather than empty, and nothing telling them what to supply.
    """
    archive, _ = ps.package(project, tmp_path / "out", only_files=False)

    assert "someproject/TRANSFER_NOTE.md" in members(archive)
    with zipfile.ZipFile(archive) as zf:
        note = zf.read("someproject/TRANSFER_NOTE.md").decode()

    # Names what went missing, specifically.
    assert "backend/.env" in note
    assert "data.db" in note
    assert "consult.wav" in note
    # Tells them what to do about it, runnably.
    assert "cp backend/.env.example backend/.env" in note
    # And never restates the secret.
    assert SECRET_VALUE not in note


def test_the_note_does_not_warn_about_things_that_were_not_withheld(tmp_path):
    """A clean project must not carry a credentials warning it never earned."""
    clean = tmp_path / "docsonly"
    clean.mkdir()
    (clean / "notes.md").write_text("# notes\n", encoding="utf-8")

    archive, _ = ps.package(clean, tmp_path / "out", only_files=True)
    with zipfile.ZipFile(archive) as zf:
        note = zf.read("docsonly/TRANSFER_NOTE.md").decode()

    assert "you must supply your own" not in note
    assert "Data — withheld" not in note


def test_the_notes_copy_command_resolves_from_the_project_root(project, tmp_path):
    """These are lines somebody pastes, not reads.

    An earlier version emitted `cd backend && cp ...` followed by
    `$EDITOR backend/.env`, which does not resolve after the cd.
    """
    archive, _ = ps.package(project, tmp_path / "out", only_files=False)
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(unpacked)

    root = unpacked / "someproject"
    note = (root / "TRANSFER_NOTE.md").read_text()
    line = next(x for x in note.splitlines() if x.startswith("cp "))
    _, src, dst = line.split()

    assert (root / src).exists(), f"{src} does not exist relative to the root"
    (root / dst).write_bytes((root / src).read_bytes())
    assert (root / dst).exists()


def test_the_packager_never_swallows_samvedna_itself(tmp_path):
    """Packaging the parent directory must not recurse into this project."""
    archive, _ = ps.package(ps.ROOT.parent, tmp_path / "out", only_files=True)
    assert not [n for n in members(archive) if "samvedna/src" in n]
