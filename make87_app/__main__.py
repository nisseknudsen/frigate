import logging
import yaml

import make87

logger = logging.getLogger(__name__)

FRIGATE_CONFIG_PATH = "/config/config.yaml"
FRIGATE_DEFAULT_CONFIG_PATH = "/opt/frigate/config_template/config.yaml"


def load_frigate_config():
    try:
        with open(FRIGATE_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"[Frigate] Config file not found at {FRIGATE_CONFIG_PATH}, using default template.")
        with open(FRIGATE_DEFAULT_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)


def write_frigate_config(config):
    with open(FRIGATE_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def cameras_env_to_frigate_dict(cameras_env):
    """
    Convert the list of camera configs from env to Frigate config format.
    """
    cameras = {}
    for cam in cameras_env:
        name = cam.get("camera_name") or cam.get("camera_ip")
        ip = cam["camera_ip"]
        port = cam.get("camera_port", 554)
        path = cam.get("camera_path", "/")
        sub_path = cam.get("camera_sub_path", path)
        username = cam.get("camera_username")
        password = cam.get("camera_password")
        onvif_port = cam.get("onvif_port", None)

        # Build RTSP URL
        if username and password:
            rtsp_url = f"rtsp://{username}:{password}@{ip}:{port}{path}"
            rtsp_url_sub = f"rtsp://{username}:{password}@{ip}:{port}{sub_path}"
        elif username:
            rtsp_url = f"rtsp://{username}@{ip}:{port}{path}"
            rtsp_url_sub = f"rtsp://{username}@{ip}:{port}{sub_path}"
        else:
            rtsp_url = f"rtsp://{ip}:{port}{path}"
            rtsp_url_sub = f"rtsp://{ip}:{port}{sub_path}"

        cameras[name] = {
            "enabled": True,
            "ffmpeg": {
                "hwaccel_args": "preset-vaapi",
                "inputs": [
                    {"path": rtsp_url, "roles": ["record"]},
                    {"path": rtsp_url_sub, "roles": ["detect"]},
                ],
            },
            "detect": {"enabled": False},
            "record": {"enabled": True, "retain": {"days": 7}},
        }

        if onvif_port is not None:
            cameras[name]["onvif"] = {
                "host": ip,
                "port": onvif_port,
                "user": username,
                "password": password,
            }
    return cameras


def main():
    config = load_frigate_config()

    application_config = make87.config.load_config_from_env()
    cameras_env = application_config.config.get("cameras", [])
    try:
        new_camera_dict = cameras_env_to_frigate_dict(cameras_env)
        config["cameras"] = new_camera_dict
        write_frigate_config(config)
        logger.info("[Frigate] Cameras changed, config updated.")
    except Exception as e:
        logger.error(f"[Frigate] Error in main loop: {e}")
        raise Exception("There was a problem with configuring the cameras or writing the config.yaml.")


if __name__ == "__main__":
    main()
