ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

RUN apk add --no-cache nginx python3 py3-pip \
    && rm -f /etc/nginx/http.d/default.conf \
    && python3 -m venv /opt/ki/venv \
    && /opt/ki/venv/bin/pip install --no-cache-dir "appdaemon==4.5.11" "requests>=2.32,<3" "PyYAML>=6,<7"
COPY source /opt/ki/source
COPY rootfs /
RUN chmod 755 /etc/services.d/ki-kindersicherung/run /etc/services.d/ki-kindersicherung/finish
