"""Lab 3 Proof-of-Work blockchain package.

Bootstraps libsodium on import. Submodules import ``ipv8`` at module load,
which eagerly loads libnacl/libsodium; doing this here guarantees the library
is resolvable before any submodule (e.g. the ``lab3-node`` CLI) is imported.
The call is idempotent and a no-op when libsodium is already available.
"""

from lab1_pow_ipv8.libsodium_bootstrap import ensure_libsodium

ensure_libsodium()
