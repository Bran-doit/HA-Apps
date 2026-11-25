ARG BUILD_FROM
FROM ${BUILD_FROM}

COPY rootfs /
RUN chmod 0755 /run.sh

CMD ["/run.sh"]

