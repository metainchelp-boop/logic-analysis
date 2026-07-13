"""API 입출력 스키마 (pydantic v2)."""
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    team_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ChannelIn(BaseModel):
    channel: str
    mode: str = "direct"
    fields: Dict[str, str] = {}


class ChannelOut(BaseModel):
    channel: str
    mode: str
    status: str
    fields_masked: Dict[str, str] = {}


class ClientIn(BaseModel):
    name: str
    category: Optional[str] = None
    status: str = "active"
    owner_id: Optional[int] = None
    contact: Optional[str] = None
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    memo: Optional[str] = None
    channels: List[ChannelIn] = []


class ClientOut(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    status: str
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    contact: Optional[str] = None
    contract_start: Optional[str] = None
    contract_end: Optional[str] = None
    biz_reg_name: Optional[str] = None
    sales_manager: Optional[str] = None
    db_grade: Optional[str] = None
    memo: Optional[str] = None
    channels: List[ChannelOut] = []
    connected_count: int = 0
