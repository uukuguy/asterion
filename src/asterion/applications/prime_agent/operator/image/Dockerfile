FROM python:3.11.11-bookworm

WORKDIR /workspace
COPY requirements.lock /opt/prime-requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/prime-requirements.lock
COPY launcher.py /usr/local/bin/prime-ipython-coding.py
COPY fixture /opt/prime-fixture
RUN chmod 0555 /usr/local/bin/prime-ipython-coding.py
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/prime-ipython-coding.py"]
