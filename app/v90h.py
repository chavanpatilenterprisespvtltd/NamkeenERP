from __future__ import annotations
from fastapi import HTTPException, Request
from sqlalchemy.engine import Engine
from .auth import authenticate
from .identity import permissions_for_user
from .master_scope import assert_entity_location_allowed

def require_master_access(engine: Engine, request: Request, entity_id: str | None = None, location_id: str | None = None, write: bool = False):
    user = authenticate(request)
    needed = 'masters.edit' if write else 'masters.view'
    if needed not in permissions_for_user(engine, user.user_id):
        raise HTTPException(status_code=403, detail='permission denied')
    try:
        assert_entity_location_allowed(engine, user.user_id, entity_id, location_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return user
