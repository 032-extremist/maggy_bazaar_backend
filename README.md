# Ecommerce Backend Setup

This folder contains the Flask API for the Maggy Bazaar ecommerce site. The frontend is deployed separately from `../frontend`.

## 1. Create the Postgres database

```powershell
createdb ecommerce
psql -d ecommerce -f ..\database\schema_postgres.sql
```

If your Postgres username, password, host, or database name is different, update `DATABASE_URL`.

## 2. Install the Python dependency

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Configure environment variables

Copy `.env.example` to `.env`, then set the values for your machine. PowerShell can also set them for the current terminal:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ecommerce"
$env:SECRET_KEY="replace-with-a-long-random-secret"
```

## 4. Run the backend

```powershell
python app.py
```

The API runs at `http://localhost:5000`. Frontend pages are served from `../frontend`.

## Main API Routes

- `GET /api/health`
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/me`
- `GET /api/products`
- `GET /api/products/{id}`
- `POST /api/products`
- `GET /api/cart`
- `POST /api/cart`
- `PUT /api/cart/{cart_item_id}`
- `DELETE /api/cart/{cart_item_id}`
- `GET /api/wishlist`
- `POST /api/wishlist`
- `DELETE /api/wishlist/{product_id}`
- `GET /api/orders`
- `GET /api/orders/{id}`
- `POST /api/orders`
- `GET /api/reviews?product_id=1`
- `POST /api/reviews`
- `GET /api/messages`
- `POST /api/messages`
- `GET /api/addresses`
- `POST /api/addresses`
- `GET /api/payment-methods`
- `POST /api/payment-methods`

Protected endpoints require:

```http
Authorization: Bearer your-token-from-login
```
