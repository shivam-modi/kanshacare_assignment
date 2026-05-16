"""FastAPI dependency wires. Centralised so tests can override one place."""

from __future__ import annotations

from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, Request

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import MongoClient
from kanshacare_shared.geocoding.base import Geocoder


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo  # type: ignore[no-any-return]


def get_settings(request: Request) -> BaseAppSettings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_geocoder(request: Request) -> Geocoder:
    return request.app.state.geocoder  # type: ignore[no-any-return]


def get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq  # type: ignore[no-any-return]


MongoDep = Annotated[MongoClient, Depends(get_mongo)]
SettingsDep = Annotated[BaseAppSettings, Depends(get_settings)]
GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
ArqDep = Annotated[ArqRedis, Depends(get_arq)]
