"""Compatibility import for the Embassy access service.

The durable implementation lives in ``access.service``.  Older integration
code imports ``AccessService`` from ``embassy.access``, so this module keeps
that public import path stable without duplicating the access logic.
"""

from access.service import AccessService

__all__ = ["AccessService"]
