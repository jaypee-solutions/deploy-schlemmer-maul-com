# Migration: schlemmer-maul.de → WooCommerce

Two scripts to migrate the old static website's product catalogue into WordPress/WooCommerce.

## Quick start

```bash
cd migration
uv sync
```

## Step 1 — Scrape the old site

```bash
uv run python scrape.py
```

This creates a `data/` folder tree:

```
data/
  images/                   # downloaded images
  schlemmereien/
    category.yaml
    spirituosen/
      category.yaml
      leichte-schnaepse/
        category.yaml
        waldhimbeerschnaepsle.yaml
        ...
  lagerverkauf/
    category.yaml
    ...
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--out DIR` | `data` | Output directory |

Review and edit the YAML files before importing — add prices, fix descriptions, etc.

## Step 2 — Configure credentials

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```dotenv
WC_URL=https://schlemmer-maul.com
WC_KEY=ck_...           # WooCommerce > Settings > Advanced > REST API
WC_SECRET=cs_...
WP_USER=admin           # WordPress username
WP_APP_PASS=xxxx xxxx   # Users > Application Passwords in WP Admin
```

## Step 3 — Import into WooCommerce

Dry run (no changes):

```bash
uv run python import_woo.py --dry-run
```

Live import:

```bash
uv run python import_woo.py
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--data DIR` | `data` | Data directory to import from |
| `--dry-run` | off | Print actions without calling the API |

The import is **idempotent**: running it again updates existing categories and products rather than creating duplicates (matched by slug).

## YAML formats

### `category.yaml`

```yaml
name: Leichte Schnäpse
slug: leichte-schnaepse
description: ""
image: images/some-image.jpg   # optional, relative to data/
```

### `<product-slug>.yaml`

```yaml
name: Waldhimbeerschnäpsle
slug: waldhimbeerschnaepsle
description: ""
short_description: ""
attributes:
  Alkoholgehalt: "34% Vol."
  Gebindegröße: "0,5 Lt / 1 Lt"
images:
  - images/some-image.jpg            # optional, relative to data/
status: publish                      # publish | draft
```
