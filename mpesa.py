import requests
import base64
import json
from datetime import datetime
from flask import Blueprint, request, jsonify

# ─────────────────────────────────────────────
#  YOUR DARAJA SANDBOX CREDENTIALS
# ─────────────────────────────────────────────
MPESA_CONSUMER_KEY    = "L5avjCX8DBHvXdLmq2pksRcki4sTfGhnvGF0nBZAI3tHh3kK"
MPESA_CONSUMER_SECRET = "QhxDszdrlcbVEwZpAAHLhfyrbAYfSj1Oa4qIkmvlqEUCMyhPLtH6Woj43WDA0DYe"
MPESA_SHORTCODE       = "174379"
MPESA_PASSKEY         = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
MPESA_CALLBACK_URL = "https://maggy-bazaar-backend.onrender.com/api/mpesa/callback"

TOKEN_URL    = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"


def get_access_token():
    creds = base64.b64encode(
        f"{MPESA_CONSUMER_KEY}:{MPESA_CONSUMER_SECRET}".encode()
    ).decode()
    res = requests.get(TOKEN_URL, headers={"Authorization": f"Basic {creds}"}, timeout=10)
    res.raise_for_status()
    return res.json()["access_token"]


def get_password_and_timestamp():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw       = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}"
    password  = base64.b64encode(raw.encode()).decode()
    return password, timestamp


def register_mpesa_routes(app, get_db_connection, DbError):

    @app.route("/api/mpesa/stkpush", methods=["POST"])
    def mpesa_stkpush():
        data     = request.get_json(silent=True) or {}
        phone    = str(data.get("phone", "")).strip()
        amount   = data.get("amount")
        order_id = data.get("order_id")
        email    = (data.get("email") or "").strip().lower()
        shipping = data.get("shipping") or {}   # shipping details from frontend

        # ── Validate ──
        if not phone or not amount:
            return jsonify({"error": "Phone and amount are required"}), 400

        try:
            amount = int(float(amount))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid amount"}), 400

        if amount < 1:
            return jsonify({"error": "Amount must be at least KES 1"}), 400

        if not phone.startswith("254") or len(phone) != 12:
            return jsonify({"error": "Phone must be in format 2547XXXXXXXX"}), 400

        # ── Get token ──
        try:
            token = get_access_token()
        except Exception as e:
            print(f"[MPESA] Token error: {e}")
            return jsonify({"error": "Could not connect to M-Pesa. Try again."}), 503

        # ── Build STK push request ──
        password, timestamp = get_password_and_timestamp()
        payload = {
            "BusinessShortCode": MPESA_SHORTCODE,
            "Password":          password,
            "Timestamp":         timestamp,
            "TransactionType":   "CustomerPayBillOnline",
            "Amount":            amount,
            "PartyA":            phone,
            "PartyB":            MPESA_SHORTCODE,
            "PhoneNumber":       phone,
            "CallBackURL":       MPESA_CALLBACK_URL,
            "AccountReference":  f"Order-{order_id or 'CART'}",
            "TransactionDesc":   "E-commerce payment",
        }

        try:
            res      = requests.post(
                STK_PUSH_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            res_data = res.json()
        except Exception as e:
            print(f"[MPESA] STK push error: {e}")
            return jsonify({"error": "Payment request failed. Try again."}), 503

        if res_data.get("ResponseCode") != "0":
            msg = res_data.get("ResponseDescription", "STK push failed")
            return jsonify({"error": msg}), 400

        # ── Save pending transaction + shipping details to DB ──
        checkout_request_id = res_data.get("CheckoutRequestID")
        conn = cursor = None
        try:
            conn   = get_db_connection()
            cursor = conn.cursor()

            # Store shipping as JSON string in mpesa_transactions
            shipping_json = json.dumps(shipping) if shipping else None

            cursor.execute(
                """
                INSERT INTO mpesa_transactions
                    (checkout_request_id, phone, amount, order_id, email, status, shipping_details)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s)
                ON CONFLICT (checkout_request_id) DO UPDATE
                SET status = 'pending', shipping_details = EXCLUDED.shipping_details
                """,
                (checkout_request_id, phone, amount, order_id, email, shipping_json),
            )
            conn.commit()
        except DbError as e:
            print(f"[MPESA] DB error saving transaction: {e}")
        finally:
            if cursor: cursor.close()
            if conn:   conn.close()

        return jsonify(res_data), 200


    @app.route("/api/mpesa/status", methods=["GET"])
    def mpesa_status():
        checkout_request_id = request.args.get("checkout_request_id", "").strip()
        if not checkout_request_id:
            return jsonify({"error": "checkout_request_id required"}), 400

        conn = cursor = None
        try:
            conn   = get_db_connection(dict_cursor=True)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, mpesa_receipt FROM mpesa_transactions WHERE checkout_request_id = %s",
                (checkout_request_id,),
            )
            row = cursor.fetchone()
        except DbError as e:
            print(f"[MPESA] DB status error: {e}")
            return jsonify({"status": "pending"}), 200
        finally:
            if cursor: cursor.close()
            if conn:   conn.close()

        if not row:
            return jsonify({"status": "pending"}), 200

        return jsonify({
            "status":  row["status"],
            "receipt": row.get("mpesa_receipt"),
        }), 200


    @app.route("/api/mpesa/callback", methods=["POST"])
    def mpesa_callback():
        body = request.get_json(silent=True) or {}

        try:
            stk_callback        = body["Body"]["stkCallback"]
            checkout_request_id = stk_callback["CheckoutRequestID"]
            result_code         = stk_callback["ResultCode"]

            if result_code == 0:
                # Payment successful
                items   = stk_callback.get("CallbackMetadata", {}).get("Item", [])
                meta    = {item["Name"]: item.get("Value") for item in items}
                receipt = meta.get("MpesaReceiptNumber")

                conn = cursor = None
                try:
                    conn   = get_db_connection(dict_cursor=True)
                    cursor = conn.cursor()

                    # 1. Mark transaction as success and fetch stored data
                    cursor.execute(
                        """
                        UPDATE mpesa_transactions
                        SET status = 'success', mpesa_receipt = %s
                        WHERE checkout_request_id = %s
                        """,
                        (receipt, checkout_request_id),
                    )

                    # 2. Fetch email and shipping details saved during STK push
                    cursor.execute(
                        "SELECT email, shipping_details FROM mpesa_transactions WHERE checkout_request_id = %s",
                        (checkout_request_id,),
                    )
                    row      = cursor.fetchone()
                    email    = (row or {}).get("email", "")
                    shipping_json = (row or {}).get("shipping_details")

                    shipping = {}
                    if shipping_json:
                        try:
                            shipping = json.loads(shipping_json)
                        except (ValueError, TypeError):
                            shipping = {}

                    if email:
                        # 3. Get user_id
                        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                        user_row = cursor.fetchone()
                        user_id  = (user_row or {}).get("id")

                        if user_id:
                            # 4. Fetch cart items
                            cursor.execute(
                                """
                                SELECT ci.product_id, ci.quantity, p.price
                                FROM cart_items ci
                                JOIN products p ON p.id = ci.product_id
                                WHERE ci.user_id = %s
                                """,
                                (user_id,),
                            )
                            cart_items = cursor.fetchall()

                            if cart_items:
                                # 5. Create order
                                cursor.execute(
                                    "INSERT INTO orders (user_id, status) VALUES (%s, %s) RETURNING id",
                                    (user_id, "processing"),
                                )
                                order_id = cursor.fetchone()["id"]

                                # 6. Insert order items
                                for item in cart_items:
                                    cursor.execute(
                                        """
                                        INSERT INTO order_items
                                            (order_id, product_id, quantity, price)
                                        VALUES (%s, %s, %s, %s)
                                        """,
                                        (order_id, item["product_id"], item["quantity"], item["price"]),
                                    )

                                # 7. Save shipping details if provided
                                if shipping.get("full_name"):
                                    cursor.execute(
                                        """
                                        INSERT INTO shipping_details
                                            (order_id, full_name, phone, county, town, drop_station, address)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                        """,
                                        (
                                            order_id,
                                            shipping.get("full_name"),
                                            shipping.get("phone"),
                                            shipping.get("county"),
                                            shipping.get("town"),
                                            shipping.get("drop_station"),
                                            shipping.get("address"),
                                        ),
                                    )

                                # 8. Clear the cart
                                cursor.execute(
                                    "DELETE FROM cart_items WHERE user_id = %s", (user_id,)
                                )

                                print(f"[MPESA] Order {order_id} created for {email}, cart cleared.")

                    conn.commit()

                except DbError as e:
                    print(f"[MPESA] DB callback success error: {e}")
                finally:
                    if cursor: cursor.close()
                    if conn:   conn.close()

            else:
                # Payment failed/cancelled
                conn = cursor = None
                try:
                    conn   = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE mpesa_transactions SET status = 'failed' WHERE checkout_request_id = %s",
                        (checkout_request_id,),
                    )
                    conn.commit()
                except DbError as e:
                    print(f"[MPESA] DB callback failed error: {e}")
                finally:
                    if cursor: cursor.close()
                    if conn:   conn.close()

        except (KeyError, TypeError) as e:
            print(f"[MPESA] Callback parse error: {e}")

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
