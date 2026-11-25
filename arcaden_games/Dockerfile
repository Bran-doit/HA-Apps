FROM python:3.13-alpine
WORKDIR /app
COPY www /app/www
COPY server.py config.yaml /app/
USER 65534:65534
EXPOSE 8100
CMD ["python", "-u", "/app/server.py"]
