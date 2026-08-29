# Single image, two roles (API or Celery worker) selected by the ROLE
# env var -- see docker-compose.yml. Keeps one Dockerfile in sync
# instead of two nearly-identical ones.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    libvirt-dev pkg-config gcc \
    qemu-utils libguestfs-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY n_migrate ./n_migrate

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[api]"

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV ROLE=api
EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
