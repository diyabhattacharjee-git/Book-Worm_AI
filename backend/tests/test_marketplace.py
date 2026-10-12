import io

from PIL import Image

from tests.conftest import book_id_by_title

LISTING = {"title": "Atomic Habits", "author": "James Clear", "isbn": "9780735211292", "condition": "good",
           "price_amount": 199, "currency": "INR", "delivery": "both", "shipping_cost": 40,
           "location_city": "Kolkata", "description": "Clean copy with a few highlighted lines."}


def _png(size=(40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buf, "PNG")
    return buf.getvalue()


def test_create_and_link_listing(user_client, db):
    c, _ = user_client
    r = c.post("/api/marketplace/listings", json=LISTING)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["book_id"] == book_id_by_title(db, "Atomic Habits")
    assert body["total_known_cost"] == 239 and body["total_cost_complete"] is True
    assert c.get("/api/users/me").json()["is_seller"] is True
    # Identical active listing is rejected
    assert c.post("/api/marketplace/listings", json=LISTING).status_code == 409


def test_listing_validation(user_client):
    c, _ = user_client
    assert c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 0}).status_code == 422
    assert c.post("/api/marketplace/listings", json={**LISTING, "isbn": "1234567890123"}).status_code == 422
    assert c.post("/api/marketplace/listings", json={**LISTING, "delivery": "pickup", "shipping_cost": 30}).status_code == 422
    assert c.post("/api/marketplace/listings", json={**LISTING, "currency": "XYZ"}).status_code == 422


def test_other_users_cannot_modify_listing(user_client, other_client):
    c, _ = user_client
    o, _ = other_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 205}).json()["id"]
    assert o.patch(f"/api/marketplace/listings/{lid}", json={"price_amount": 1}).status_code == 403
    assert o.delete(f"/api/marketplace/listings/{lid}").status_code == 403
    assert o.post(f"/api/marketplace/listings/{lid}/mark-sold").status_code == 403
    assert o.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("a.png", _png(), "image/png")}).status_code == 403
    assert c.get(f"/api/marketplace/listings/{lid}").json()["listing"]["price_amount"] == 205


def test_status_lifecycle(user_client):
    c, _ = user_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 210}).json()["id"]
    assert c.post(f"/api/marketplace/listings/{lid}/deactivate").json()["status"] == "inactive"
    assert c.post(f"/api/marketplace/listings/{lid}/reactivate").json()["status"] == "active"
    sold = c.post(f"/api/marketplace/listings/{lid}/mark-sold").json()
    assert sold["status"] == "sold" and sold["sold_at"]
    assert c.patch(f"/api/marketplace/listings/{lid}", json={"price_amount": 99}).status_code == 409
    ids = [x["id"] for x in c.get("/api/marketplace/listings", params={"q": "atomic habits"}).json()["items"]]
    assert lid not in ids, "sold listings are hidden from browsing"
    assert c.delete(f"/api/marketplace/listings/{lid}").status_code == 204


def test_location_privacy(user_client, other_client):
    c, _ = user_client
    o, _ = other_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 215, "location_public": False}).json()["id"]
    assert o.get(f"/api/marketplace/listings/{lid}").json()["listing"]["location_city"] is None
    assert c.get(f"/api/marketplace/listings/{lid}").json()["listing"]["location_city"] == "Kolkata"


def test_image_upload_validation(user_client, tmp_path):
    c, _ = user_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 220}).json()["id"]
    r = c.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("cover.png", _png(), "image/png")})
    assert r.status_code == 201 and len(r.json()["images"]) == 1
    url = r.json()["images"][0]["url"]
    assert url.startswith("/uploads/listings/") and url.endswith(".png")
    fake = b"<script>alert(1)</script>" + b"0" * 100
    assert c.post(f"/api/marketplace/listings/{lid}/images",
                  files={"file": ("evil.png", fake, "image/png")}).status_code == 415
    from app.core.config import get_settings

    big = b"0" * int(get_settings().max_upload_mb * 1024 * 1024 + 10)
    assert c.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("big.jpg", big, "image/jpeg")}).status_code == 413
    img_id = r.json()["images"][0]["id"]
    assert c.delete(f"/api/marketplace/listings/{lid}/images/{img_id}").json()["images"] == []


def test_favorites_inquiries_and_reports(user_client, other_client):
    seller, _ = user_client
    buyer, _ = other_client
    lid = seller.post("/api/marketplace/listings", json={**LISTING, "price_amount": 225}).json()["id"]
    assert buyer.post(f"/api/marketplace/listings/{lid}/favorite").status_code == 204
    assert [f["id"] for f in buyer.get("/api/marketplace/favorites").json()] == [lid]
    r = buyer.post(f"/api/marketplace/listings/{lid}/inquiries", json={"message": "Is this still available?"})
    assert r.status_code == 201
    iid = r.json()["id"]
    assert seller.post(f"/api/marketplace/listings/{lid}/inquiries", json={"message": "talking to myself"}).status_code == 400
    assert buyer.post(f"/api/marketplace/inquiries/{iid}/reply", json={"reply": "hijack"}).status_code == 403
    reply = seller.post(f"/api/marketplace/inquiries/{iid}/reply", json={"reply": "Yes! Pickup near Park Street."}).json()
    assert reply["status"] == "answered"
    mine = buyer.get("/api/marketplace/inquiries?role=buyer").json()
    assert mine[0]["seller_reply"].startswith("Yes")
    assert buyer.post(f"/api/marketplace/listings/{lid}/report", json={"reason": "misleading"}).status_code == 201
    assert seller.post(f"/api/marketplace/listings/{lid}/report", json={"reason": "spam"}).status_code == 400
    dash = seller.get("/api/marketplace/seller-dashboard").json()
    assert dash["open_inquiries"] == 0 and any(lst["id"] == lid for lst in dash["listings"])
    assert dash["listings"][0]["inquiry_count"] is not None  # owner-only stats present


def test_browse_filters_and_public_seller_profile(client, user_client):
    c, info = user_client
    c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 230, "condition": "like_new"})
    r = client.get("/api/marketplace/listings", params={"min_condition": "very_good", "sort": "price_asc"}).json()
    assert all(x["condition"] in ("like_new", "very_good") for x in r["items"])
    prices = [x["price_amount"] for x in r["items"]]
    assert prices == sorted(prices)
    prof = client.get(f"/api/marketplace/sellers/{info['id']}").json()
    assert "email" not in prof["seller"] and prof["seller"]["active_listings"] >= 1


def test_sample_listings_are_labelled(client):
    items = client.get("/api/marketplace/listings", params={"page_size": 60}).json()["items"]
    assert any(x["is_sample"] for x in items)
    assert all(x["seller"]["is_demo"] for x in items if x["is_sample"])


def test_cloudinary_storage_when_configured(user_client, monkeypatch):
    """With CLOUDINARY_URL set, photos go to Cloudinary over HTTPS (signed) and the URL is stored."""
    import hashlib

    import httpx

    from app.core.config import get_settings
    from app.services import uploads

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append((url, data, files))
        if url.endswith("/image/upload"):
            return httpx.Response(200, json={"secure_url": f"https://res.cloudinary.com/demo/image/upload/v1/{data['public_id']}.png"})
        return httpx.Response(200, json={"result": "ok"})

    monkeypatch.setattr(get_settings(), "cloudinary_url", "cloudinary://key123:secret456@democloud")
    monkeypatch.setattr(uploads.httpx, "post", fake_post)
    c, _ = user_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 245}).json()["id"]
    r = c.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("a.png", _png(), "image/png")})
    assert r.status_code == 201
    url = r.json()["images"][0]["url"]
    assert url.startswith("https://res.cloudinary.com/demo/image/upload/v1/bookworm/listings/")
    upload_url, form, _files = calls[0]
    assert upload_url == "https://api.cloudinary.com/v1_1/democloud/image/upload"
    expected = hashlib.sha1(f"public_id={form['public_id']}&timestamp={form['timestamp']}secret456".encode()).hexdigest()
    assert form["signature"] == expected and form["api_key"] == "key123" and "api_secret" not in form
    img_id = r.json()["images"][0]["id"]
    c.delete(f"/api/marketplace/listings/{lid}/images/{img_id}")
    assert calls[-1][0].endswith("/image/destroy") and calls[-1][1]["public_id"] == form["public_id"]


def test_database_image_storage(user_client, monkeypatch):
    """IMAGE_STORAGE=database (automatic on Vercel) keeps photos in the database and serves them from /api/media/."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "image_storage", "database")
    c, _ = user_client
    lid = c.post("/api/marketplace/listings", json={**LISTING, "price_amount": 265}).json()["id"]
    r = c.post(f"/api/marketplace/listings/{lid}/images", files={"file": ("a.png", _png(), "image/png")})
    assert r.status_code == 201
    url = r.json()["images"][0]["url"]
    assert url.startswith("/api/media/listings/") and url.endswith(".png")
    img = c.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG") and "sandbox" in img.headers["content-security-policy"]
    img_id = r.json()["images"][0]["id"]
    c.delete(f"/api/marketplace/listings/{lid}/images/{img_id}")
    assert c.get(url).status_code == 404


def test_auto_image_storage_uses_database_on_vercel(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "image_storage", "auto")
    monkeypatch.delenv("VERCEL", raising=False)
    assert s.image_backend == "local"
    monkeypatch.setenv("VERCEL", "1")
    assert s.image_backend == "database"


def test_upload_dir_moves_to_tmp_on_vercel(monkeypatch):
    """Vercel's disk is read-only except /tmp, whatever UPLOAD_DIR says (a crash at import otherwise)."""
    from app.core.config import Settings

    monkeypatch.setenv("VERCEL", "1")
    assert Settings(upload_dir="./uploads").upload_dir == "/tmp/bookworm-uploads"
    assert Settings(upload_dir="/tmp/photos").upload_dir.replace("\\", "/").endswith("/tmp/photos")
