# The same verified official Python image is used to build and run the core.
FROM python:3.11.17-slim-bookworm@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ ./src/
RUN python -m venv /opt/flower-venv \
    && /opt/flower-venv/bin/python -m pip install --no-cache-dir . \
    && /opt/flower-venv/bin/python -m pip check

FROM python:3.11.17-slim-bookworm@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb

ENV PATH="/opt/flower-venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLOWER_HOME=/data

COPY --from=builder /opt/flower-venv /opt/flower-venv
RUN groupadd --gid 10001 flower \
    && useradd --uid 10001 --gid 10001 --create-home flower \
    && mkdir /data \
    && chown flower:flower /data

USER 10001:10001
WORKDIR /home/flower
VOLUME ["/data"]

CMD ["flower-mcp", "serve", "--profile", "default", "--profile-root", "/data", "--transport", "stdio"]
