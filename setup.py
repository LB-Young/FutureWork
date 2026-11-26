"""Discard stale package files before setuptools copies the current source tree."""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class CleanBuildPy(build_py):
    """Prevent deleted built-in Agents or Skills from leaking into later wheels."""

    def run(self) -> None:
        package_dir = Path(self.build_lib) / "futurework"
        if package_dir.is_dir():
            shutil.rmtree(package_dir)
        super().run()


setup(cmdclass={"build_py": CleanBuildPy})
