"""QR codes („QR-Codes“): list, create, edit, change a token, revoke
(services/codes.py). Every change is audited and sent as `code.changed`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ....core.errors import error_responses
from ....domain.constants import MAX_ID
from ...deps import AdminDep, CoreDep
from ...schemas.codes import CodeCreateIn, CodeEditIn, CodeOut, CodesOut, CodeTokenIn

router = APIRouter(responses=error_responses(409))

CodeId = Annotated[int, Path(ge=1, lt=MAX_ID)]


@router.get("/codes")
def list_codes(core: CoreDep) -> CodesOut:
    """Every code by number, revoked ones included, with their statistics."""
    return core.services.codes.views()


@router.post("/codes", status_code=201)
def create_code(body: CodeCreateIn, core: CoreDep, admin: AdminDep) -> CodeOut:
    """A new code with the next number and a random animal. `token` null =
    generate one; a custom token must never have been used by any code (409
    `token_taken`)."""
    code = core.services.codes.create(
        token=body.token, target=body.target, note=body.note, actor=admin.actor
    )
    return CodeOut(code=code, changed=True)


@router.get("/codes/{code_id}")
def get_code(code_id: CodeId, core: CoreDep) -> CodeOut:
    return CodeOut(code=core.services.codes.view(code_id), changed=False)


@router.patch("/codes/{code_id}")
def edit_code(code_id: CodeId, body: CodeEditIn, core: CoreDep, admin: AdminDep) -> CodeOut:
    """Change the target and/or the note (null = unchanged). 409
    `code_revoked` for a revoked code."""
    code, changed = core.services.codes.edit(
        code_id, target=body.target, note=body.note, actor=admin.actor
    )
    return CodeOut(code=code, changed=changed)


@router.post("/codes/{code_id}/token")
def set_code_token(code_id: CodeId, body: CodeTokenIn, core: CoreDep, admin: AdminDep) -> CodeOut:
    """A new token (null = generate one). The old one stops working at once;
    guests who joined through it stay. 409 `code_revoked`, `token_taken`."""
    code = core.services.codes.set_token(code_id, body.token, actor=admin.actor)
    return CodeOut(code=code, changed=True)


@router.delete("/codes/{code_id}")
def revoke_code(code_id: CodeId, core: CoreDep, admin: AdminDep) -> CodeOut:
    """„Löschen“: the token stops working, the code stays as a tombstone with
    its number, name and statistics (`changed` false when it was revoked
    already)."""
    code, changed = core.services.codes.revoke(code_id, actor=admin.actor)
    return CodeOut(code=code, changed=changed)
