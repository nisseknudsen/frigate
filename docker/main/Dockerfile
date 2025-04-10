ARG DEBIAN_FRONTEND=noninteractive

ARG BASE_IMAGE=ghcr.io/blakeblackshear/frigate:0.15.0-tensorrt

FROM ${BASE_IMAGE} AS frigate

COPY docker/main/requirements.txt /requirements.txt
RUN pip3 install -r /requirements.txt
RUN rm /requirements.txt

WORKDIR /opt/frigate/
COPY make87_app make87_app/
COPY docker/main/config/ config_template/

COPY docker/main/rootfs/ /

