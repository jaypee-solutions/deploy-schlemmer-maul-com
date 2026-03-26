#!/usr/bin/env python3
"""
Scrape schlemmer-maul.de and write a local product folder tree.

Each category becomes a folder containing category.yaml.
Each product becomes a <slug>.yaml file inside its category folder.
Images are downloaded to data/images/.

Usage:
    uv sync
    uv run migration/scrape.py [--out data]
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

SITE_ROOT = "http://www.schlemmer-maul.de"
ENCODING = "iso-8859-1"

# Maps local folder path (relative to data/) → page URL path on the old site.
# Intermediate category nodes without their own page are created as folders only.
PAGES: dict[str, str] = {
    "lagerverkauf": "/HTML/lager.html",
    "geschenksideen": "/HTML/laden.html",
    "schlemmereien/spirituosen/leichte-schnaepse": "/HTML/produkte/schnaepse/fruchtige.html",
    "schlemmereien/spirituosen/edle-schnaepse": "/HTML/produkte/schnaepse/edle.html",
    "schlemmereien/spirituosen/alte-schnaepse": "/HTML/produkte/schnaepse/alte.html",
    "schlemmereien/spirituosen/likoere": "/HTML/produkte/schnaepse/likoere.html",
    "schlemmereien/kaese": "/HTML/produkte/kaese.html",
    "schlemmereien/fruchtaufstriche": "/HTML/produkte/marmelade.html",
    "schlemmereien/sirup": "/HTML/produkte/sirup.html",
}

# Intermediate categories (no dedicated page, name derived from slug)
INTERMEDIATE_NAMES: dict[str, str] = {
    "schlemmereien": "Schlemmereien",
    "schlemmereien/spirituosen": "Spirituosen",
}


# ── helpers ──────────────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe ASCII kebab-case slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=15)
    resp.encoding = ENCODING
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def download_image(url: str, dest: Path) -> bool:
    """Download *url* to *dest*. Returns True if downloaded, False if skipped."""
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        print(f"  [img] {dest.name}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [img] WARN: could not download {url}: {exc}", file=sys.stderr)
        return False


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)


def relative_image_path(product_dir: Path, images_dir: Path, filename: str) -> str:
    """Return a relative path string from product_dir to images_dir/filename."""
    abs_image = images_dir / filename
    return str(abs_image.relative_to(product_dir.parent))


# ── parsing helpers ───────────────────────────────────────────────────────────


_RE_ALCOHOL = re.compile(r"(\d+(?:[,.]\d+)?\s*%\s*Vol\.?)", re.IGNORECASE)
_RE_VOLUME = re.compile(
    r"(\d+(?:[,.]\d+)?(?:\s*/\s*\d+(?:[,.]\d+)?)?\s*(?:Lt|ml|cl|g|kg))",
    re.IGNORECASE,
)


def parse_product_line(raw: str) -> dict | None:
    """
    Parse a product list-item string like:
        'Waldhimbeerschnäpsle (34% Vol. - 0,5/1 Lt)'
    Returns a product dict or None if the line looks empty.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Split name from spec parenthetical
    if "(" in raw:
        name_part, spec_part = raw.split("(", 1)
        spec_part = spec_part.rstrip(")")
    else:
        name_part = raw
        spec_part = ""

    name = name_part.strip().rstrip("-").strip()
    if not name:
        return None

    attributes: dict[str, str] = {}
    if alcohol := _RE_ALCOHOL.search(spec_part):
        attributes["Alkoholgehalt"] = alcohol.group(1).strip()
    if volume := _RE_VOLUME.search(spec_part):
        attributes["Gebindegröße"] = volume.group(1).strip()

    product: dict = {
        "name": name,
        "slug": slugify(name),
        "description": "",
        "images": [],
        "status": "publish",
    }
    if attributes:
        product["attributes"] = attributes
    return product


def extract_description(soup: BeautifulSoup) -> str:
    """Pull plain-text paragraphs from #textbereich that precede any <ul>."""
    content = soup.select_one("#textbereich")
    if not content:
        return ""
    parts: list[str] = []
    for tag in content.children:
        if hasattr(tag, "name"):
            if tag.name in ("ul", "div") and tag.find("li"):
                break
            if tag.name in ("p", "h2", "h3", "h4"):
                text = tag.get_text(" ", strip=True)
                if text:
                    parts.append(text)
    return " ".join(parts)


def extract_images(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Return absolute image URLs from .schnapsbild / .schnapsbild2 / #textbereich img."""
    imgs: list[str] = []
    for img in soup.select("#textbereich img"):
        src = img.get("src", "")
        if src:
            imgs.append(urljoin(page_url, src))
    return imgs


def extract_products(soup: BeautifulSoup) -> list[dict]:
    """Extract all products from the page as parsed dicts."""
    products: list[dict] = []
    for li in soup.select("#textbereich li"):
        text = li.get_text(" ", strip=True)
        product = parse_product_line(text)
        if product:
            products.append(product)
    return products


# ── main scraping logic ───────────────────────────────────────────────────────


def scrape_page(folder_path: str, page_path: str, data_dir: Path) -> None:
    url = SITE_ROOT + page_path
    print(f"Fetching {url} → {folder_path}/")
    try:
        soup = fetch(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {exc}", file=sys.stderr)
        return

    cat_dir = data_dir / folder_path
    images_dir = data_dir / "images"

    # ── category name ──────────────────────────────────────────────────────
    h1 = soup.select_one("#textbereich h1")
    cat_name = h1.get_text(strip=True) if h1 else folder_path.split("/")[-1]

    # ── category description ───────────────────────────────────────────────
    description = extract_description(soup)

    # ── images ────────────────────────────────────────────────────────────
    image_urls = extract_images(soup, url)
    cat_image_key: str | None = None
    downloaded_images: list[str] = []

    for img_url in image_urls:
        # Derive a filename from the URL
        raw_name = img_url.split("/")[-1].split("?")[0]
        # Keep original filename but prefix with category slug for uniqueness
        filename = raw_name
        dest = images_dir / filename
        download_image(img_url, dest)
        rel = str((images_dir / filename).relative_to(data_dir))
        downloaded_images.append(rel)
        if cat_image_key is None:
            cat_image_key = rel

    # ── write category.yaml ────────────────────────────────────────────────
    cat_data: dict = {
        "name": cat_name,
        "slug": slugify(cat_name),
        "description": description,
    }
    if cat_image_key:
        cat_data["image"] = cat_image_key

    write_yaml(cat_dir / "category.yaml", cat_data)

    # ── products ───────────────────────────────────────────────────────────
    products = extract_products(soup)
    if not products:
        print(f"  (no products found on this page)")
        return

    # Assign images to products: first downloaded image goes to the first product, etc.
    for i, product in enumerate(products):
        if i < len(downloaded_images):
            product["images"] = [downloaded_images[i]]

        slug = product["slug"]
        write_yaml(cat_dir / f"{slug}.yaml", product)

    print(f"  → {len(products)} product(s) written")


def create_intermediate_categories(data_dir: Path) -> None:
    """Create category.yaml for intermediate nodes that have no dedicated page."""
    for folder_path, name in INTERMEDIATE_NAMES.items():
        cat_dir = data_dir / folder_path
        yaml_path = cat_dir / "category.yaml"
        if yaml_path.exists():
            continue
        cat_data = {
            "name": name,
            "slug": slugify(name),
            "description": "",
        }
        write_yaml(yaml_path, cat_data)
        print(f"Created intermediate category: {folder_path}/category.yaml")


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape schlemmer-maul.de into local YAML tree")
    parser.add_argument("--out", default="data", help="Output directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.out)
    data_dir.mkdir(parents=True, exist_ok=True)

    create_intermediate_categories(data_dir)

    for folder_path, page_path in PAGES.items():
        scrape_page(folder_path, page_path, data_dir)

    print("\nDone. Review the files in:", data_dir.resolve())


if __name__ == "__main__":
    main()
