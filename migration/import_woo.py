#!/usr/bin/env python3
"""
Import a local product folder tree into WordPress/WooCommerce.

Reads the folder structure produced by scrape.py and:
  1. Creates WooCommerce product categories (respecting hierarchy).
  2. Uploads images via the WordPress Media REST API.
  3. Creates or updates WooCommerce products.

Configuration (environment variables or .env file next to this script):
    WC_URL       Base URL of the WordPress site, e.g. https://schlemmer-maul.com
    WC_KEY       WooCommerce REST API consumer key  (ck_…)
    WC_SECRET    WooCommerce REST API consumer secret (cs_…)
    WP_USER      WordPress username (needed for media upload)
    WP_APP_PASS  WordPress application password (needed for media upload)
    DATA_DIR     Path to the data folder (default: data)

Usage:
    pip install -r requirements.txt
    # copy .env.example to .env and fill in credentials
    python import_woo.py [--data data] [--dry-run]
"""

import argparse
import mimetypes
import os
import sys
from pathlib import Path

import requests
import yaml
from woocommerce import API as WooAPI

# ── configuration ─────────────────────────────────────────────────────────────


def load_env() -> None:
    """Load a .env file from the script directory if present."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_config() -> dict:
    load_env()
    required = ["WC_URL", "WC_KEY", "WC_SECRET", "WP_USER", "WP_APP_PASS"]
    cfg: dict = {}
    missing: list[str] = []
    for key in required:
        val = os.environ.get(key, "")
        if not val:
            missing.append(key)
        cfg[key] = val
    if missing:
        print("ERROR: Missing required environment variables:", ", ".join(missing), file=sys.stderr)
        print("Set them in a .env file or export them before running.", file=sys.stderr)
        sys.exit(1)
    cfg["DATA_DIR"] = os.environ.get("DATA_DIR", "data")
    return cfg


# ── WordPress Media API ────────────────────────────────────────────────────────


class MediaUploader:
    """Upload images to WordPress media library."""

    def __init__(self, wp_url: str, user: str, app_pass: str, dry_run: bool = False) -> None:
        self.base = wp_url.rstrip("/")
        self.auth = (user, app_pass)
        self.dry_run = dry_run
        self._cache: dict[str, int] = {}  # filename → media id

    def _existing_id(self, filename: str) -> int | None:
        """Check if a media item with this filename already exists."""
        resp = requests.get(
            f"{self.base}/wp-json/wp/v2/media",
            params={"search": filename, "per_page": 5},
            auth=self.auth,
            timeout=15,
        )
        if resp.ok:
            for item in resp.json():
                if item.get("slug", "") == Path(filename).stem.lower().replace(" ", "-"):
                    return item["id"]
                src = item.get("source_url", "")
                if Path(src).name == filename:
                    return item["id"]
        return None

    def upload(self, image_path: Path) -> int | None:
        """Upload *image_path* and return the WordPress media ID."""
        filename = image_path.name
        if filename in self._cache:
            return self._cache[filename]

        existing = self._existing_id(filename)
        if existing:
            print(f"    [media] reuse existing id={existing} for {filename}")
            self._cache[filename] = existing
            return existing

        if self.dry_run:
            print(f"    [media] DRY-RUN: would upload {filename}")
            return None

        mime, _ = mimetypes.guess_type(filename)
        mime = mime or "application/octet-stream"
        try:
            with image_path.open("rb") as fh:
                resp = requests.post(
                    f"{self.base}/wp-json/wp/v2/media",
                    auth=self.auth,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                    files={"file": (filename, fh, mime)},
                    timeout=60,
                )
            resp.raise_for_status()
            media_id = resp.json()["id"]
            print(f"    [media] uploaded {filename} → id={media_id}")
            self._cache[filename] = media_id
            return media_id
        except Exception as exc:  # noqa: BLE001
            print(f"    [media] ERROR uploading {filename}: {exc}", file=sys.stderr)
            return None


# ── category helpers ──────────────────────────────────────────────────────────


def load_category_tree(data_dir: Path) -> list[tuple[Path, dict]]:
    """
    Walk data_dir and return all category folders sorted by depth (parents first).
    Returns list of (folder_path, category_data) tuples.
    """
    cats: list[tuple[Path, dict]] = []
    for yaml_file in sorted(data_dir.rglob("category.yaml")):
        folder = yaml_file.parent
        with yaml_file.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        cats.append((folder, data))
    # Sort by depth so parents are created before children
    cats.sort(key=lambda x: len(x[0].relative_to(data_dir).parts))
    return cats


def ensure_category(
    wc: WooAPI,
    cat_data: dict,
    parent_id: int,
    uploader: MediaUploader,
    data_dir: Path,
    folder: Path,
    slug_to_id: dict[str, int],
    dry_run: bool,
) -> int | None:
    slug = cat_data.get("slug", "")
    name = cat_data.get("name", slug)

    # Check if already exists
    resp = wc.get("products/categories", params={"slug": slug, "per_page": 1})
    if resp.status_code == 200 and resp.json():
        wc_id = resp.json()[0]["id"]
        print(f"  [cat] exists: {name} (id={wc_id})")
        slug_to_id[slug] = wc_id
        return wc_id

    # Upload image if present
    image_payload: dict | None = None
    if image_rel := cat_data.get("image"):
        image_abs = (data_dir / image_rel).resolve()
        if image_abs.exists():
            media_id = uploader.upload(image_abs)
            if media_id:
                image_payload = {"id": media_id}

    payload: dict = {
        "name": name,
        "slug": slug,
        "description": cat_data.get("description", ""),
        "parent": parent_id,
    }
    if image_payload:
        payload["image"] = image_payload

    if dry_run:
        print(f"  [cat] DRY-RUN: would create '{name}' (parent_id={parent_id})")
        return None

    resp = wc.post("products/categories", payload)
    if resp.status_code in (200, 201):
        wc_id = resp.json()["id"]
        print(f"  [cat] created: {name} (id={wc_id})")
        slug_to_id[slug] = wc_id
        return wc_id
    else:
        print(f"  [cat] ERROR creating '{name}': {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        return None


# ── product helpers ───────────────────────────────────────────────────────────


def load_products(data_dir: Path) -> list[tuple[Path, dict]]:
    """Return all product YAML files (everything except category.yaml)."""
    products: list[tuple[Path, dict]] = []
    for yaml_file in sorted(data_dir.rglob("*.yaml")):
        if yaml_file.name == "category.yaml":
            continue
        with yaml_file.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        products.append((yaml_file, data))
    return products


def build_attributes_payload(attributes: dict) -> list[dict]:
    return [
        {"name": key, "options": [str(val)], "visible": True}
        for key, val in attributes.items()
    ]


def ensure_product(
    wc: WooAPI,
    product_file: Path,
    product_data: dict,
    slug_to_id: dict[str, int],
    uploader: MediaUploader,
    data_dir: Path,
    dry_run: bool,
) -> bool:
    slug = product_data.get("slug", "")
    name = product_data.get("name", slug)

    # Resolve parent category from folder name
    cat_folder_slug = product_file.parent.name
    cat_id = slug_to_id.get(cat_folder_slug)
    if cat_id is None:
        # Try parent category by matching folder name to any slug
        for s, i in slug_to_id.items():
            if s == cat_folder_slug:
                cat_id = i
                break

    # Upload images
    image_ids: list[dict] = []
    for image_rel in product_data.get("images", []):
        image_abs = (data_dir / image_rel).resolve()
        if image_abs.exists():
            media_id = uploader.upload(image_abs)
            if media_id:
                image_ids.append({"id": media_id})

    # Build payload
    payload: dict = {
        "name": name,
        "slug": slug,
        "status": product_data.get("status", "publish"),
        "type": "simple",
        "description": product_data.get("description", ""),
        "short_description": product_data.get("short_description", ""),
        "categories": [{"id": cat_id}] if cat_id else [],
        "images": image_ids,
    }
    if attrs := product_data.get("attributes"):
        payload["attributes"] = build_attributes_payload(attrs)

    if dry_run:
        print(f"  [prod] DRY-RUN: would upsert '{name}' in cat_id={cat_id}")
        return True

    # Check for existing product
    resp = wc.get("products", params={"slug": slug, "per_page": 1})
    if resp.status_code == 200 and resp.json():
        existing_id = resp.json()[0]["id"]
        resp2 = wc.put(f"products/{existing_id}", payload)
        if resp2.status_code in (200, 201):
            print(f"  [prod] updated: {name} (id={existing_id})")
            return True
        else:
            print(f"  [prod] ERROR updating '{name}': {resp2.status_code} {resp2.text[:200]}", file=sys.stderr)
            return False
    else:
        resp2 = wc.post("products", payload)
        if resp2.status_code in (200, 201):
            print(f"  [prod] created: {name} (id={resp2.json()['id']})")
            return True
        else:
            print(f"  [prod] ERROR creating '{name}': {resp2.status_code} {resp2.text[:200]}", file=sys.stderr)
            return False


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Import product data into WooCommerce")
    parser.add_argument("--data", default=None, help="Path to data directory")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without calling the API")
    args = parser.parse_args()

    cfg = get_config()
    data_dir = Path(args.data or cfg["DATA_DIR"])

    if not data_dir.is_dir():
        print(f"ERROR: data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    dry_run: bool = args.dry_run
    if dry_run:
        print("=== DRY RUN — no changes will be made ===\n")

    wc = WooAPI(
        url=cfg["WC_URL"],
        consumer_key=cfg["WC_KEY"],
        consumer_secret=cfg["WC_SECRET"],
        wp_api=True,
        version="wc/v3",
        timeout=30,
    )

    uploader = MediaUploader(
        wp_url=cfg["WC_URL"],
        user=cfg["WP_USER"],
        app_pass=cfg["WP_APP_PASS"],
        dry_run=dry_run,
    )

    # ── Phase 1: categories ────────────────────────────────────────────────
    print("=== Phase 1: Categories ===")
    slug_to_id: dict[str, int] = {}
    cat_errors: list[str] = []

    for folder, cat_data in load_category_tree(data_dir):
        rel = folder.relative_to(data_dir)
        # Parent slug = parent folder name (or 0 for top-level)
        parent_slug = rel.parent.name if len(rel.parts) > 1 else ""
        parent_id = slug_to_id.get(parent_slug, 0)

        wc_id = ensure_category(
            wc=wc,
            cat_data=cat_data,
            parent_id=parent_id,
            uploader=uploader,
            data_dir=data_dir,
            folder=folder,
            slug_to_id=slug_to_id,
            dry_run=dry_run,
        )
        if wc_id is None and not dry_run:
            cat_errors.append(cat_data.get("slug", str(folder)))

    # ── Phase 2: products ──────────────────────────────────────────────────
    print("\n=== Phase 2: Products ===")
    prod_errors: list[str] = []

    for product_file, product_data in load_products(data_dir):
        ok = ensure_product(
            wc=wc,
            product_file=product_file,
            product_data=product_data,
            slug_to_id=slug_to_id,
            uploader=uploader,
            data_dir=data_dir,
            dry_run=dry_run,
        )
        if not ok and not dry_run:
            prod_errors.append(product_data.get("slug", str(product_file)))

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n=== Summary ===")
    if cat_errors:
        print(f"  Category errors ({len(cat_errors)}): {', '.join(cat_errors)}")
    if prod_errors:
        print(f"  Product errors ({len(prod_errors)}): {', '.join(prod_errors)}")
    if not cat_errors and not prod_errors:
        print("  All done — no errors.")


if __name__ == "__main__":
    main()
