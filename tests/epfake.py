# Copyright (c) 2022 AllSeeingEyeTolledEweSew
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

from __future__ import annotations

import collections
from collections.abc import Iterable
import email.message
import importlib
import importlib.metadata
import io
import os
import pathlib
import sys
from typing import Any
from typing import Optional
from typing import Union
import uuid


class _FakeDistribution(importlib.metadata.Distribution):
    def __init__(self) -> None:
        self._entry_points: dict[str, list[tuple[str, str]]] = collections.defaultdict(
            list
        )
        # Some amount of metadata is expected. In particular,
        # importlib.metadata de-duplicates distributions by name, for some
        # cases
        self._meta = email.message.Message()
        self._meta["Name"] = uuid.uuid4().hex
        self._meta["Metadata-Version"] = "2.1"
        self._meta["Version"] = "1.0"

    def add_entry_point(self, group: str, name: str, value: str) -> None:
        self._entry_points[group].append((name, value))

    def locate_file(self, path: Union[str, os.PathLike]) -> os.PathLike:
        return pathlib.Path("__DOES_NOT_EXIST__").joinpath(path)

    def read_text(self, filename: str) -> Optional[str]:
        if filename == "entry_points.txt":
            fp = io.StringIO()
            for group, name_values in self._entry_points.items():
                fp.write("[")
                fp.write(group)
                fp.write("]\n")
                for name, value in name_values:
                    fp.write(name)
                    fp.write(" = ")
                    fp.write(value)
                    fp.write("\n")
                fp.write("\n")
            return fp.getvalue()
        if filename == "PKG-INFO":
            return self._meta.as_string()
        return None


_DEFAULT_CTX = importlib.metadata.DistributionFinder.Context()


class _FakeDistributionFinder(importlib.metadata.DistributionFinder):
    def __init__(
        self, distributions: Iterable[importlib.metadata.Distribution]
    ) -> None:
        self._distributions = distributions

    def find_distributions(
        self,
        context: importlib.metadata.DistributionFinder.Context = _DEFAULT_CTX,
    ) -> Iterable[importlib.metadata.Distribution]:
        return self._distributions


class EntryPointFaker:
    def __init__(self) -> None:
        self._dist = _FakeDistribution()
        self._finder = _FakeDistributionFinder([self._dist])
        self._globals: dict[str, Any] = {}
        self._enabled = False

    def enable(self) -> None:
        sys.meta_path.append(self._finder)
        self._enabled = True
        this_module = importlib.import_module(__name__)
        for name, value in self._globals.items():
            setattr(this_module, name, value)

    def disable(self) -> None:
        self._enabled = False
        sys.meta_path.remove(self._finder)
        this_module = importlib.import_module(__name__)
        for name in self._globals:
            delattr(this_module, name)

    def __enter__(self) -> EntryPointFaker:
        self.enable()
        return self

    def __exit__(self, _type: Any, _value: Any, _tb: Any) -> None:
        self.disable()

    def add(self, name: str, value: Any, group: Any) -> None:
        if not isinstance(value, str):
            qualname = value.__qualname__
            # If the value isn't global, adopt it as a global of this module
            if "." in qualname:
                global_name = uuid.uuid4().hex
                self._globals[global_name] = value
                value = f"{__name__}:{global_name}"
                if self._enabled:
                    this_module = importlib.import_module(__name__)
                    setattr(this_module, global_name, self._globals[global_name])
            else:
                value = f"{value.__module__}:{qualname}"
        if not isinstance(group, str):
            group = f"{group.__module__}.{group.__qualname__}"
        self._dist.add_entry_point(group, name, value)
