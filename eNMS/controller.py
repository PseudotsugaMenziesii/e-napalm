from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from flask import Flask
from hvac import Client as VaultClient
from importlib import import_module
from importlib.abc import Loader
from importlib.util import spec_from_file_location, module_from_spec
from ldap3 import ALL, Server
from logging import basicConfig, StreamHandler
from logging.handlers import RotatingFileHandler
from napalm._SUPPORTED_DRIVERS import SUPPORTED_DRIVERS
from netmiko.ssh_dispatcher import CLASS_MAPPER, FILE_TRANSFER_MAP
from os import environ
from pathlib import Path
from sqlalchemy.exc import InvalidRequestError
from simplekml import Color, Style
from string import punctuation
from tacacs_plus.client import TACACSClient
from typing import Any, Dict, Set
from yaml import load, BaseLoader


class Controller:

    device_subtypes: Dict[str, str] = {
        "antenna": "Antenna",
        "firewall": "Firewall",
        "host": "Host",
        "optical_switch": "Optical switch",
        "regenerator": "Regenerator",
        "router": "Router",
        "server": "Server",
        "switch": "Switch",
    }

    link_subtypes: Dict[str, str] = {
        "bgp_peering": "BGP peering",
        "etherchannel": "Etherchannel",
        "ethernet_link": "Ethernet link",
        "optical_channel": "Optical channel",
        "optical_link": "Optical link",
        "pseudowire": "Pseudowire",
    }

    link_colors: Dict[str, str] = {
        "bgp_peering": "#77ebca",
        "etherchannel": "#cf228a",
        "ethernet_link": "#0000ff",
        "optical_link": "#d4222a",
        "optical_channel": "#ff8247",
        "pseudowire": "#902bec",
    }

    NETMIKO_DRIVERS = sorted((driver, driver) for driver in CLASS_MAPPER)
    NETMIKO_SCP_DRIVERS = sorted((driver, driver) for driver in FILE_TRANSFER_MAP)
    NAPALM_DRIVERS = sorted((driver, driver) for driver in SUPPORTED_DRIVERS[1:])

    def __init__(self):
        self.USE_SYSLOG = int(environ.get("USE_SYSLOG", False))
        self.USE_TACACS = int(environ.get("USE_TACACS", False))
        self.USE_LDAP = int(environ.get("USE_LDAP", False))
        self.USE_VAULT = int(environ.get("USE_VAULT", False))
        self.config = self.load_config()
        self.custom_properties = self.load_custom_properties()
        self.configure_scheduler()
        if self.USE_TACACS:
            self.configure_tacacs_server()
        if self.USE_LDAP:
            self.configure_ldap_client()
        if self.USE_VAULT:
            self.configure_vault_client()

    def init_app(self, app: Flask):
        self.app = app
        self.create_google_earth_styles()
        self.configure_logs()

    def configure_logs(self) -> None:
        basicConfig(
            level=getattr(
                import_module("logging"), controller.config["ENMS_LOG_LEVEL"]
            ),
            format="%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%m-%d-%Y %H:%M:%S",
            handlers=[
                RotatingFileHandler(
                    self.app.path / "logs" / "app_logs" / "enms.log",
                    maxBytes=20_000_000,
                    backupCount=10,
                ),
                StreamHandler(),
            ],
        )

    def configure_scheduler(self) -> None:
        self.scheduler = BackgroundScheduler(
            {
                "apscheduler.jobstores.default": {
                    "type": "sqlalchemy",
                    "url": "sqlite:///jobs.sqlite",
                },
                "apscheduler.executors.default": {
                    "class": "apscheduler.executors.pool:ThreadPoolExecutor",
                    "max_workers": "50",
                },
                "apscheduler.job_defaults.misfire_grace_time": "5",
                "apscheduler.job_defaults.coalesce": "true",
                "apscheduler.job_defaults.max_instances": "3",
            }
        )
        self.scheduler.start()

    def load_services(self) -> None:
        path_services = [self.app.path / "eNMS" / "services"]
        custom_services_path = self.config["CUSTOM_SERVICES_PATH"]
        if custom_services_path:
            path_services.append(Path(custom_services_path))
        for path in path_services:
            for file in path.glob("**/*.py"):
                if "init" in str(file):
                    continue
                if not self.config["CREATE_EXAMPLES"] and "examples" in str(file):
                    continue
                spec = spec_from_file_location(str(file).split("/")[-1][:-3], str(file))
                assert isinstance(spec.loader, Loader)
                module = module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)
                except InvalidRequestError:
                    continue

    def configure_ldap_client(self) -> None:
        self.LDAP_SERVER = environ.get("LDAP_SERVER")
        self.LDAP_USERDN = environ.get("LDAP_USERDN")
        self.LDAP_BASEDN = environ.get("LDAP_BASEDN")
        self.LDAP_ADMIN_GROUP = environ.get("LDAP_ADMIN_GROUP", "").split(",")
        self.ldap_client = Server(environ.get("LDAP_SERVER"), get_info=ALL)

    def configure_tacacs_server(self) -> None:
        self.tacacs_server = TACACSClient(
            environ.get("TACACS_ADDR"), 49, environ.get("TACACS_PASSWORD")
        )

    def configure_vault_client(self) -> None:
        self.vault_client = VaultClient()
        self.vault_client.url = environ.get("VAULT_ADDR")
        self.vault_client.token = environ.get("VAULT_TOKEN")
        if self.vault_client.sys.is_sealed() and environ.get("UNSEAL_VAULT"):
            keys = [environ.get(f"UNSEAL_VAULT_KEY{i}") for i in range(1, 6)]
            self.vault_client.sys.submit_unseal_keys(filter(None, keys))

    def allowed_file(self, name: str, allowed_modules: Set[str]) -> bool:
        allowed_syntax = "." in name
        allowed_extension = name.rsplit(".", 1)[1].lower() in allowed_modules
        return allowed_syntax and allowed_extension

    def create_google_earth_styles(self):
        self.google_earth_styles = {}
        for subtype in self.device_subtypes:
            point_style = Style()
            point_style.labelstyle.color = Color.blue
            path_icon = f"{self.app.path}/eNMS/views/static/images/2D/{subtype}.gif"
            point_style.iconstyle.icon.href = path_icon
            self.google_earth_styles[subtype] = point_style
        for subtype in self.link_subtypes:
            line_style = Style()
            color = self.link_colors[subtype]
            kml_color = "#ff" + color[-2:] + color[3:5] + color[1:3]
            line_style.linestyle.color = kml_color
            self.google_earth_styles[subtype] = line_style

    def get_time(self):
        return str(datetime.now()).replace("-", "+")

    def load_config(self) -> dict:
        return {
            "CLUSTER": int(environ.get("CLUSTER", False)),
            "CLUSTER_ID": int(environ.get("CLUSTER_ID", True)),
            "CLUSTER_SCAN_SUBNET": environ.get(
                "CLUSTER_SCAN_SUBNET", "192.168.105.0/24"
            ),
            "CLUSTER_SCAN_PROTOCOL": environ.get("CLUSTER_SCAN_PROTOCOL", "http"),
            "CLUSTER_SCAN_TIMEOUT": float(environ.get("CLUSTER_SCAN_TIMEOUT", 0.05)),
            "DEFAULT_LONGITUDE": float(environ.get("DEFAULT_LONGITUDE", -96.0)),
            "DEFAULT_LATITUDE": float(environ.get("DEFAULT_LATITUDE", 33.0)),
            "DEFAULT_ZOOM_LEVEL": int(environ.get("DEFAULT_ZOOM_LEVEL", 5)),
            "DEFAULT_VIEW": environ.get("DEFAULT_VIEW", "2D"),
            "DEFAULT_MARKER": environ.get("DEFAULT_MARKER", "Image"),
            "CREATE_EXAMPLES": int(environ.get("CREATE_EXAMPLES", True)),
            "CUSTOM_SERVICES_PATH": environ.get("CUSTOM_SERVICES_PATH"),
            "ENMS_LOG_LEVEL": environ.get("ENMS_LOG_LEVEL", "DEBUG").upper(),
            "ENMS_SERVER_ADDR": environ.get("ENMS_SERVER_ADDR"),
            "GIT_AUTOMATION": environ.get("GIT_AUTOMATION", ""),
            "GIT_CONFIGURATIONS": environ.get("GIT_CONFIGURATIONS", ""),
            "GOTTY_PORT_REDIRECTION": int(environ.get("GOTTY_PORT_REDIRECTION", False)),
            "GOTTY_BYPASS_KEY_PROMPT": environ.get("GOTTY_BYPASS_KEY_PROMPT"),
            "GOTTY_START_PORT": int(environ.get("GOTTY_START_PORT", 9000)),
            "GOTTY_END_PORT": int(environ.get("GOTTY_END_PORT", 9100)),
            "MATTERMOST_URL": environ.get("MATTERMOST_URL", ""),
            "MATTERMOST_CHANNEL": environ.get("MATTERMOST_CHANNEL", ""),
            "MATTERMOST_VERIFY_CERTIFICATE": int(
                environ.get("MATTERMOST_VERIFY_CERTIFICATE", True)
            ),
            "POOL_FILTER": environ.get("POOL_FILTER", "All objects"),
            "SLACK_TOKEN": environ.get("SLACK_TOKEN", ""),
            "SLACK_CHANNEL": environ.get("SLACK_CHANNEL", ""),
        }

    def load_custom_properties(self) -> dict:
        filepath = environ.get("PATH_CUSTOM_PROPERTIES")
        if not filepath:
            return {}
        with open(filepath, "r") as properties:
            return load(properties, Loader=BaseLoader)

    def str_dict(self, input: Any, depth: int = 0) -> str:
        tab = "\t" * depth
        if isinstance(input, list):
            result = "\n"
            for element in input:
                result += f"{tab}- {self.str_dict(element, depth + 1)}\n"
            return result
        elif isinstance(input, dict):
            result = ""
            for key, value in input.items():
                result += f"\n{tab}{key}: {self.str_dict(value, depth + 1)}"
            return result
        else:
            return str(input)

    def strip_all(self, input: str) -> str:
        return input.translate(str.maketrans("", "", f"{punctuation} "))


controller = Controller()
