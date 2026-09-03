FROM node:22.8.0-bookworm-slim@sha256:bcf420bf2d8b4e7670c536eeac6b6a4b6e59a3dcb9c688dd3e4691fef3dfddc1
WORKDIR /workspace
COPY launcher.mjs /usr/local/bin/prime-recursive-code-review.mjs
COPY fixture-lock.json /opt/prime-p3/fixture-lock.json
RUN chmod 0555 /usr/local/bin/prime-recursive-code-review.mjs
USER 65534:65534
ENTRYPOINT ["node", "/usr/local/bin/prime-recursive-code-review.mjs"]
