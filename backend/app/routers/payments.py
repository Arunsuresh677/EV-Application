"""Mock PSP integration. A real deployment uses Stripe/Razorpay/PayU
PSP-hosted fields/SDKs so raw card data never touches our servers (per the
PRD's PCI-DSS scope requirement) — this stands in for that boundary with a
fake token, so the rest of the system (payment_methods/payments tables,
capture flow) can be built and tested against a stable contract now.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db

router = APIRouter(tags=["payments"])


class TokenizeRequest(BaseModel):
    card_number: str
    brand: str = "visa"


class TokenizeResponse(BaseModel):
    psp_token: str
    last4: str


@router.post("/payments/methods/tokenize", response_model=TokenizeResponse)
def tokenize(body: TokenizeRequest, user: dict = Depends(auth.get_current_user)):
    if len(body.card_number) < 4:
        raise HTTPException(status_code=422, detail="card_number too short")
    return TokenizeResponse(psp_token=f"tok_mock_{db.new_id()[:16]}", last4=body.card_number[-4:])


@router.post("/payments/methods")
def save_payment_method(body: TokenizeResponse, user: dict = Depends(auth.get_current_user)):
    method_id = db.new_id()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO payment_methods (id, user_id, psp_token, brand, last4, is_default, created_at)
               VALUES (?, ?, ?, 'visa', ?, 0, ?)""",
            (method_id, user["id"], body.psp_token, body.last4, db.now_iso()),
        )
    return {"id": method_id}


@router.get("/payments/methods")
def list_payment_methods(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    return db.rows_to_list(
        conn.execute(
            "SELECT id, brand, last4, is_default FROM payment_methods WHERE user_id=? ORDER BY is_default DESC, created_at",
            (user["id"],),
        ).fetchall()
    )
