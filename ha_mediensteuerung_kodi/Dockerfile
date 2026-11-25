FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/medien
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt
COPY appdaemon ./appdaemon
COPY homeassistant ./homeassistant
COPY runtime ./runtime
COPY config.yaml LICENSE.md THIRD_PARTY.md ./
ENTRYPOINT ["python", "/opt/medien/runtime/entrypoint.py"]
