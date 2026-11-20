"""Normalisers: the text a locator found, made into a value of the output contract, or None.

A wrong value is worse than a missing one. Pure functions: no network, no files, no model.
"""
from app.extract.core import Parsed, ParseContext, clean
from app.extract.parse import parse
from app.extract.settings import ExtractSettings

__all__ = ["ExtractSettings", "ParseContext", "Parsed", "clean", "parse"]
