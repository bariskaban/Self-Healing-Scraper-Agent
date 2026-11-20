"""Shared by every test: no test may reach the OpenAI API (CLAUDE.md, "Model calls").

A key in the developer's shell would let `create_app` build the real agents. It is taken out of
the environment before any test module is imported; tests that need agents hand in ones on a
scripted model.
"""
import os

os.environ.pop("OPENAI_API_KEY", None)
