import os
import logging
import threading
import requests
from typing import Optional

import yaml
from urllib.parse import urlparse, urlunparse, urlencode

from make87_messages.core.header_pb2 import Header
from make87_messages.transport.rtsp_pb2 import RTSPRequest
from make87_messages.primitive.bool_pb2 import Bool

import make87

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

FRIGATE_CONFIG_PATH = "/config/config.yaml"
RESTART_DELAY = 5  # seconds
_restart_timer: Optional[threading.Timer] = None
_restart_lock = threading.Lock()


def build_url(endpoint) -> str:
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
    parsed = urlparse(url)
    netloc = f"{username}:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return str(urlunparse(parsed._replace(netloc=netloc)))


def trigger_frigate_restart():
    try:
        logger.info("[Frigate] Restart timer expired, calling restart endpoint...")
        response = requests.post("http://localhost:5000/api/restart", json={})
        response.raise_for_status()
        logger.info("[Frigate] Restart request successful")
    except Exception as e:
        logger.error(f"[Frigate] Failed to restart Frigate: {e}")


def schedule_restart():
    global _restart_timer
    with _restart_lock:
        if _restart_timer:
            _restart_timer.cancel()
        _restart_timer = threading.Timer(RESTART_DELAY, trigger_frigate_restart)
        _restart_timer.start()
        logger.info(f"[Frigate] Restart scheduled in {RESTART_DELAY} seconds...")


def update_frigate_config(
    name: str, rtsp_url: str, onvif_user: Optional[str], onvif_pass: Optional[str], ip: str
) -> bool:
    """
    Update config.yaml and return True if it was a new camera or a changed config.
    """
    with open(FRIGATE_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    if "cameras" not in config:
        config["cameras"] = {}

    if name in config["cameras"]:
        return False  # no change

    camera_config = {
        "enabled": True,
        "ffmpeg": {"hwaccel_args": "preset-vaapi", "inputs": [{"path": rtsp_url, "roles": ["record"]}]},
        "detect": {"enabled": False},
        "record": {"enabled": True, "retain": {"days": 3}},
    }

    if onvif_user and onvif_pass:
        camera_config["onvif"] = {"host": ip, "port": 8000, "user": onvif_user, "password": onvif_pass}

    config["cameras"][name] = camera_config
    with open(FRIGATE_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    logger.info(f"[Frigate] Updated config.yaml with camera: {name}")
    return True


def main():
    make87.initialize()

    provider = make87.get_provider(name="RTSP_STREAM", requester_message_type=RTSPRequest, provider_message_type=Bool)

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

        path_suffix = message.endpoint.path.lstrip("/").replace("/", "_") or "camera"
        camera_name = f"{ip.replace('.', '_')}_{path_suffix}"

        changed = update_frigate_config(camera_name, url, username, password, ip)

        if changed:
            schedule_restart()

        return Bool(
            header=make87.header_from_message(Header, message=message, append_entity_path="config_written"),
            value=True,
        )

    provider.provide(callback)
    make87.loop()


if __name__ == "__main__":
    main()
