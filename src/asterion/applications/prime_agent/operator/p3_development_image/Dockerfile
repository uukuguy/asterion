FROM python:3.11.11-bookworm
WORKDIR /workspace
COPY image/requirements.lock /opt/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/requirements.lock
COPY p3_development_image/asterion_rlm.py /usr/local/lib/asterion_rlm.py
USER 65534:65534
