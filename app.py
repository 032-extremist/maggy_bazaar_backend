from flask import Flask, request, jsonify, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import uuid
import psycopg2
from psycopg2 import Error, errorcodes
from psycopg2.extras import RealDictCursor
import cloudinary
import cloudinary.uploader

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

# Ensure uploads folder exists
UPLOADS_DIR = BASE_DIR / 'uploads'
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ecommerce")


def get_db_connection(dict_cursor=False):
    if dict_cursor:
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return psycopg2.connect(DATABASE_URL)


def password_errors(password):
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not any(char.islower() for char in password):
        errors.append("one lowercase letter")
    if not any(char.isupper() for char in password):
        errors.append("one uppercase letter")
    if not any(char.isdigit() for char in password):
        errors.append("one number")
    if not any(not char.isalnum() for char in password):
        errors.append("one special character")
    return errors


def ensure_profile_image_table():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS user_profile_image ("
            "user_id INT PRIMARY KEY, "
            "image_path VARCHAR(255), "
            "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)"
        )
        conn.commit()
    except psycopg2.Error:
        pass
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


ensure_profile_image_table()


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = make_response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


@app.route("/")
def index():
    return jsonify({"status": "ok", "service": "maggy-bazaar-backend"})


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(str(UPLOADS_DIR), filename)


@app.route("/api/products", methods=["GET"])
def get_products():
    conn = None
    cursor = None
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, brand, name, price, description, image,
                   category, subcategory, stock, created_at
            FROM products
            ORDER BY id
        """)
        products = cursor.fetchall()
        return jsonify(products)
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, brand, name, price, description, image,
                   category, subcategory, stock, created_at
            FROM products
            WHERE id = %s
            """,
            (product_id,),
        )
        product = cursor.fetchone()
        if not product:
            return jsonify({"error": "Product not found."}), 404
        return jsonify(product)
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()



@app.route("/api/products/<int:product_id>/related", methods=["GET"])
def get_related_products(product_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()

        cursor.execute("SELECT category FROM products WHERE id = %s", (product_id,))
        current = cursor.fetchone()
        if not current:
            return jsonify([])

        cursor.execute(
            """
            SELECT id, name, brand, price, image
            FROM products
            WHERE category = %s AND id != %s
            ORDER BY RANDOM()
            LIMIT 4
            """,
            (current["category"], product_id),
        )
        return jsonify(cursor.fetchall())
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()















@app.route("/api/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or request.form or {}
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")
    first_name = payload.get("firstName", "").strip() or payload.get("first_name", "").strip()
    last_name = payload.get("lastName", "").strip() or payload.get("last_name", "").strip()
    phone = payload.get("phone", "").strip()

    if not email or not password or not first_name or not last_name or not phone:
        return jsonify({"error": "All fields are required."}), 400

    errors = password_errors(password)
    if errors:
        return jsonify({"error": "Password must include " + ", ".join(errors) + "."}), 400

    hashed_password = generate_password_hash(password)
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"error": "Email already registered."}), 400

        cursor.execute(
            "INSERT INTO users (first_name, last_name, email, phone, password_hash) VALUES (%s, %s, %s, %s, %s)",
            (first_name, last_name, email, phone, hashed_password),
        )
        conn.commit()
        return jsonify({"message": "Account created successfully."})
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or request.form or {}
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")

    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, first_name, last_name, email, phone, password_hash, is_admin FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid email or password."}), 401

        return jsonify({
            "message": "Login successful.",
            "user": {
                "firstName": user["first_name"],
                "lastName": user["last_name"],
                "email": user["email"],
                "phone": user["phone"],
                "isAdmin": bool(user["is_admin"]),
            },
        })
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


def get_user_id(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


@app.route("/api/cart/add", methods=["POST"])
def add_to_cart():
    payload = request.get_json() or {}
    email = payload.get("email", "").strip().lower()
    product_id = payload.get("productId")
    quantity = int(payload.get("quantity", 1))

    if not email or not product_id:
        return jsonify({"error": "Email and product ID are required."}), 400

    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Product not found."}), 404

        cursor.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, product_id) DO UPDATE SET "
            "quantity = cart_items.quantity + EXCLUDED.quantity, "
            "updated_at = CURRENT_TIMESTAMP",
            (user_id, product_id, quantity),
        )
        conn.commit()
        return jsonify({"message": "Product added to cart."})
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()




@app.route("/api/user/<string:email>/profile-image", methods=["POST"])
def upload_profile_image(email):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    user_id = get_user_id(email.strip().lower())
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        result = cloudinary.uploader.upload(file)
        image_url = result["secure_url"]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_profile_image (user_id, image_path) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET image_path = EXCLUDED.image_path",
            (user_id, image_url),
        )
        conn.commit()
        return jsonify({"imageUrl": image_url})
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass




@app.route("/api/admin/products/<int:id>", methods=["PUT"])
def admin_update_product(id):
    data = request.json or {}
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE products
            SET brand = %s, name = %s, price = %s, description = %s,
                image = %s, stock = %s, category = %s, subcategory = %s
            WHERE id = %s
        """, (
            data.get("brand"),
            data.get("name"),
            data.get("price"),
            data.get("description"),
            data.get("image"),
            data.get("stock"),
            data.get("category"),
            data.get("subcategory"),
            id,
        ))
        if cursor.rowcount == 0:
            return jsonify({"error": "Product not found"}), 404
        conn.commit()
        return jsonify({"message": "Product updated"})
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()














@app.route("/api/cart/<string:email>", methods=["GET"])
def get_cart(email):
    user_id = get_user_id(email.strip().lower())
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT ci.product_id AS "productId", p.name, p.brand, p.price, p.image, ci.quantity '
            "FROM cart_items ci "
            "JOIN products p ON p.id = ci.product_id "
            "WHERE ci.user_id = %s",
            (user_id,),
        )
        return jsonify(cursor.fetchall())
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/cart/remove", methods=["POST"])
def remove_from_cart():
    payload = request.get_json() or {}
    email = payload.get("email", "").strip().lower()
    product_id = payload.get("productId")

    if not email or not product_id:
        return jsonify({"error": "Email and product ID are required."}), 400

    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM cart_items WHERE user_id = %s AND product_id = %s",
            (user_id, product_id),
        )
        conn.commit()
        return jsonify({"message": "Product removed from cart."})
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()





@app.route("/api/wishlist/add", methods=["POST"])
def add_to_wishlist():
    payload = request.get_json() or {}
    email      = payload.get("email", "").strip().lower()
    product_id = payload.get("productId")

    if not email or not product_id:
        return jsonify({"error": "Email and productId are required."}), 400

    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wishlist_items (user_id, product_id)
            VALUES (%s, %s)
            """,
            (user_id, product_id),
        )
        conn.commit()
        return jsonify({"message": "Added to wishlist."}), 201

    except Error as e:
        if getattr(e, "pgcode", None) == errorcodes.UNIQUE_VIOLATION:
            return jsonify({"error": "Already in wishlist."}), 409
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/wishlist/<email>", methods=["GET"])
def get_wishlist(email):
    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn   = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id, p.name, p.price, p.image, p.brand, p.description
            FROM wishlist_items wi
            JOIN products p ON p.id = wi.product_id
            WHERE wi.user_id = %s
            ORDER BY wi.created_at DESC
            """,
            (user_id,),
        )
        items = cursor.fetchall()
        return jsonify(items), 200

    except Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/wishlist/remove", methods=["POST"])
def remove_from_wishlist():
    payload    = request.get_json() or {}
    email      = payload.get("email", "").strip().lower()
    product_id = payload.get("productId")

    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM wishlist_items WHERE user_id = %s AND product_id = %s",
            (user_id, product_id),
        )
        conn.commit()
        return jsonify({"message": "Removed from wishlist."}), 200

    except Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()





@app.route("/api/inbox/<string:email>", methods=["GET"])
def get_inbox(email):
    user_id = get_user_id(email.strip().lower())
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id AS "messageId", subject, body, created_at AS "createdAt" '
            "FROM messages "
            "WHERE user_id = %s "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        return jsonify(cursor.fetchall())
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/orders", methods=["POST"])
def create_order():
    payload = request.get_json() or {}
    email = payload.get("email", "").strip().lower()

    user_id = get_user_id(email)
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ci.product_id, ci.quantity, p.price "
            "FROM cart_items ci "
            "JOIN products p ON p.id = ci.product_id "
            "WHERE ci.user_id = %s",
            (user_id,),
        )
        cart_items = cursor.fetchall()
        if not cart_items:
            return jsonify({"error": "Cart is empty."}), 400

        cursor.execute(
            "INSERT INTO orders (user_id, status) VALUES (%s, %s) RETURNING id",
            (user_id, "processing"),
        )
        order_id = cursor.fetchone()["id"]

        order_items = []
        for item in cart_items:
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s, %s, %s, %s)",
                (order_id, item["product_id"], item["quantity"], item["price"]),
            )
            order_items.append({
                "productId": item["product_id"],
                "quantity": item["quantity"],
                "price": float(item["price"]),
            })

        cursor.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
        conn.commit()

        return jsonify({
            "message": "Order created successfully.",
            "order": {
                "orderId": order_id,
                "userId": user_id,
                "status": "processing",
                "items": order_items,
            },
        })
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/orders/<string:email>", methods=["GET"])
def get_orders(email):
    user_id = get_user_id(email.strip().lower())
    if not user_id:
        return jsonify({"error": "User not found."}), 404

    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT o.id AS "orderId", o.status, o.created_at, oi.product_id AS "productId", '
            "p.name, p.brand, p.image, oi.quantity, oi.price "
            "FROM orders o "
            "JOIN order_items oi ON oi.order_id = o.id "
            "JOIN products p ON p.id = oi.product_id "
            "WHERE o.user_id = %s "
            "ORDER BY o.created_at DESC, o.id DESC",
            (user_id,),
        )
        rows = cursor.fetchall()

        orders = {}
        for row in rows:
            order_id = row["orderId"]
            if order_id not in orders:
                orders[order_id] = {
                    "orderId": order_id,
                    "status": row["status"],
                    "createdAt": row["created_at"].isoformat(),
                    "items": [],
                }
            orders[order_id]["items"].append({
                "productId": row["productId"],
                "name": row["name"],
                "brand": row["brand"],
                "image": row["image"],
                "quantity": row["quantity"],
                "price": float(row["price"]),
            })

        return jsonify(list(orders.values()))
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/user/<string:email>", methods=["GET"])
def get_user(email):
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT first_name, last_name, email, phone FROM users WHERE email = %s",
            (email.strip().lower(),),
        )
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "User not found."}), 404

        return jsonify({
            "firstName": user["first_name"],
            "lastName": user["last_name"],
            "email": user["email"],
            "phone": user["phone"],
        })
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        cursor.close()
        conn.close()


# ── Admin routes ───────────────────────────────────────────────────────────────

@app.route("/api/admin/analytics")
def analytics():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM orders")
    orders = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(oi.price * oi.quantity),0) FROM order_items oi")
    revenue = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
    pending = cursor.fetchone()[0]

    return jsonify({
        "orders": orders,
        "revenue": float(revenue),
        "pending": pending
    })


@app.route("/api/admin/products", methods=["POST"])
def admin_create_product():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products (brand,name,price,description,image,stock,category,subcategory)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        data.get("brand"),
        data.get("name"),
        data.get("price"),
        data.get("description"),
        data.get("image"),
        data.get("stock"),
        data.get("category"),
        data.get("subcategory"),
    ))
    conn.commit()
    return jsonify({"message": "created"})


@app.route("/api/admin/products/<int:id>/stock", methods=["PUT"])
def update_stock(id):
    data = request.json or {}
    stock = data.get("stock")

    if stock is None:
        return jsonify({"error": "Stock value is required"}), 400

    try:
        stock = int(stock)
    except (TypeError, ValueError):
        return jsonify({"error": "Stock must be a number"}), 400

    if stock < 0:
        return jsonify({"error": "Stock cannot be negative"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET stock=%s WHERE id=%s", (stock, id))

    if cursor.rowcount == 0:
        cursor.close()
        conn.close()
        return jsonify({"error": "Product not found"}), 404

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Stock updated"})









@app.route("/api/admin/upload-image", methods=["POST"])
def admin_upload_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        result = cloudinary.uploader.upload(file)
        return jsonify({"imageUrl": result["secure_url"]})
    except Exception as error:
        return jsonify({"error": str(error)}), 500













@app.route("/api/admin/products/<int:id>", methods=["DELETE"])
def delete_product(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id=%s", (id,))
    conn.commit()
    return jsonify({"message": "deleted"})


@app.route("/api/admin/orders")
def admin_orders():
    conn = get_db_connection(dict_cursor=True)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            o.id,
            o.status,
            o.created_at,
            CONCAT(u.first_name, ' ', u.last_name) AS user_name,
            STRING_AGG(p.name, ', ') AS products,
            SUM(oi.quantity * oi.price) AS total
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        GROUP BY o.id, o.status, o.created_at, u.first_name, u.last_name
        ORDER BY o.id DESC
    """)
    return jsonify(cursor.fetchall())


@app.route("/api/admin/orders/<int:id>/deliver", methods=["PUT"])
def deliver_order(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status='delivered' WHERE id=%s", (id,))
    conn.commit()
    return jsonify({"message": "updated"})


@app.route("/api/admin/orders/<int:id>", methods=["DELETE"])
def delete_order(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE id=%s", (id,))
    conn.commit()
    return jsonify({"message": "deleted"})







@app.route("/api/feedback/<int:product_id>", methods=["GET"])
def get_feedback(product_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, product_id, user_id, user_name, rating, feedback, created_at
            FROM customer_feedback
            WHERE product_id = %s
            ORDER BY created_at DESC
            """,
            (product_id,),
        )
        feedback = cursor.fetchall()
        return jsonify(feedback)
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route("/api/feedback/<int:product_id>", methods=["POST"])
def add_feedback(product_id):
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    user_name = data.get("user_name")
    rating = data.get("rating")
    feedback_text = data.get("feedback")

    if not email or not user_name or not rating or not feedback_text:
        return jsonify({"error": "Missing required fields."}), 400

    conn = None
    cursor = None
    try:
        user_id = get_user_id(email.strip().lower())
        if not user_id:
            return jsonify({"error": "User not found."}), 404

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO customer_feedback (product_id, user_id, user_name, rating, feedback)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (product_id, user_id, user_name, rating, feedback_text),
        )
        conn.commit()
        return jsonify({"message": "Feedback submitted."}), 201
    except Error as error:
        return jsonify({"error": str(error)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
















# ── Search ─────────────────────────────────────────────────────────────────────

@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify([])

    if len(query) > 100:
        return jsonify({"error": "Query too long"}), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection(dict_cursor=True)
        cursor = conn.cursor()

        sql = """
            SELECT
                id,
                name,
                
                price,
                image,
                CASE
                    WHEN name ILIKE %s THEN 1
                    ELSE 2
                END AS relevance
            FROM products
            WHERE name ILIKE %s OR description ILIKE %s
            ORDER BY relevance ASC, name ASC
            LIMIT 20
        """
        like_query = f"%{query}%"
        cursor.execute(sql, (like_query, like_query, like_query))
        results = cursor.fetchall()
        return jsonify(results)

    except Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Search failed"}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# ── Static file serving ────────────────────────────────────────────────────────

@app.route("/<path:path>")
def serve_static(path):
    if path.startswith("api/"):
        return jsonify({"error": "API route not found."}), 404
    return jsonify({"error": "Not found"}), 404



    
from mpesa import register_mpesa_routes
register_mpesa_routes(app, get_db_connection, psycopg2.Error)








import re
import time
from collections import defaultdict

# Simple in-memory rate limit tracker: { ip: [timestamps] }
contact_rate_limit = defaultdict(list)
RATE_LIMIT_WINDOW = 60       # seconds
RATE_LIMIT_MAX_REQUESTS = 3  # max submissions per window

EMAIL_REGEX = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

@app.route('/api/contact', methods=['POST'])
def submit_contact():
    ip = request.remote_addr
    now = time.time()

    # Clean out old timestamps and check rate limit
    contact_rate_limit[ip] = [t for t in contact_rate_limit[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(contact_rate_limit[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return jsonify({"error": "Too many submissions. Please try again later."}), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    message = (data.get('message') or '').strip()

    # Validation
    if not name or not email or not message:
        return jsonify({"error": "All fields are required"}), 400
    if len(name) > 100 or len(email) > 150 or len(message) > 2000:
        return jsonify({"error": "Input exceeds maximum length"}), 400
    if not EMAIL_REGEX.match(email):
        return jsonify({"error": "Invalid email format"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO contact_messages (name, email, message) VALUES (%s, %s, %s)",
        (name, email, message)
    )
    conn.commit()
    cursor.close()
    conn.close()

    contact_rate_limit[ip].append(now)

    return jsonify({"success": True, "message": "Message sent successfully"}), 200



@app.route('/api/admin/contact-messages', methods=['GET'])
def get_contact_messages():
    conn = get_db_connection(dict_cursor=True)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM contact_messages ORDER BY created_at DESC")
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(messages), 200










if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
