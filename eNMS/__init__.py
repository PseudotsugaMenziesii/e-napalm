from flask import Flask, render_template
from flask_assets import Bundle
from flask_cli import FlaskCLI
from flask.wrappers import Request
from logging import info
from os import environ
from pathlib import Path
from sqlalchemy.orm import configure_mappers
from typing import Any, Optional, Tuple, Type

from eNMS.cli import configure_cli
from eNMS.config import Config
from eNMS.controller import controller
from eNMS.database import Base, engine, Session
from eNMS.database.events import configure_events
from eNMS.database.functions import fetch, get_one
from eNMS.forms import form_properties, property_types
from eNMS.extensions import assets, bp, cache, csrf, login_manager, mail_client, toolbar
from eNMS.models.logging import SyslogServer
from eNMS.models.administration import User
from eNMS.properties import property_names
from eNMS.rest import configure_rest_api

import eNMS.routes  # noqa: F401


def register_modules(app: Flask) -> None:
    app.register_blueprint(bp)
    assets.init_app(app)
    cache.init_app(app)
    csrf.init_app(app)
    FlaskCLI(app)
    login_manager.init_app(app)
    mail_client.init_app(app)
    toolbar.init_app(app)
    controller.initialize_app(app)


def configure_login_manager(app: Flask) -> None:
    @login_manager.user_loader
    def user_loader(id: int) -> User:
        return fetch("User", id=id)

    @login_manager.request_loader
    def request_loader(request: Request) -> User:
        return fetch("User", name=request.form.get("name"))


def configure_database(app: Flask) -> None:
    @app.before_first_request
    def initialize_database() -> None:
        Base.metadata.create_all(bind=engine)
        configure_mappers()
        configure_events()
        controller.initialize_database()

    @app.teardown_appcontext
    def cleanup(exc_or_none: Optional[Exception]) -> None:
        Session.remove()


def configure_context_processor(app: Flask) -> None:
    @app.context_processor
    def inject_properties() -> dict:
        return {
            "form_properties": form_properties,
            "names": property_names,
            "parameters": get_one("Parameters").serialized,
            "property_types": {k: str(v) for k, v in property_types.items()},
        }


def configure_errors(app: Flask) -> None:
    @login_manager.unauthorized_handler
    def unauthorized_handler() -> Tuple[str, int]:
        return render_template("errors/page_403.html"), 403

    @app.errorhandler(403)
    def authorization_required(error: Any) -> Tuple[str, int]:
        return render_template("errors/page_403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error: Any) -> Tuple[str, int]:
        return render_template("errors/page_404.html"), 404


def configure_assets(app: Flask):
    assets.register(
        "js", Bundle("lib/base/**/*.js", "base/base.js", output="bundles/base.js")
    )
    assets.register(
        "css",
        Bundle(
            "lib/base/3_bootstrap/css/bootstrap.min.css",
            "lib/base/**/*.css",
            "base/base.min.css",
            output="bundles/base.css",
        ),
    )


def configure_syslog_server() -> None:
    syslog_server = SyslogServer(
        environ.get("SYSLOG_ADDR", "0.0.0.0"), int(environ.get("SYSLOG_PORT", 514))
    )
    syslog_server.start()


def create_app(path: Path, config_class: Type[Config]) -> Flask:
    app = Flask(__name__, static_folder="static")
    app.config.from_object(config_class)  # type: ignore
    app.path = path
    register_modules(app)
    configure_login_manager(app)
    configure_database(app)
    configure_context_processor(app)
    configure_rest_api(app)
    configure_errors(app)
    configure_assets(app)
    controller.load_services()
    configure_cli(app)
    if controller.USE_SYSLOG:
        configure_syslog_server()
    info("eNMS starting")
    return app
