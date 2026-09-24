from __future__ import annotations

import pathlib

APP = pathlib.Path(__file__).resolve().parents[1]
REPO = APP.parent


def test_release_requirements_pin_manylinux2014_wheel_matrix():
    req = (APP / "requirements-portable-build.txt").read_text(encoding="utf-8")
    assert "PyInstaller==6.22.3" in req
    assert "Pillow==10.4.0" in req
    assert "numpy==1.26.4" in req
    assert ">=" not in "\n".join(line for line in req.splitlines() if line and not line.startswith("#"))


def test_container_forbids_source_build_fallback_and_uses_shared_python():
    text = (REPO / "Containerfile.portable").read_text(encoding="utf-8")
    assert "manylinux2014_x86_64" in text
    assert "python-build-standalone" in text
    assert "PBS_VERSION=3.11.16" in text
    assert "PBS_RELEASE=20260825" in text
    assert "PBS_SHA256=25844eb97cdc72cdc78addaad0969ce3b2133a4de54bfcfa4d57f8a6d095eaab" in text
    assert "ENV PYTHON=/opt/pt-python/bin/python3" in text
    assert "libpython3.11.so.1.0" in text
    assert "Py_ENABLE_SHARED" in text
    assert "portable_shared_python=READY" in text
    assert "PIP_ONLY_BINARY=:all:" in text
    assert "pip install --upgrade pip" not in text
    assert "portable_binary_wheels=READY" in text


def test_host_build_is_dev_only_and_uses_binary_wheels():
    text = (APP / "build_portable_linux.sh").read_text(encoding="utf-8")
    assert "HOST_BUILD_USES_HOST_GLIBC" in text
    assert "HOST_PYTHON_WHEEL_MATRIX_UNSUPPORTED" in text
    assert "--only-binary=:all:" in text
    assert "build_portable_container.sh" in text


def test_container_output_uses_current_portable_image_and_single_file_path():
    text = (REPO / "build_portable_container.sh").read_text(encoding="utf-8")
    assert 'IMAGE="pt-asset-tool-portable:v10.4"' in text
    assert "dist-portable/pt-asset-tool" in text
    assert "python-build-standalone-3.11.16+20260825" in text
