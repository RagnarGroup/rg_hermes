"""Environment a test must keep when it clears ``os.environ`` (``patch.dict(..., clear=True)``).

A fully cleared environment breaks Windows CPython: OpenSSL needs ``SYSTEMROOT`` to build an SSL
context (aiohttp creates one at import) and ``Path.home()`` needs ``USERPROFILE``. These are not
configuration, and none of them exists on POSIX, where ``PLATFORM_ENV`` is empty and the cleared
environment stays empty too.
"""

import os

PLATFORM_ENV = {
    k: os.environ[k]
    for k in ("SYSTEMROOT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP")
    if k in os.environ
}
