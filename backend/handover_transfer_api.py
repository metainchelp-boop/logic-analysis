"""MetaInc 전산 전용 담당자 변경 서비스 API."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from handover_transfer import (
    HandoverTransferCommand,
    HandoverTransferService,
    sanitize_handover_error,
)


class HandoverTransferRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_key: str = Field(alias="requestKey", min_length=1, max_length=160)
    client_id: int = Field(alias="clientId", gt=0)
    from_username: str = Field(alias="fromUsername", min_length=1, max_length=100)
    to_username: str = Field(alias="toUsername", min_length=1, max_length=100)
    to_name: str = Field(alias="toName", default="", max_length=100)
    place_business_keys: list[str] = Field(alias="placeBusinessKeys", default_factory=list)

    def command(self) -> HandoverTransferCommand:
        return HandoverTransferCommand(
            request_key=self.request_key,
            client_id=self.client_id,
            from_username=self.from_username,
            to_username=self.to_username,
            to_name=self.to_name,
            place_business_keys=tuple(self.place_business_keys),
        )


def _camelize(value):
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            parts = str(key).split("_")
            camel_key = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
            converted[camel_key] = _camelize(item)
        return converted
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def create_handover_router(
    service: HandoverTransferService, service_key: str
) -> APIRouter:
    router = APIRouter(prefix="/api/internal/handovers", tags=["internal-handover"])

    def require_service_key(
        provided: Annotated[str | None, Header(alias="X-Handover-Key")] = None,
    ) -> None:
        if not service_key or not provided or not hmac.compare_digest(provided, service_key):
            raise HTTPException(status_code=401, detail="서비스 인증에 실패했습니다.")

    def invoke(operation):
        try:
            return _camelize(operation())
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "HANDOVER_TRANSFER_BLOCKED",
                    "message": sanitize_handover_error(exc),
                    "action": "전산의 담당자 연결과 로직분석 자산 연결을 확인해 주세요.",
                },
            ) from exc

    @router.post("/preview", dependencies=[])
    def preview(
        request: HandoverTransferRequest,
        _: Annotated[str | None, Header(alias="X-Handover-Key")] = None,
    ):
        require_service_key(_)
        return invoke(lambda: service.preview(request.command()))

    @router.post("/transfer", dependencies=[])
    def transfer(
        request: HandoverTransferRequest,
        _: Annotated[str | None, Header(alias="X-Handover-Key")] = None,
    ):
        require_service_key(_)
        return invoke(lambda: service.transfer(request.command()))

    @router.get("/requests/{request_key}")
    def request_status(
        request_key: str,
        _: Annotated[str | None, Header(alias="X-Handover-Key")] = None,
    ):
        require_service_key(_)
        return invoke(lambda: service.request_status(request_key))

    @router.get("/residual/{username}")
    def residual(
        username: str,
        _: Annotated[str | None, Header(alias="X-Handover-Key")] = None,
    ):
        require_service_key(_)
        return invoke(lambda: service.residual(username))

    return router
