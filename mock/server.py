"""Mock merchant world on :8001 — fictional stores, returns portal, checkout, carrier,
plus the user's inbox and bank ledger, and a demo admin panel.

Run: .venv/bin/uvicorn mock.server:app --port 8001 --reload
"""
from __future__ import annotations

import html
import random
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mock import world as W

app = FastAPI(title="Snapback mock merchant world")


@app.get("/static/products/{name}", include_in_schema=False)
def product_image(name: str):
    """Product photos: mock/product_images first (kept outside mock/static), then mock/static/products.
    Registered before the /static mount so it takes precedence."""
    path = W.product_image_path(name)
    if not path:
        raise HTTPException(404, "no such product image")
    return FileResponse(path)


app.mount("/static", StaticFiles(directory=str(W.MOCK / "static")), name="static")
app.mount("/photos", StaticFiles(directory=str(W.PHOTOS)), name="photos")
T = Jinja2Templates(directory=str(W.MOCK / "templates"))

REASONS = [
    ("defective", "Item is defective or stopped working"),
    ("damaged", "Defective / damaged"),
    ("arrived_damaged", "Arrived damaged"),
    ("no_longer_needed", "No longer needed"),
    ("wrong_item", "Wrong item received"),
    ("better_price", "Found a better price"),
]


def _store(store_id: str) -> Dict[str, Any]:
    s = W.stores().get(store_id)
    if not s:
        raise HTTPException(404, "Unknown store")
    return s


def _page(request: Request, name: str, store: Optional[Dict[str, Any]] = None, status_code: int = 200, **ctx):
    return T.TemplateResponse(request, name, {"store": store, "now": W.now(), **ctx}, status_code=status_code)


def _error(request: Request, store, title: str, message: str, status_code: int = 400):
    return _page(request, "error.html", store, status_code=status_code, title=title, message=message)


def _today() -> date:
    return (W.now() - timedelta(hours=8)).date()


def _slug(text: str) -> str:
    text = re.sub(r"^\d+\.\s*", "", text.strip())
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _md_to_html(md: str) -> str:
    out, in_list = [], False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("## "):
            out.append(f'<h2 id="{_slug(line[3:])}">{html.escape(line[3:])}</h2>')
        elif line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line:
            out.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---------------- index + store ----------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _page(request, "index.html", stores=W.stores().values())


@app.get("/s/{store_id}", response_class=HTMLResponse)
def store_home(request: Request, store_id: str):
    store = _store(store_id)
    p = W.prices()
    items = [dict(c, current_price=p.get(c["sku"], c["price"]), image=W.product_image_name(c["sku"]))
             for c in W.catalog().values() if c["store"] == store_id]
    return _page(request, "store.html", store, items=items)


@app.get("/s/{store_id}/policy", response_class=HTMLResponse)
def policy(request: Request, store_id: str):
    store = _store(store_id)
    path = W.MOCK / "policies" / f"{store_id}.md"
    if not path.exists():
        return _error(request, store, "No published policy", "This store has not published a returns policy.", 404)
    return _page(request, "policy.html", store, body=_md_to_html(path.read_text()))


@app.get("/s/{store_id}/reviews", response_class=HTMLResponse)
def reviews(request: Request, store_id: str):
    store = _store(store_id)
    path = W.MOCK / "reviews" / f"{store_id}.md"
    if not path.exists():
        return _error(request, store, "No review summaries", "No review summaries published for this store.", 404)
    return _page(request, "policy.html", store, body=_md_to_html(path.read_text()))


# ---------------- returns portal (order # + ZIP, no login) ----------------

@app.get("/s/{store_id}/returns", response_class=HTMLResponse)
def returns_start(request: Request, store_id: str):
    return _page(request, "returns_lookup.html", _store(store_id))


def _find_order(store_id: str, order_no: str, zip_code: str) -> Optional[Dict[str, Any]]:
    o = W.merchant()["orders"].get(order_no.strip().upper())
    if o and o["store"] == store_id and o["ship_zip"] == zip_code.strip():
        return o
    return None


@app.post("/s/{store_id}/returns/lookup", response_class=HTMLResponse)
def returns_lookup(request: Request, store_id: str, order_no: str = Form(...), zip_code: str = Form(...)):
    store = _store(store_id)
    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return _error(request, store, "Order not found", "We couldn't find an order with that number and ZIP code.", 404)
    if o["status"] != "active":
        existing = next((r for r in W.merchant()["returns"] if r["order_no"] == o["order_no"]), None)
        return _page(request, "returns_confirm.html", store, ret=existing, order=o, already=True)
    if not o["delivered_at"]:
        return _error(request, store, "Not delivered yet",
                      "This order hasn't been delivered. For a late or missing package, contact support.", 409)
    window_open = _today() <= date.fromisoformat(o["return_by"])
    return _page(request, "returns_select.html", store, order=o, reasons=REASONS, window_open=window_open,
                 image=W.product_image_name(o["sku"]))


@app.post("/s/{store_id}/returns/submit", response_class=HTMLResponse)
def returns_submit(request: Request, store_id: str, order_no: str = Form(...), zip_code: str = Form(...),
                   reason: str = Form(...), refund_method: str = Form("original_payment"),
                   idempotency_key: str = Form(""), verified_by: str = Form(""),
                   return_method: str = Form("standard")):
    store = _store(store_id)
    if return_method not in RETURN_METHODS:
        return _error(request, store, "Unknown return method", f"'{return_method}' is not a return method we offer.", 400)
    w = W.world()
    if w.get("fail_next_submit"):
        w["fail_next_submit"] = False
        W.save_world(w)
        return _error(request, store, "Something went wrong", "Our returns service is temporarily unavailable. Please try again.", 503)

    m = W.merchant()
    if idempotency_key:
        dup = next((r for r in m["returns"] if r.get("idempotency_key") == idempotency_key), None)
        if dup:
            return _page(request, "returns_confirm.html", store, ret=dup, order=m["orders"][dup["order_no"]], already=True)

    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return _error(request, store, "Order not found", "We couldn't find an order with that number and ZIP code.", 404)
    if o["status"] != "active":
        return _error(request, store, "Already returned", "A return has already been started for this order.", 409)
    if not o["delivered_at"] or _today() > date.fromisoformat(o["return_by"]):
        return _error(request, store, "Outside the return window",
                      "This order is past its return window. For defects, please file a warranty claim.", 409)

    rules = store["merchant_rules"]
    defective = reason in ("defective", "arrived_damaged", "damaged")
    restocking = 0.0 if defective else round(o["price"] * rules["restocking_pct_non_defective"] / 100, 2)
    shipping = 0.0 if defective else float(rules["return_shipping_non_defective"])
    refund = round(o["price"] - restocking - shipping, 2)
    rma = f"RMA-{store['order_prefix']}-{random.randint(100000, 999999)}"
    ret = {
        "rma": rma, "order_no": o["order_no"], "store": store_id, "sku": o["sku"], "reason": reason,
        "refund_method": refund_method, "restocking_fee": restocking, "return_shipping_fee": shipping,
        "refund_amount": refund, "label_url": f"{W.MERCHANT_BASE_URL}/s/{store_id}/returns/label/{rma}",
        "drop_off_by": (_today() + timedelta(days=7)).isoformat(), "created_at": W.now().isoformat(timespec="seconds"),
        "idempotency_key": idempotency_key or None, "verified_by": verified_by or None,
        "return_method": return_method, "return_method_label": RETURN_METHODS[return_method][0],
        "return_instructions": RETURN_METHODS[return_method][1].format(store=store["name"]),
    }
    m["returns"].append(ret)
    m["orders"][o["order_no"]]["status"] = "return_requested"
    W.save_merchant(m)

    delay = int(w.get("refund_delay_seconds", 10))
    W.add_bank_txn(merchant_name=store["name"], amount=refund, memo=f"Refund {rma} ({o['order_no']})",
                   kind="refund", posts_at=W.now() + timedelta(seconds=delay), ref=rma)
    W.add_inbox_email(
        sender=f"{store['name']} <{store['support_email']}>",
        subject=f"Return {rma} approved for order {o['order_no']}",
        body_text=(f"Your return for {o['name']} (order {o['order_no']}) is approved.\n"
                   f"Return authorization: {rma}\nRefund amount: ${refund:.2f} to your original payment method\n"
                   f"Restocking fee: ${restocking:.2f} · Return shipping: ${shipping:.2f}\n"
                   f"Return method: {ret['return_method_label']}. {ret['return_instructions']}\n"
                   f"{'Print your label' if return_method != 'in_store_dropoff' else 'Your drop-off slip'}: {ret['label_url']}\n"
                   f"Please drop off by {ret['drop_off_by']}."),
        kind="return_confirmation", meta={"rma": rma, "order_no": o["order_no"], "refund_amount": refund,
                                          "return_method": return_method},
    )
    return _page(request, "returns_confirm.html", store, ret=ret, order=o, already=False)


@app.get("/s/{store_id}/returns/label/{rma}", response_class=HTMLResponse)
def return_label(request: Request, store_id: str, rma: str):
    store = _store(store_id)
    ret = next((r for r in W.merchant()["returns"] if r["rma"] == rma), None)
    if not ret:
        return _error(request, store, "Label not found", "No return with that authorization number.", 404)
    return _page(request, "label.html", store, ret=ret)


RETURN_METHODS = {
    "standard": ("Prepaid return label", "Pack the item and drop it at any carrier location."),
    "in_store_dropoff": ("In-store drop-off", "Bring the item to any {store} store; staff seal damaged batteries in a "
                                             "fire-safe bag. Do not mail it."),
    "battery_safe_label": ("Battery-safe return label (UN3481)", "The carrier collects the item in a battery-safe pouch "
                                                                "within 5 business days. Do not use standard mail."),
}


# ---------------- checkout ----------------

@app.get("/s/{store_id}/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, store_id: str, sku: str):
    store = _store(store_id)
    item = W.catalog().get(sku)
    if not item or item["store"] != store_id:
        return _error(request, store, "Item not found", "That item isn't sold here.", 404)
    price = W.prices().get(sku, item["price"])
    return _page(request, "checkout.html", store, item=item, price=price, image=W.product_image_name(sku))


@app.post("/s/{store_id}/checkout", response_class=HTMLResponse)
def checkout_submit(request: Request, store_id: str, sku: str = Form(...), ship_zip: str = Form(...),
                    idempotency_key: str = Form(""), verified_by: str = Form(""), max_price: str = Form("")):
    store = _store(store_id)
    item = W.catalog().get(sku)
    if not item or item["store"] != store_id:
        return _error(request, store, "Item not found", "That item isn't sold here.", 404)
    m = W.merchant()
    if idempotency_key:
        dup = next((p for p in m["purchases"] if p.get("idempotency_key") == idempotency_key), None)
        if dup:
            return _page(request, "checkout_confirm.html", store, purchase=dup, item=item, already=True)
    if not _in_stock(sku):
        return _error(request, store, "Out of stock", f"{item['name']} is currently out of stock.", 409)
    price = float(W.prices().get(sku, item["price"]))
    if max_price and price > float(max_price):
        return _error(request, store, "Price changed", f"The price is now ${price:.2f}, above your limit.", 409)

    order_no = f"{store['order_prefix']}-{random.randint(20000, 99999)}"
    purchase = {
        "order_no": order_no, "store": store_id, "sku": sku, "name": item["name"], "price": price,
        "ship_zip": ship_zip, "created_at": W.now().isoformat(timespec="seconds"),
        "idempotency_key": idempotency_key or None, "verified_by": verified_by or None,
    }
    m["purchases"].append(purchase)
    m["orders"][order_no] = {
        "order_no": order_no, "store": store_id, "sku": sku, "name": item["name"], "price": price, "qty": 1,
        "ship_zip": ship_zip, "ordered_at": purchase["created_at"], "delivered_at": None, "return_by": None,
        "tracking": f"{store['order_prefix']}1Z{random.randint(10000, 99999)}", "carrier_status": "label_created",
        "eta": (_today() + timedelta(days=3)).isoformat(), "status": "active",
    }
    W.save_merchant(m)
    W.add_bank_txn(merchant_name=store["name"], amount=-price, memo=f"{store['name']} order {order_no}",
                   kind="charge", ref=order_no)
    W.add_inbox_email(
        sender=f"{store['name']} <{store['orders_email']}>",
        subject=f"Order confirmation {order_no}",
        body_text=(f"Thanks for your order!\n\nOrder summary\nOrder #: {order_no}\n"
                   f"Order date: {W.now():%B} {W.now().day}, {W.now().year}\nItem: {item['name']} (SKU {sku})\nQty: 1\n"
                   f"Price: ${price:.2f}\nOrder total: ${price:.2f}\nShip to: Alex Moreno, San Francisco, CA {ship_zip}\n"
                   f"Carrier tracking: {m['orders'][order_no]['tracking']}\n"
                   f"Returns: {store['merchant_rules']['return_window_days']} days from delivery\n"
                   f"Estimated delivery: {m['orders'][order_no]['eta']}\n\n{store['name']} · {store['support_email']}"),
        kind="order_confirmation", image=W.product_image_name(sku), meta={"order_no": order_no, "sku": sku, "price": price},
    )
    return _page(request, "checkout_confirm.html", store, purchase=purchase, item=item, already=False)


# ---------------- support API: price adjustment, warranty, missing package ----------------
# Form posts that return JSON (the store's support endpoints). Same order # + ZIP lookup, idempotent.

def _support_dup(kind: str, key: str):
    if not key:
        return None
    return next((c for c in W.merchant()[kind] if c.get("idempotency_key") == key), None)


@app.post("/s/{store_id}/price-adjustment")
def price_adjustment(store_id: str, order_no: str = Form(...), zip_code: str = Form(...),
                     idempotency_key: str = Form(""), verified_by: str = Form("")):
    store = _store(store_id)
    dup = _support_dup("adjustments", idempotency_key)
    if dup:
        return {**dup, "already": True}
    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return JSONResponse({"ok": False, "error": "order_not_found"}, 404)
    rules = store["merchant_rules"]
    if not rules["price_adjustment_days"] or not o["delivered_at"]:
        return JSONResponse({"ok": False, "error": "price_adjustments_not_offered"}, 409)
    until = date.fromisoformat(o["delivered_at"][:10]) + timedelta(days=rules["price_adjustment_days"])
    if _today() > until:
        return JSONResponse({"ok": False, "error": "price_adjustment_window_closed"}, 409)
    current = float(W.prices().get(o["sku"], o["price"]))
    diff = round(o["price"] - current, 2)
    if diff <= 0:
        return JSONResponse({"ok": False, "error": "no_price_drop", "current_price": current}, 409)
    adj_id = f"ADJ-{store['order_prefix']}-{random.randint(10000, 99999)}"
    rec = {"ok": True, "adjustment_id": adj_id, "order_no": o["order_no"], "sku": o["sku"], "paid": o["price"],
           "current_price": current, "amount": diff, "created_at": W.now().isoformat(timespec="seconds"),
           "idempotency_key": idempotency_key or None, "verified_by": verified_by or None}
    m = W.merchant()
    m["adjustments"].append(rec)
    W.save_merchant(m)
    delay = int(W.world().get("refund_delay_seconds", 10))
    W.add_bank_txn(merchant_name=store["name"], amount=diff, memo=f"Price adjustment {adj_id} ({o['order_no']})",
                   kind="adjustment", posts_at=W.now() + timedelta(seconds=delay), ref=adj_id)
    W.add_inbox_email(sender=f"{store['name']} <{store['support_email']}>",
                      subject=f"Price adjustment {adj_id} approved for order {o['order_no']}",
                      body_text=f"We've refunded the ${diff:.2f} difference on {o['name']} (paid ${o['price']:.2f}, now ${current:.2f}) "
                                f"to your original payment method.\nReference: {adj_id}",
                      kind="adjustment_confirmation", meta={"adjustment_id": adj_id, "order_no": o["order_no"], "amount": diff})
    return rec


@app.post("/s/{store_id}/warranty")
def warranty_claim(store_id: str, order_no: str = Form(...), zip_code: str = Form(...), description: str = Form(""),
                   idempotency_key: str = Form(""), verified_by: str = Form("")):
    store = _store(store_id)
    dup = _support_dup("claims", idempotency_key)
    if dup:
        return {**dup, "already": True}
    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return JSONResponse({"ok": False, "error": "order_not_found"}, 404)
    until = date.fromisoformat(o["delivered_at"][:10]) + timedelta(days=store["merchant_rules"]["warranty_days"]) if o["delivered_at"] else None
    if not until or _today() > until:
        return JSONResponse({"ok": False, "error": "warranty_expired"}, 409)
    claim_id = f"WAR-{store['order_prefix']}-{random.randint(10000, 99999)}"
    rec = {"ok": True, "claim_id": claim_id, "type": "warranty", "order_no": o["order_no"], "sku": o["sku"],
           "resolution": "replacement", "ship_by": (_today() + timedelta(days=3)).isoformat(),
           "created_at": W.now().isoformat(timespec="seconds"), "idempotency_key": idempotency_key or None,
           "verified_by": verified_by or None}
    m = W.merchant()
    m["claims"].append(rec)
    m["orders"][o["order_no"]]["status"] = "claimed"
    W.save_merchant(m)
    W.add_inbox_email(sender=f"{store['name']} <{store['support_email']}>",
                      subject=f"Warranty claim {claim_id} approved for order {o['order_no']}",
                      body_text=f"Your warranty claim for {o['name']} is approved. A replacement ships by {rec['ship_by']}.\n"
                                f"Claim: {claim_id}\nReported issue: {description[:200]}",
                      kind="warranty_confirmation", meta={"claim_id": claim_id, "order_no": o["order_no"]})
    return rec


@app.post("/s/{store_id}/claims/missing")
def missing_claim(store_id: str, order_no: str = Form(...), zip_code: str = Form(...),
                  idempotency_key: str = Form(""), verified_by: str = Form("")):
    store = _store(store_id)
    dup = _support_dup("claims", idempotency_key)
    if dup:
        return {**dup, "already": True}
    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return JSONResponse({"ok": False, "error": "order_not_found"}, 404)
    eta_passed = bool(o.get("eta")) and _today() > date.fromisoformat(o["eta"]) + timedelta(days=2)
    if o["carrier_status"] not in ("lost", "exception") and not eta_passed:
        return JSONResponse({"ok": False, "error": "package_not_missing", "carrier_status": o["carrier_status"]}, 409)
    claim_id = f"CLM-{store['order_prefix']}-{random.randint(10000, 99999)}"
    rec = {"ok": True, "claim_id": claim_id, "type": "missing_package", "order_no": o["order_no"], "amount": o["price"],
           "resolution": "refund", "created_at": W.now().isoformat(timespec="seconds"),
           "idempotency_key": idempotency_key or None, "verified_by": verified_by or None}
    m = W.merchant()
    m["claims"].append(rec)
    m["orders"][o["order_no"]]["status"] = "claimed"
    W.save_merchant(m)
    delay = int(W.world().get("refund_delay_seconds", 10))
    W.add_bank_txn(merchant_name=store["name"], amount=o["price"], memo=f"Refund {claim_id} lost package ({o['order_no']})",
                   kind="claim_credit", posts_at=W.now() + timedelta(seconds=delay), ref=claim_id)
    W.add_inbox_email(sender=f"{store['name']} <{store['support_email']}>",
                      subject=f"Claim {claim_id}: refund for your missing package ({o['order_no']})",
                      body_text=f"The carrier could not locate your {o['name']}. We're refunding ${o['price']:.2f} "
                                f"to your original payment method.\nClaim: {claim_id}",
                      kind="claim_confirmation", meta={"claim_id": claim_id, "order_no": o["order_no"], "amount": o["price"]})
    return rec


@app.post("/s/{store_id}/orders/cancel")
def cancel_order(store_id: str, order_no: str = Form(...), zip_code: str = Form(...),
                 idempotency_key: str = Form(""), verified_by: str = Form("")):
    """Cancel an order that hasn't been delivered yet (full refund)."""
    store = _store(store_id)
    dup = _support_dup("claims", idempotency_key)
    if dup:
        return {**dup, "already": True}
    o = _find_order(store_id, order_no, zip_code)
    if not o:
        return JSONResponse({"ok": False, "error": "order_not_found"}, 404)
    if o["delivered_at"]:
        return JSONResponse({"ok": False, "error": "already_delivered_return_instead"}, 409)
    if o["status"] != "active":
        return JSONResponse({"ok": False, "error": f"order_{o['status']}"}, 409)
    cancel_id = f"CXL-{store['order_prefix']}-{random.randint(10000, 99999)}"
    rec = {"ok": True, "claim_id": cancel_id, "type": "cancellation", "order_no": o["order_no"], "amount": o["price"],
           "created_at": W.now().isoformat(timespec="seconds"), "idempotency_key": idempotency_key or None,
           "verified_by": verified_by or None}
    m = W.merchant()
    m["claims"].append(rec)
    m["orders"][o["order_no"]]["status"] = "cancelled"
    W.save_merchant(m)
    delay = int(W.world().get("refund_delay_seconds", 10))
    W.add_bank_txn(merchant_name=store["name"], amount=o["price"], memo=f"Refund {cancel_id} cancelled order {o['order_no']}",
                   kind="refund", posts_at=W.now() + timedelta(seconds=delay), ref=cancel_id)
    W.add_inbox_email(sender=f"{store['name']} <{store['support_email']}>",
                      subject=f"Order {o['order_no']} cancelled ({cancel_id})",
                      body_text=f"Your order {o['order_no']} for {o['name']} was cancelled before shipping. "
                                f"${o['price']:.2f} will be refunded to your original payment method.\nReference: {cancel_id}",
                      kind="cancel_confirmation", meta={"claim_id": cancel_id, "order_no": o["order_no"], "amount": o["price"]})
    return rec


# ---------------- JSON APIs: prices + carrier ----------------

def _in_stock(sku: str) -> bool:
    item = W.catalog().get(sku) or {}
    return bool(item.get("in_stock", True)) and sku not in (W.world().get("out_of_stock") or [])


@app.get("/s/{store_id}/api/price/{sku}")
def api_price(store_id: str, sku: str):
    item = W.catalog().get(sku)
    if not item or item["store"] != store_id:
        raise HTTPException(404, "Unknown SKU")
    return {"store": store_id, "sku": sku, "price": W.prices().get(sku, item["price"]),
            "in_stock": _in_stock(sku), "as_of": W.now().isoformat(timespec="seconds"),
            "url": f"{W.MERCHANT_BASE_URL}/s/{store_id}/checkout?sku={sku}"}


@app.get("/carrier/track/{tracking}")
def carrier_track(tracking: str):
    o = next((o for o in W.merchant()["orders"].values() if o["tracking"] == tracking), None)
    if not o:
        raise HTTPException(404, "Unknown tracking number")
    status = o["carrier_status"]
    events = [{"status": "label_created", "at": o["ordered_at"]}]
    if status in ("in_transit", "lost", "exception", "delivered"):
        events.append({"status": "in_transit", "at": o["ordered_at"]})
    if status == "delivered":
        events.append({"status": "delivered", "at": o["delivered_at"]})
    if status in ("lost", "exception"):
        events.append({"status": status, "at": W.now().isoformat(timespec="seconds"),
                       "detail": "Package could not be located at the last facility scan."})
    return {"tracking": tracking, "status": status, "eta": o.get("eta"), "events": events,
            "url": f"{W.MERCHANT_BASE_URL}/carrier/track/{tracking}"}


# ---------------- the user's inbox + bank ----------------

def _emails():
    import json
    out = [json.loads(p.read_text()) for p in W.INBOX.glob("*.json")]
    return sorted(out, key=lambda e: e["received_at"], reverse=True)


@app.get("/api/inbox")
def api_inbox():
    return _emails()


# ---------------- calendar (drop-off reminder fallback) ----------------

@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request):
    return T.TemplateResponse(request, "calendar.html", {})


@app.get("/calendar/events.json")
def calendar_events_json():
    return W.calendar_events()


@app.post("/calendar/events")
async def calendar_add(request: Request):
    body = await request.json()
    try:
        start, end = datetime.fromisoformat(body["start"]), datetime.fromisoformat(body["end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "start and end must be ISO datetimes")
    if not body.get("title") or end <= start:
        raise HTTPException(400, "title required and end must be after start")
    ev, already = W.add_calendar_event({
        "task_id": body.get("task_id"), "title": str(body["title"])[:200], "notes": str(body.get("notes") or "")[:2000],
        "location": str(body.get("location") or "")[:200], "calendar": body.get("calendar") or "Snapback",
        "start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes"),
        "alarm_minutes_before": int(body.get("alarm_minutes_before") or 0)})
    return {**ev, "already": already, "url": f"{W.MERCHANT_BASE_URL}/calendar?date={ev['start'][:10]}#{ev['event_id']}"}


@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request):
    return _page(request, "inbox.html", emails=_emails())


@app.get("/inbox/{email_id}", response_class=HTMLResponse)
def inbox_email(request: Request, email_id: str):
    e = next((e for e in _emails() if e["email_id"] == email_id), None)
    if not e:
        raise HTTPException(404, "No such email")
    return _page(request, "email.html", email=e)


@app.get("/api/bank/transactions")
def api_bank():
    return W.posted_bank_txns()


@app.get("/bank", response_class=HTMLResponse)
def bank_page(request: Request):
    txns = sorted(W.posted_bank_txns(), key=lambda t: t["posts_at"], reverse=True)
    pending = [t for t in W.bank() if t not in txns]
    return _page(request, "bank.html", txns=txns, pending=pending)


# ---------------- demo admin ----------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return _page(request, "admin.html", world=W.world(), prices=W.prices(), catalog=W.catalog(),
                 orders=W.merchant()["orders"].values())


@app.get("/api/world")
def api_world():
    return {**W.world(), "now": W.now().isoformat(timespec="seconds")}


@app.post("/admin/price")
def admin_price(sku: str = Form(...), price: float = Form(...)):
    p = W.prices()
    p[sku] = round(price, 2)
    W.save_prices(p)
    return RedirectResponse("/admin", 303)


@app.post("/admin/carrier")
def admin_carrier(tracking: str = Form(...), status: str = Form(...)):
    m = W.merchant()
    for o in m["orders"].values():
        if o["tracking"] == tracking:
            o["carrier_status"] = status
    W.save_merchant(m)
    return RedirectResponse("/admin", 303)


@app.post("/admin/clock")
def admin_clock(hours: float = Form(...)):
    w = W.world()
    w["clock_offset_hours"] = float(w.get("clock_offset_hours", 0)) + hours
    W.save_world(w)
    return RedirectResponse("/admin", 303)


@app.post("/admin/refund-delay")
def admin_refund_delay(seconds: int = Form(...)):
    w = W.world()
    w["refund_delay_seconds"] = seconds
    W.save_world(w)
    return RedirectResponse("/admin", 303)


@app.post("/admin/fail-next")
def admin_fail_next():
    w = W.world()
    w["fail_next_submit"] = not w.get("fail_next_submit", False)
    W.save_world(w)
    return RedirectResponse("/admin", 303)


@app.post("/admin/stock")
def admin_stock(sku: str = Form(...), in_stock: str = Form("false")):
    w = W.world()
    oos = set(w.get("out_of_stock") or [])
    (oos.discard if in_stock.lower() in ("1", "true", "yes") else oos.add)(sku)
    w["out_of_stock"] = sorted(oos)
    W.save_world(w)
    return {"ok": True, "out_of_stock": w["out_of_stock"]}


@app.post("/admin/reset")
def admin_reset(stage: str = Form("yes")):
    W.reset_world(stage_demo=(stage == "yes"))
    return RedirectResponse("/admin", 303)
