"""Pytest bootstrap shared by the whole suite.

Several test modules import ``ipv8.keyvault.crypto`` at module load time, which
eagerly loads libnacl/libsodium. On systems where libsodium is not on the
default dynamic-loader path, that import fails during *collection* — before any
test body runs ``ensure_libsodium()``. Calling it here, at conftest import,
guarantees the library is resolvable before any test module is imported. The
call is idempotent and a no-op when libsodium is already available.
"""

from __future__ import annotations

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium

ensure_libsodium()
