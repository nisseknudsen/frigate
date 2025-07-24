import logging
import yaml
import urllib.parse

import make87

logger = logging.getLogger(__name__)

FRIGATE_CONFIG_PATH = "/config/config.yaml"
FRIGATE_DEFAULT_CONFIG_PATH = "/opt/frigate/config_template/config.yaml"


def load_frigate_config():
    try:
        with open(FRIGATE_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
            if config is None:
                logger.warning(f"[Frigate] Config file at {FRIGATE_CONFIG_PATH} is empty, using default template.")
                with open(FRIGATE_DEFAULT_CONFIG_PATH, "r") as default_f:
                    config = yaml.safe_load(default_f)
            return config
    except FileNotFoundError:
        logger.warning(f"[Frigate] Config file not found at {FRIGATE_CONFIG_PATH}, using default template.")
        with open(FRIGATE_DEFAULT_CONFIG_PATH, "r") as f:
            return yaml.safe_load(f)

def write_frigate_config(config):
    with open(FRIGATE_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def build_rtsp_url(ip, port, path, username=None, password=None, encode_password=False):
    if username and password:
        pwd = urllib.parse.quote(password) if encode_password else password
        return f"ffmpeg:rtsp://{username}:{pwd}@{ip}:{port}{path}"
    elif username:
        return f"ffmpeg:rtsp://{username}@{ip}:{port}{path}"
    else:
        return f"ffmpeg:rtsp://{ip}:{port}{path}"


def cameras_env_to_frigate_dict_and_restream(cameras_env, retention_days=7):
    """
    Convert the list of camera configs from env to Frigate config format,
    and build the restream config for go2rtc.
    """
    cameras = {}
    restream = {}

    for cam in cameras_env:
        name = cam.get("camera_name") or cam.get("camera_ip")
        ip = cam["camera_ip"]
        port = cam.get("camera_port", 554)
        path = cam.get("camera_path", "/")
        sub_path = cam.get("camera_sub_path", path)
        username = cam.get("camera_username")
        password = cam.get("camera_password")
        onvif_port = cam.get("onvif_port", None)

        # Build RTSP URLs (URL encode password for go2rtc streams)
        rtsp_url = build_rtsp_url(ip, port, path, username, password, encode_password=True)
        rtsp_url_sub = build_rtsp_url(ip, port, sub_path, username, password, encode_password=True)

        ffmpeg_inputs = []
        # If main and sub path are the same, only create one go2rtc stream and one ffmpeg input with both roles
        if sub_path == path:
            restream[name] = [rtsp_url]
            ffmpeg_inputs.append(
                {
                    "path": f"rtsp://localhost:8554/{name}",
                    "roles": ["record", "detect"],
                }
            )
            live_stream_name = name
        else:
            restream[name] = rtsp_url
            restream[f"{name}_sub"] = rtsp_url_sub
            ffmpeg_inputs.append(
                {"path": f"rtsp://localhost:8554/{name}", "roles": ["record"]}
            )
            ffmpeg_inputs.append(
                {"path": f"rtsp://localhost:8554/{name}_sub", "roles": ["detect"]}
            )
            live_stream_name = f"{name}_sub"

        cameras[name] = {
            "enabled": True,
            "live": {"stream_name": live_stream_name},
            "ffmpeg": {
                "hwaccel_args": "preset-vaapi",
                "inputs": ffmpeg_inputs,
            },
            "detect": {"enabled": False},
            "record": {"enabled": True, "retain": {"days": retention_days}},
        }

        if onvif_port is not None:
            cameras[name]["onvif"] = {
                "host": ip,
                "port": onvif_port,
                "user": username,
                "password": password,
            }
    return cameras, restream


def main():
    config = load_frigate_config()

    application_config = make87.config.load_config_from_env()
    cameras_env = application_config.config.get("cameras", [])
    retention_days = application_config.config.get("retention", 7)
    try:
        new_camera_dict, restream_dict = cameras_env_to_frigate_dict_and_restream(cameras_env, retention_days=retention_days)
        config["cameras"] = new_camera_dict
        if "go2rtc" not in config:  # keep any other existing go2rtc config
            config["go2rtc"] = {}
        config["go2rtc"]["streams"] = restream_dict

        write_frigate_config(config)
        logger.info("[Frigate] Cameras and restream config updated.")
    except Exception as e:
        logger.error(f"[Frigate] Error in main loop: {e}")
        raise Exception("There was a problem with configuring the cameras or writing the config.yaml.")


if __name__ == "__main__":
    main()
