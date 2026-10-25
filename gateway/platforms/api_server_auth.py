"""Bearer-auth decorator shared by the API server adapter and its route mixins."""

from functools import wraps


def _require_auth(handler):
    """Run ``self._check_auth`` first and return its 401 instead of the handler."""
    @wraps(handler)
    async def _wrapped(self, request, *args, **kwargs):
        auth_err = self._check_auth(request)
        if auth_err:
            return auth_err
        return await handler(self, request, *args, **kwargs)
    return _wrapped
