ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

RUN apk add --no-cache nginx python3 py3-pip \
    && rm -f /etc/nginx/http.d/default.conf \
    && python3 -m venv /opt/shopping-sync/venv \
    && /opt/shopping-sync/venv/bin/pip install --no-cache-dir \
        "appdaemon>=4.5.11,<5" \
        "requests>=2.32,<3" \
        "websocket-client>=1.8,<2"

COPY rootfs /
RUN chmod +x /etc/services.d/shopping-sync/run /etc/services.d/shopping-sync/finish

LABEL \
  org.opencontainers.image.title="Home Assistant App: Shopping Sync" \
  org.opencontainers.image.description="Synchronisiert Home-Assistant-Todo-Listen mit einer mobilen Shopping-App ueber Firebase." \
  org.opencontainers.image.source="https://github.com/Bran-doit/HA-Apps" \
  org.opencontainers.image.licenses="MIT"

