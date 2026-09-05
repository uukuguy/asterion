FROM python:3.11.11-bookworm@sha256:4ca910a51a1a474e5d95aa52455331b2a94272eeae3c498be1ad7a2ff9b00bf3

WORKDIR /workspace
COPY image/requirements.lock /opt/prime-requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/prime-requirements.lock
COPY image/launcher.py /usr/local/bin/prime-ipython-coding.py
COPY image/fixture /opt/prime-fixture
RUN chmod 0555 /usr/local/bin/prime-ipython-coding.py
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/prime-ipython-coding.py"]
