"""The mock portal: a fake tender portal we break on purpose, and the recipe that reads it.

    portal = MockPortal()
    client = httpx.Client(transport=httpx.MockTransport(portal.handle), base_url=portal.base_url)

No socket is opened and no request leaves the process (CLAUDE.md, "no live portals").
"""
from mock_portal.portal import MockPortal
from mock_portal.recipe import TIMEZONE, recipe

__all__ = ["TIMEZONE", "MockPortal", "recipe"]
