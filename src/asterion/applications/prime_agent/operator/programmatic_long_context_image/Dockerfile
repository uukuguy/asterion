FROM node:22.8.0-bookworm-slim@sha256:bcf420bf2d8b4e7670c536eeac6b6a4b6e59a3dcb9c688dd3e4691fef3dfddc1
WORKDIR /workspace
COPY launcher.mjs /usr/local/bin/prime-programmatic-long-context.mjs
COPY fixture /opt/prime-p2/fixture
COPY corpus /opt/prime-p2/corpus
COPY oracle /opt/prime-p2/oracle
COPY fixture-lock.json /opt/prime-p2/fixture-lock.json
RUN chmod 0555 /usr/local/bin/prime-programmatic-long-context.mjs
USER 65534:65534
ENTRYPOINT ["node", "/usr/local/bin/prime-programmatic-long-context.mjs"]
