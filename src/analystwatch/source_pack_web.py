from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .source_packs import (
    SourcePack,
    SourcePackId,
    SourcePackMaterialization,
    SourcePackOverrides,
    list_source_packs,
    materialize_source_pack,
)


class SourcePackMaterializeRequest(BaseModel):
    pack_id: SourcePackId
    role_mapping: dict[str, str] = Field(default_factory=dict)
    overrides: SourcePackOverrides | None = None


def configure_source_pack_web(app: FastAPI) -> None:
    def catalog() -> list[SourcePack]:
        return list_source_packs()

    def materialize(request: SourcePackMaterializeRequest) -> SourcePackMaterialization:
        try:
            return materialize_source_pack(
                request.pack_id,
                request.role_mapping,
                overrides=request.overrides,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    app.add_api_route(
        "/api/source-packs",
        catalog,
        methods=["GET"],
        response_model=list[SourcePack],
    )
    app.add_api_route(
        "/api/source-packs/materialize",
        materialize,
        methods=["POST"],
        response_model=SourcePackMaterialization,
    )
