from dotenv import load_dotenv
import os

from flask import Flask, request, session, render_template, redirect, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User, PurchaseOrderRequest, PurchaseOrderItem
from reimburse.models import ReimburseRequest, ReimburseItem


# =========================
# LOAD ENV
# =========================
if os.getenv("RENDER") is None:
    load_dotenv()


app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# =========================
# DATABASE CONFIG
# =========================
uri = os.getenv("DATABASE_URL")

if not uri:
    raise Exception("DATABASE_URL belum diset di environment!")

if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

if "sslmode" not in uri:
    if "?" in uri:
        uri += "&sslmode=require"
    else:
        uri += "?sslmode=require"

app.config["SQLALCHEMY_DATABASE_URI"] = uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "finance-secret-key")

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db.init_app(app)


# =========================
# AUTO CREATE TABLE + SEED USER
# =========================
with app.app_context():
    db.create_all()

    # ADMIN
    if not User.query.filter_by(username="Jonathan").first():
        db.session.add(User(
            username="Jonathan",
            nama_lengkap="Jonathan",
            password=generate_password_hash("Jonathan@itsupport"),
            role="admin",
            divisi="IT"
        ))

    # DIREKTUR
    if not User.query.filter_by(username="Martin").first():
        db.session.add(User(
            username="Martin",
            nama_lengkap="Martin",
            password=generate_password_hash("Martin@direktur"),
            role="direktur",
            divisi="Direksi"
        ))

    # ACCOUNTING
    if not User.query.filter_by(username="aul").first():
        db.session.add(User(
            username="aul",
            nama_lengkap="aul",
            password=generate_password_hash("aul@accounting"),
            role="accounting",
            divisi="Accounting"
        ))

    db.session.commit()


# =========================
# BASIC ROUTES
# =========================
@app.route("/")
def index():
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login_view():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password, password):
            flash("Username / password salah!", "danger")
            return redirect("/login")

        session["user_id"] = user.id
        session["role"] = user.role

        return redirect("/main_dashboard")

    return render_template("login.html")


@app.route("/main_dashboard")
def main_dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(User, session["user_id"])
    if not user:
        session.clear()
        return redirect("/login")

    selected_system = request.args.get("system")

    if selected_system == "reimburse":
        session["active_system"] = "reimburse"
        return redirect("/reimburse/list")

    elif selected_system == "purchase_order":
        session["active_system"] = "purchase_order"
        return redirect("/purchase-order/list")

    if session.get("active_system") == "reimburse":
        return redirect("/reimburse/list")

    elif session.get("active_system") == "purchase_order":
        return redirect("/purchase-order/list")

    return render_template("main_dashboard.html", user=user)


@app.route("/change_system")
def change_system():
    session.pop("active_system", None)
    return redirect("/main_dashboard")


@app.route("/logout")
def logout_view():
    session.clear()
    return redirect("/login")


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.context_processor
def utility_processor():
    def get_user(user_id):
        return db.session.get(User, user_id)

    return dict(get_user=get_user)


# =========================
# REGISTER BLUEPRINT
# =========================
from reimburse.routes import reimburse_bp
app.register_blueprint(reimburse_bp, url_prefix="/reimburse")

from purchase_order.routes import po_bp
app.register_blueprint(po_bp, url_prefix="/purchase-order")


if __name__ == "__main__":
    app.run(debug=True)