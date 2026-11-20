ARG BUILD_FROM
FROM ${BUILD_FROM}

# The app version in config.yaml is the gateway release it installs.
ARG BUILD_VERSION
RUN pip install --no-cache-dir \
    "econext-gateway @ https://github.com/LeeNuss/econext-gateway/releases/download/v${BUILD_VERSION}/econext_gateway-${BUILD_VERSION}-py3-none-any.whl"

COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
