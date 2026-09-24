from __future__ import annotations

import pathlib

APP = pathlib.Path(__file__).resolve().parents[1]
REPO = APP.parent


def test_release_container_keeps_manylinux2014_but_replaces_static_wheel_python():
    text = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    assert text.startswith("FROM quay.io/pypa/manylinux2014_x86_64:latest")
    assert "/opt/python/cp311-cp311/bin/python" not in text
    assert "ENV PYTHON=/opt/pt-python/bin/python3" in text


def test_standalone_python_download_is_version_and_hash_pinned():
    text = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    assert "PBS_VERSION=3.11.16" in text
    assert "PBS_RELEASE=20260825" in text
    assert "25844eb97cdc72cdc78addaad0969ce3b2133a4de54bfcfa4d57f8a6d095eaab" in text
    assert "sha256sum -c -" in text
    assert "x86_64-unknown-linux-gnu-install_only.tar.gz" in text


def test_container_gates_pyinstaller_shared_library_contract():
    text = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    assert "test -f /opt/pt-python/lib/libpython3.11.so.1.0" in text
    assert "Py_ENABLE_SHARED" in text
    assert "GNU_STACK" in text
    assert "RWE" in text
    assert "portable_shared_python=READY" in text


def test_binary_wheel_policy_is_unchanged():
    text = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    req = (APP / "requirements-portable-build.txt").read_text(encoding="utf-8")
    assert "PIP_ONLY_BINARY=:all:" in text
    assert "Pillow==10.4.0" in req
    assert "numpy==1.26.4" in req
    assert "PyInstaller==6.22.3" in req
