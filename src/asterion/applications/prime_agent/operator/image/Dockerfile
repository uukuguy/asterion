FROM node:22.8.0-bookworm-slim@sha256:1f12a613e95ce50b7a61f58f05f3bed8c86f583768495bb8ea7cf049337ec3ee

WORKDIR /workspace
COPY launcher.mjs /usr/local/bin/prime-ipython-coding
COPY fixture /opt/prime-fixture
RUN chmod 0555 /usr/local/bin/prime-ipython-coding
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/prime-ipython-coding"]
