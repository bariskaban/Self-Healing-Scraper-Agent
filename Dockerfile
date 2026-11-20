# Watchtower: API and dashboard on port 8080. Base image chosen in research/q06-language.md.
# BASE_IMAGE can be overridden (for example with a registry mirror); it must stay Playwright 1.65.2.
ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.65.2-noble
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /srv

# Dependencies first, read from pyproject.toml, so this layer stays cached when only app/ changes.
# When playwright is added to pyproject.toml, pin it to the base image's version: playwright==1.65.2.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app/ ./app/
# The portal we break on purpose: the app mounts it for the demo.
COPY mock_portal/ ./mock_portal/

ENV DATA_DIR=/data
# The container reads real portals. Everywhere else the fetch layer replays recordings unless told
# otherwise, so an agent or a test never reaches a live portal by accident (CLAUDE.md).
ENV FETCH_MODE=live
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
