"""The simulated outside world: merchants' systems, the user's inbox and bank ledger.

Snapback's backend never reads merchant state directly. It sees the world only through:
  - the user's inbox (mock/emails/inbox/*.json)
  - the user's bank ledger (served by the merchant server at /api/bank/transactions)
  - merchant web pages / JSON APIs on :8001
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

MOCK = Path(__file__).resolve().parent
STATE = MOCK / "state"
INBOX = MOCK / "emails" / "inbox"
PRODUCTS = MOCK / "static" / "products"
PHOTOS = MOCK / "photos"
PRICES_FILE = MOCK / "prices.json"
MERCHANT_BASE_URL = "http://localhost:8001"

_lock = threading.RLock()


# ---------- small JSON state helpers ----------

def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def world() -> Dict[str, Any]:
    return _read(STATE / "world.json", {"clock_offset_hours": 0, "refund_delay_seconds": 10, "fail_next_submit": False})


def save_world(w: Dict[str, Any]) -> None:
    _write(STATE / "world.json", w)


def now() -> datetime:
    return datetime.utcnow() + timedelta(hours=float(world().get("clock_offset_hours", 0)))


def merchant() -> Dict[str, Any]:
    return _read(STATE / "merchant.json", {"orders": {}, "returns": [], "purchases": [], "claims": [], "adjustments": []})


def save_merchant(m: Dict[str, Any]) -> None:
    _write(STATE / "merchant.json", m)


def bank() -> List[Dict[str, Any]]:
    return _read(STATE / "bank.json", [])


def save_bank(b: List[Dict[str, Any]]) -> None:
    _write(STATE / "bank.json", b)


def prices() -> Dict[str, float]:
    return _read(PRICES_FILE, {})


def save_prices(p: Dict[str, float]) -> None:
    _write(PRICES_FILE, p)


def stores() -> Dict[str, Dict[str, Any]]:
    return {s["id"]: s for s in json.loads((MOCK / "stores" / "stores.json").read_text())}


def catalog() -> Dict[str, Dict[str, Any]]:
    return {c["sku"]: c for c in json.loads((MOCK / "stores" / "catalog.json").read_text())}


def seed_spec() -> Dict[str, Any]:
    return yaml.safe_load((MOCK / "emails" / "orders.yaml").read_text())


def product_image_name(sku: str) -> str:
    """Prefer a real photo (<sku>.jpg) if the team dropped one in; else the generated card."""
    base = sku.lower()
    for ext in (".jpg", ".jpeg", ".png"):
        if (PRODUCTS / f"{base}{ext}").exists() and ext != ".png":
            return f"{base}{ext}"
    return f"{base}.png"


# ---------- inbox + bank writers (used by the merchant server at runtime) ----------

def add_inbox_email(*, sender: str, subject: str, body_text: str, kind: str,
                    received_at: Optional[datetime] = None, image: Optional[str] = None,
                    meta: Optional[Dict[str, Any]] = None, email_id: Optional[str] = None) -> Dict[str, Any]:
    email_id = email_id or f"m-{uuid.uuid4().hex[:10]}"
    received_at = received_at or now()
    email = {
        "email_id": email_id,
        "from": sender,
        "to": "alex.moreno@mail.example",
        "subject": subject,
        "received_at": received_at.isoformat(timespec="seconds"),
        "kind": kind,
        "body_text": body_text,
        "image": image,
        "image_url": f"{MERCHANT_BASE_URL}/static/products/{image}" if image else None,
        "url": f"{MERCHANT_BASE_URL}/inbox/{email_id}",
        "meta": meta or {},
    }
    with _lock:
        _write(INBOX / f"{email_id}.json", email)
    return email


def add_bank_txn(*, merchant_name: str, amount: float, memo: str, kind: str,
                 posts_at: Optional[datetime] = None, ref: Optional[str] = None) -> Dict[str, Any]:
    txn = {
        "txn_id": f"t-{uuid.uuid4().hex[:10]}",
        "merchant": merchant_name,
        "amount": round(amount, 2),   # negative = charge, positive = refund/credit
        "memo": memo,
        "kind": kind,                 # charge | refund | adjustment | claim_credit
        "ref": ref,
        "created_at": now().isoformat(timespec="seconds"),
        "posts_at": (posts_at or now()).isoformat(timespec="seconds"),
    }
    with _lock:
        b = bank()
        b.append(txn)
        save_bank(b)
    return txn


def posted_bank_txns() -> List[Dict[str, Any]]:
    t = now().isoformat(timespec="seconds")
    return [x for x in bank() if x["posts_at"] <= t]


# ---------- product image generation (fictional product cards) ----------

def _font(size: int):
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _glyph(d, category: str, color, cx: int = 320, cy: int = 280, crack: bool = False) -> None:
    w = 14
    if category == "headphones":
        d.arc([cx - 150, cy - 170, cx + 150, cy + 130], 190, 350, fill=color, width=w + 6)
        d.rounded_rectangle([cx - 175, cy - 20, cx - 105, cy + 110], 24, fill=color)
        d.rounded_rectangle([cx + 105, cy - 20, cx + 175, cy + 110], 24, fill=color)
    elif category == "earbuds":
        for dx in (-80, 80):
            d.ellipse([cx + dx - 45, cy - 60, cx + dx + 45, cy + 30], fill=color)
            d.rounded_rectangle([cx + dx - 14, cy, cx + dx + 14, cy + 120], 12, fill=color)
    elif category == "speakers":
        for dx in (-95, 95):
            d.rounded_rectangle([cx + dx - 75, cy - 120, cx + dx + 75, cy + 120], 18, outline=color, width=w)
            d.ellipse([cx + dx - 45, cy - 10, cx + dx + 45, cy + 80], outline=color, width=w)
            d.ellipse([cx + dx - 18, cy - 90, cx + dx + 18, cy - 54], fill=color)
    elif category == "blender":
        d.polygon([(cx - 90, cy - 150), (cx + 90, cy - 150), (cx + 60, cy + 60), (cx - 60, cy + 60)], outline=color, width=w)
        d.rounded_rectangle([cx - 100, cy + 60, cx + 100, cy + 150], 16, fill=color)
    elif category == "kettle":
        d.ellipse([cx - 120, cy - 100, cx + 120, cy + 140], outline=color, width=w)
        d.line([(cx + 110, cy - 10), (cx + 190, cy - 110)], fill=color, width=w)
        d.arc([cx - 90, cy - 190, cx + 90, cy - 40], 180, 360, fill=color, width=w)
    elif category == "toaster":
        d.rounded_rectangle([cx - 160, cy - 80, cx + 160, cy + 130], 40, outline=color, width=w)
        d.rounded_rectangle([cx - 110, cy - 95, cx - 20, cy - 70], 8, fill=color)
        d.rounded_rectangle([cx + 20, cy - 95, cx + 110, cy - 70], 8, fill=color)
    elif category == "jacket":
        d.polygon([(cx - 70, cy - 160), (cx + 70, cy - 160), (cx + 170, cy - 60), (cx + 130, cy + 20),
                   (cx + 100, cy - 10), (cx + 100, cy + 150), (cx - 100, cy + 150), (cx - 100, cy - 10),
                   (cx - 130, cy + 20), (cx - 170, cy - 60)], outline=color, width=w)
        d.line([(cx, cy - 150), (cx, cy + 150)], fill=color, width=8)
    elif category == "bottle":
        d.rounded_rectangle([cx - 60, cy - 110, cx + 60, cy + 160], 30, outline=color, width=w)
        d.rounded_rectangle([cx - 35, cy - 170, cx + 35, cy - 110], 10, fill=color)
    elif category == "tent":
        d.polygon([(cx, cy - 160), (cx + 200, cy + 130), (cx - 200, cy + 130)], outline=color, width=w)
        d.polygon([(cx, cy - 40), (cx + 50, cy + 130), (cx - 50, cy + 130)], fill=color)
    elif category == "lamp":
        d.line([(cx - 60, cy + 140), (cx + 20, cy - 20), (cx - 40, cy - 110)], fill=color, width=w)
        d.polygon([(cx - 40, cy - 150), (cx + 90, cy - 90), (cx - 10, cy - 30)], fill=color)
        d.rounded_rectangle([cx - 120, cy + 130, cx + 0, cy + 155], 10, fill=color)
    else:
        d.rounded_rectangle([cx - 130, cy - 130, cx + 130, cy + 130], 30, outline=color, width=w)
    if crack:
        d.line([(cx - 40, cy - 160), (cx - 10, cy - 110), (cx - 35, cy - 80), (cx + 5, cy - 30)], fill=(200, 30, 30), width=9)


def generate_product_images(force: bool = False) -> None:
    from PIL import Image, ImageDraw
    PRODUCTS.mkdir(parents=True, exist_ok=True)
    st = stores()
    for sku, item in catalog().items():
        out = PRODUCTS / f"{sku.lower()}.png"
        if out.exists() and not force:
            continue
        store = st[item["store"]]
        base = _hex(store["color"])
        bg = tuple(int(c + (255 - c) * 0.88) for c in base)
        img = Image.new("RGB", (640, 640), bg)
        d = ImageDraw.Draw(img)
        _glyph(d, item["category"], base)
        d.text((40, 500), store["name"].upper(), font=_font(22), fill=base)
        d.text((40, 535), item["name"], font=_font(34), fill=(30, 30, 30))
        img.save(out)


def generate_demo_photo() -> None:
    """Placeholder 'photo of broken headphones' for mock mode. Replace with a real photo
    (mock/photos/demo_broken_headphones.jpg) for real SIE matching."""
    from PIL import Image, ImageDraw
    PHOTOS.mkdir(parents=True, exist_ok=True)
    out = PHOTOS / "demo_broken_headphones.png"
    if not out.exists():
        img = Image.new("RGB", (640, 640), (214, 210, 204))
        d = ImageDraw.Draw(img)
        _glyph(d, "headphones", (58, 58, 64), cx=330, cy=300, crack=True)
        img.save(out)
    # Sidecar label used ONLY by the mock embedder (honestly labeled as mock in the audit log).
    _write(PHOTOS / "labels.json", {
        "demo_broken_headphones.png": {"ref": "NWA-ARC-ANC", "similar": {"NWA-STUDIO-MH": 0.45, "NWA-PULSE-EB": 0.2}},
        "demo_broken_headphones.jpg": {"ref": "NWA-ARC-ANC", "similar": {"NWA-STUDIO-MH": 0.45, "NWA-PULSE-EB": 0.2}},
    })


# ---------- email rendering ----------

def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%B %-d, %Y")


def _render_order_email(o: Dict[str, Any], customer: Dict[str, Any], today: datetime) -> Dict[str, Any]:
    st = stores()[o["store"]]
    item = catalog()[o["sku"]]
    rules = st["merchant_rules"]
    omit = set(o.get("omit_fields") or [])
    ordered_at = today - timedelta(days=o["ordered_days_ago"])
    delivered = o.get("delivered_days_ago")
    delivered_at = today - timedelta(days=delivered) if delivered is not None else None

    lines = [f"Hi {customer['name'].split()[0]},", ""]
    if delivered_at:
        subject = f"Delivered: your {st['name']} order {o['order_no']}"
        lines.append(f"Good news, your {st['name']} order was delivered on {_fmt_date(delivered_at)}.")
        received_at = delivered_at.replace(hour=21, minute=12, second=0, microsecond=0)
    else:
        shipped_at = today - timedelta(days=o.get("shipped_days_ago", 1))
        eta = today - timedelta(days=o.get("eta_days_ago", 0))
        subject = f"Shipped: your {st['name']} order {o['order_no']} is on its way"
        lines.append(f"Your {st['name']} order shipped on {_fmt_date(shipped_at)}. Estimated delivery: {_fmt_date(eta)}.")
        received_at = shipped_at.replace(hour=17, minute=40, second=0, microsecond=0)
    lines += [
        "",
        "Order summary",
        f"Order #: {o['order_no']}",
        f"Order date: {_fmt_date(ordered_at)}",
        f"Item: {item['name']} (SKU {o['sku']})",
        "Qty: 1",
        f"Price: ${o['price']:.2f}",
        f"Order total: ${o['price']:.2f}",
    ]
    if "ship_zip" not in omit:
        lines.append(f"Ship to: {customer['name']}, {customer['city']} {customer['zip']}")
    else:
        lines.append(f"Ship to: {customer['name']}")
    lines.append(f"Carrier tracking: {o['tracking']}")
    if delivered_at:
        return_by = delivered_at + timedelta(days=rules["return_window_days"])
        lines.append(f"Return by: {_fmt_date(return_by)} ({rules['return_window_days']} days from delivery)")
    else:
        lines.append(f"Returns: {rules['return_window_days']} days from delivery")
    lines += ["", f"Start a return or check your order: {MERCHANT_BASE_URL}/s/{o['store']}/returns"]
    if o.get("injection"):
        lines += ["", o["injection"]]
    lines += ["", f"Thanks for shopping with {st['name']}.", f"{st['name']} · {st['support_email']}"]

    image = product_image_name(o["sku"])
    return dict(
        email_id=o["id"], sender=f"{st['name']} <{st['orders_email']}>", subject=subject,
        body_text="\n".join(lines), kind="order", received_at=received_at, image=image,
        meta={"seed_scenario": o.get("scenario", "")},
    )


# ---------- reset / staging ----------

def reset_world(stage_demo: bool = True, refund_delay_seconds: int = 10) -> Dict[str, Any]:
    with _lock:
        shutil.rmtree(STATE, ignore_errors=True)
        shutil.rmtree(INBOX, ignore_errors=True)
        STATE.mkdir(parents=True, exist_ok=True)
        INBOX.mkdir(parents=True, exist_ok=True)

        save_world({"clock_offset_hours": 0, "refund_delay_seconds": refund_delay_seconds, "fail_next_submit": False})
        generate_product_images()
        generate_demo_photo()

        spec = seed_spec()
        customer = spec["customer"]
        cat = catalog()
        st = stores()
        today = now()

        save_prices({sku: item["price"] for sku, item in cat.items()})
        m = {"orders": {}, "returns": [], "purchases": [], "claims": [], "adjustments": []}
        save_bank([])

        for o in spec["orders"]:
            e = _render_order_email(o, customer, today)
            add_inbox_email(**e)
            rules = st[o["store"]]["merchant_rules"]
            delivered_at = today - timedelta(days=o["delivered_days_ago"]) if o.get("delivered_days_ago") is not None else None
            ordered_at = today - timedelta(days=o["ordered_days_ago"])
            m["orders"][o["order_no"]] = {
                "order_no": o["order_no"], "store": o["store"], "sku": o["sku"], "name": cat[o["sku"]]["name"],
                "price": o["price"], "qty": 1, "ship_zip": customer["zip"],
                "ordered_at": ordered_at.isoformat(timespec="seconds"),
                "delivered_at": delivered_at.isoformat(timespec="seconds") if delivered_at else None,
                "return_by": (delivered_at + timedelta(days=rules["return_window_days"])).date().isoformat() if delivered_at else None,
                "tracking": o["tracking"], "carrier_status": o["carrier_status"],
                "eta": (today - timedelta(days=o.get("eta_days_ago", 0))).date().isoformat() if not delivered_at else None,
                "status": "active",
            }
            add_bank_txn(merchant_name=st[o["store"]]["name"], amount=-o["price"],
                         memo=f"{st[o['store']]['name']} order {o['order_no']}", kind="charge",
                         posts_at=ordered_at, ref=o["order_no"])
        save_merchant(m)
        if stage_demo:
            stage(spec.get("demo_staging") or {})
        return {"orders": len(m["orders"]), "emails": len(list(INBOX.glob('*.json'))), "staged": stage_demo}


def stage(staging: Dict[str, Any]) -> None:
    with _lock:
        p = prices()
        p.update(staging.get("prices") or {})
        save_prices(p)
        m = merchant()
        for tracking, status in (staging.get("carrier_status") or {}).items():
            for order in m["orders"].values():
                if order["tracking"] == tracking:
                    order["carrier_status"] = status
        save_merchant(m)
