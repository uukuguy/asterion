FROM python:3.11.11-bookworm@sha256:4ca910a51a1a474e5d95aa52455331b2a94272eeae3c498be1ad7a2ff9b00bf3

WORKDIR /workspace
COPY image/requirements.lock /opt/prime-requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/prime-requirements.lock
COPY image/launcher.py /usr/local/bin/launcher.py
COPY image/closed_worker.py /usr/local/bin/closed_worker.py
COPY image/p1b_launcher.py /usr/local/bin/prime-p1b-persistent-worker.py
COPY image/fixture/p1b-workload.json /opt/prime-fixture/p1b-workload.json
RUN chmod 0555 /usr/local/bin/launcher.py /usr/local/bin/closed_worker.py /usr/local/bin/prime-p1b-persistent-worker.py \
    && test ! -e /root/.aws && test ! -L /root/.aws \
    && chmod 0711 /root
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/prime-p1b-persistent-worker.py"]
