# Copyright (c) 2020 AllSeeingEyeTolledEweSew
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

import abc
import contextlib
import json
import os
import pathlib
from typing import Any
from typing import Callable
from typing import ContextManager
from typing import Iterator
from typing import MutableMapping
from typing import Optional
from typing import Type
from typing import TypeVar
from typing import Union

# Design notes:

# Config is stored as json. This is so external programs can easily manipulate
# the config if necessary.

# Config is a dict of json-compatible python primitives. I tried using a
# dataclass to map it, but as of 3.8, translating between dataclasses and json
# is still quite cumbersome. We either need ad-hoc code in several different
# places, or complex metaclass code. All type conversion also needs to be
# centralized, which impacts modularity.

# Config updates are "staged" such that e.g. when the HTTP port is changed, we:
#  - bind a socket to the new port
#  - attempt any other config changes
#  - if other changes fail, close the new socket
#  - if other changes succeed, start the server on the new port and close
#    the old server.
# This makes certain changes impossible, such as changing the binding from
# 0.0.0.0:21 to 127.0.0.1:21, as the old server breaks the new binding. However
# I notice that nginx has the same limitation, so it's probably good enough.

# In Python we prefer to work with "disposable" objects which are configured
# only once, and re-created as necessary. However, tvaf's top-level App code
# doesn't know the right life cycle for its various components (for example,
# should the App re-create the server for a particular config change?).
# So we design our components to be long-lived objects which can be
# re-configured over their lifetimes.


class Error(Exception):

    pass


class InvalidConfigError(Error):

    pass


_T = TypeVar("_T")


class Config(dict, MutableMapping[str, Any]):
    @classmethod
    def from_disk(cls: Type["_C"], path: Union[str, os.PathLike]) -> "_C":
        path = pathlib.Path(path)
        with path.open() as fp:
            try:
                data = json.load(fp)
            except json.JSONDecodeError as exc:
                raise InvalidConfigError(str(exc)) from exc
        return cls(data)

    def write_to_disk(self, path: Union[str, os.PathLike]) -> None:
        path = pathlib.Path(path)
        with path.open(mode="w") as fp:
            json.dump(self, fp, sort_keys=True, indent=4)

    def _get(self, key: str, type_: Type[_T]) -> Optional[_T]:
        value = self.get(key)
        if key in self and not isinstance(value, type_):
            raise InvalidConfigError(f'"{key}": {value!r} is not a {type_}')
        return value

    def _require(self, key: str, type_: Type[_T]) -> _T:
        value = self._get(key, type_)
        if value is None:
            raise InvalidConfigError(f'"{key}": missing')
        return value

    def get_int(self, key: str) -> Optional[int]:
        return self._get(key, int)

    def get_str(self, key: str) -> Optional[str]:
        return self._get(key, str)

    def get_bool(self, key: str) -> Optional[bool]:
        return self._get(key, bool)

    def require_int(self, key: str) -> int:
        return self._require(key, int)

    def require_str(self, key: str) -> str:
        return self._require(key, str)

    def require_bool(self, key: str) -> bool:
        return self._require(key, bool)


_C = TypeVar("_C", bound=Config)


class HasConfig(abc.ABC):
    @abc.abstractmethod
    @contextlib.contextmanager
    def stage_config(self, config: Config) -> Iterator[None]:
        yield

    def set_config(self, config: Config) -> None:
        with self.stage_config(config):
            pass


def set_config(config: Config, *stages: Callable[[Config], ContextManager]):
    with contextlib.ExitStack() as stack:
        for stage in stages:
            stack.enter_context(stage(config))
