import os
import logging
import yaml
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from make87_messages.core.header_pb2 import Header
from make87_messages.transport.rtsp_pb2 import RTSPRequest
from make87_messages.primitive.bool_pb2 import Bool

import make87

FRIGATE_CONFIG_PATH = "/tmp/frigate/config.yaml"


def build_url(endpoint) -> str:
    """
    Build a full URL from an Endpoint message.
    """
    protocol = endpoint.protocol
    host = endpoint.host
    port = endpoint.port
    path = endpoint.path
    if not path.startswith("/"):
        path = "/" + path

    query = urlencode(endpoint.query_params) if endpoint.query_params else ""
    netloc = f"{host}:{port}" if port else host

    return str(urlunparse((protocol, netloc, path, "", query, "")))


def insert_credentials(url: str, username: str, password: str) -> str:
    """
    Insert credentials into a URL.
    """
    parsed = urlparse(url)
    netloc = f"{username}:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    new_parsed = parsed._replace(netloc=netloc)
    return str(urlunparse(new_parsed))


def update_frigate_config(name: str, rtsp_url: str, onvif_user: str | None, onvif_pass: str | None, ip: str):
    """
    Update Frigate config.yaml with a new or changed camera entry.
    """
    if os.path.exists(FRIGATE_CONFIG_PATH):
        with open(FRIGATE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
    else:
        config = {
            "mqtt": {"enabled": False},
            "tls": {"enabled": False},
            "auth": {"reset_admin_password": True},
            "cameras": {},
        }

    if "cameras" not in config:
        config["cameras"] = {}

    camera_config = {
        "enabled": True,
        "ffmpeg": {"inputs": [{"path": rtsp_url, "roles": ["record"]}]},
        "detect": {"enabled": False},
        "record": {"enabled": True, "retain": {"days": 1}},
    }

    if onvif_user and onvif_pass:
        camera_config["onvif"] = {"host": ip, "port": 8000, "user": onvif_user, "password": onvif_pass}

    if config["cameras"].get(name) == camera_config:
        return  # no changes

    config["cameras"][name] = camera_config

    with open(FRIGATE_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    logging.info(f"[Frigate] Updated config.yaml with camera: {name}")


def main():
    make87.initialize()

    provider = make87.get_provider(
        name="RTSP_CONFIG_UPDATER", requester_message_type=RTSPRequest, provider_message_type=Bool
    )

    def callback(message: RTSPRequest) -> Bool:
        url = build_url(message.endpoint)
        ip = message.endpoint.host
        username = password = None

        if message.HasField("basic_auth"):
            username = message.basic_auth.username
            password = message.basic_auth.password
            url = insert_credentials(url, username, password)
        elif message.HasField("digest_auth"):
            username = message.digest_auth.username
            password = message.digest_auth.password
            url = insert_credentials(url, username, password)

        camera_name = ip.replace(".", "_")
        update_frigate_config(camera_name, url, username, password, ip)

        return Bool(
            header=make87.header_from_message(Header, message=message, append_entity_path="config_written"),
            value=True,
        )

    provider.provide(callback)
    make87.loop()


if __name__ == "__main__":
    main()
