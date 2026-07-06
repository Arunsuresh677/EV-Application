"""Mock PSP integration. A real deployment uses Stripe/Razorpay/PayU
PSP-hosted fields/SDKs so raw card data never touches our servers (per the
PRD's PCI-DSS scope requirement) — this stands in for that boundary with a
fake token, so the rest of the system (payment_methods/payments tables,
capture flow) can be built and tested against a stable contract now.
"""
from __future__ import annotations

import sqlite3

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


@router.post("/payments/methods", status_code=201)
def save_payment_method(body: TokenizeResponse, user: dict = Depends(auth.get_current_user)):
    method_id = db.new_id()
    with db.transaction() as c:
        # A driver's very first card becomes the default automatically —
        # otherwise a freshly self-registered driver would have no way to
        # actually pay for a session without a separate "set default" step.
        is_first = c.execute("SELECT COUNT(*) AS n FROM payment_methods WHERE user_id=?", (user["id"],)).fetchone()["n"] == 0
        c.execute(
            """INSERT INTO payment_methods (id, user_id, psp_token, brand, last4, is_default, created_at)
               VALUES (?, ?, ?, 'visa', ?, ?, ?)""",
            (method_id, user["id"], body.psp_token, body.last4, 1 if is_first else 0, db.now_iso()),
        )
    return db.row_to_dict(db.get_conn().execute("SELECT id, brand, last4, is_default FROM payment_methods WHERE id=?", (method_id,)).fetchone())


@router.get("/payments/methods")
def list_payment_methods(user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    return db.rows_to_list(
        conn.execute(
            "SELECT id, brand, last4, is_default FROM payment_methods WHERE user_id=? ORDER BY is_default DESC, created_at",
            (user["id"],),
        ).fetchall()
    )


@router.post("/payments/methods/{method_id}/default")
def set_default_payment_method(method_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    method = db.row_to_dict(conn.execute("SELECT id FROM payment_methods WHERE id=? AND user_id=?", (method_id, user["id"])).fetchone())
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    with db.transaction() as c:
        c.execute("UPDATE payment_methods SET is_default=0 WHERE user_id=?", (user["id"],))
        c.execute("UPDATE payment_methods SET is_default=1 WHERE id=?", (method_id,))
    return {"status": "ok"}


@router.delete("/payments/methods/{method_id}", status_code=204)
def delete_payment_method(method_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    method = db.row_to_dict(conn.execute("SELECT * FROM payment_methods WHERE id=? AND user_id=?", (method_id, user["id"])).fetchone())
    if method is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    try:
        with db.transaction() as c:
            c.execute("DELETE FROM payment_methods WHERE id=?", (method_id,))
            # If we just deleted the default, promote the next-oldest one so
            # the driver isn't silently left without a way to pay.
            if method["is_default"]:
                next_method = db.row_to_dict(
                    c.execute("SELECT id FROM payment_methods WHERE user_id=? ORDER BY created_at LIMIT 1", (user["id"],)).fetchone()
                )
                if next_method:
                    c.execute("UPDATE payment_methods SET is_default=1 WHERE id=?", (next_method["id"],))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="This payment method has charge history and can't be deleted")
