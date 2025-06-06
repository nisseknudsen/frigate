import logging
import requests
from typing import Optional, Dict
import time
import copy

import yaml
from urllib.parse import urlparse

import make87
from make87.models import InterfaceConfig, BoundClient

logger = logging.getLogger(__name__)

FRIGATE_CONFIG_PATH = "/config/config.yaml"
POLL_INTERVAL = 10  # seconds


def trigger_frigate_restart():
    try:
        logger.info("[Frigate] Restart timer expired, calling restart endpoint...")
        response = requests.post("http://localhost:5000/api/restart", json={})
        response.raise_for_status()
        logger.info("[Frigate] Restart request successful")
    except Exception as e:
        logger.error(f"[Frigate] Failed to restart Frigate: {e}")


def fetch_all_paths(base_url: str, items_per_page: int = 100, headers: Optional[Dict] = None):
    all_paths = []
    page = 0

    while True:
        resp = requests.get(
            f"{base_url}/v3/paths/list", params={"page": page, "itemsPerPage": items_per_page}, headers=headers or {}
        )
        resp.raise_for_status()
        data = resp.json()
        all_paths.extend(data.get("items", []))

        if page + 1 >= data.get("pageCount", 0):
            break
        page += 1

    return all_paths


def load_frigate_config():
    with open(FRIGATE_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def write_frigate_config(config):
    with open(FRIGATE_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def paths_to_camera_dict(paths, rtsp_host, rtsp_port):
    """
    Convert mediamtx paths to a dict keyed by camera name.
    Use provided RTSP host and port for RTSP URL construction.
    """
    cameras = {}
    for path in paths:
        name = path.get("name")
        rtsp_url = f"rtsp://{rtsp_host}:{rtsp_port}/{name}"
        cameras[name] = {
            "enabled": True,
            "ffmpeg": {"hwaccel_args": "preset-vaapi", "inputs": [{"path": rtsp_url, "roles": ["record"]}]},
            "detect": {"enabled": False},
            "record": {"enabled": True, "retain": {"days": 7}},
        }
    return cameras


def main():
    application_config = make87.config.load_config_from_env()

    # Use mediamtx_api for HTTP REST API access
    mediamtx_http_interface: InterfaceConfig = application_config.interfaces.get("mediamtx_http")
    mediamtx_api_client: BoundClient = mediamtx_http_interface.clients.get("mediamtx_api")
    mediamtx_api_url = f"http://{mediamtx_api_client.vpn_ip}:{mediamtx_api_client.vpn_port}"

    # Use mediamtx_rtsp for RTSP URL construction
    rtsp_interface: InterfaceConfig = application_config.interfaces.get("rtsp_connection")
    rtsp_client: BoundClient = rtsp_interface.clients.get("rtsp_connection")
    rtsp_host = rtsp_client.vpn_ip
    rtsp_port = rtsp_client.vpn_port

    last_camera_dict = None

    while True:
        try:
            mediamtx_paths = fetch_all_paths(mediamtx_api_url)
            new_camera_dict = paths_to_camera_dict(mediamtx_paths, rtsp_host, rtsp_port)

            config = load_frigate_config()
            config_cameras = config.get("cameras", {})

            # Compare current config cameras with new_camera_dict
            if last_camera_dict is not None and new_camera_dict == last_camera_dict:
                # No change, sleep and continue
                time.sleep(POLL_INTERVAL)
                continue

            if new_camera_dict == config_cameras:
                last_camera_dict = copy.deepcopy(new_camera_dict)
                time.sleep(POLL_INTERVAL)
                continue

            # Update config
            config["cameras"] = new_camera_dict
            write_frigate_config(config)
            logger.info("[Frigate] Cameras changed, config updated.")

            # Trigger Frigate restart
            trigger_frigate_restart()

            last_camera_dict = copy.deepcopy(new_camera_dict)
        except Exception as e:
            logger.error(f"[Frigate] Error in main loop: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
