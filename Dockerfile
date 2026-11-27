# syntax=docker/dockerfile:1.6
# Multi-stage build for a minimal bankstatementparser image.
#
# The image runs the bankstatementparser command-line interface:
#
#   docker run --rm -v "$PWD:/data" bankstatementparser \
#     --type camt --input /data/statement.xml

# Pinned by digest; Dependabot's docker updater moves it.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# requirements/runtime.txt is exported from poetry.lock with hashes, so
# the image installs exactly the locked runtime set; the package itself
# goes on top without resolving anything further. pyproject.toml names
# README.md as the readme, so the build needs it too.
COPY requirements/runtime.txt ./requirements.txt
COPY pyproject.toml README.md LICENSE LICENSE-APACHE LICENSE-MIT ./
COPY bankstatementparser ./bankstatementparser

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --require-hashes -r requirements.txt \
    && /opt/venv/bin/pip wheel --no-deps --wheel-dir /tmp/wheels . \
    && /opt/venv/bin/pip install --no-deps /tmp/wheels/*.whl

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

LABEL org.opencontainers.image.title="bankstatementparser" \
      org.opencontainers.image.description="Parse bank statements (CAMT, PAIN.001, MT940, MT942, OFX, BAI2, CSV) into unified transactions." \
      org.opencontainers.image.source="https://github.com/sebastienrousseau/bankstatementparser" \
      org.opencontainers.image.licenses="Apache-2.0 OR MIT"

RUN groupadd --system bsp && useradd --system --gid bsp --home /home/bsp bsp \
    && mkdir -p /home/bsp \
    && chown -R bsp:bsp /home/bsp

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER bsp
WORKDIR /home/bsp

ENTRYPOINT ["bankstatementparser"]
CMD ["--help"]
