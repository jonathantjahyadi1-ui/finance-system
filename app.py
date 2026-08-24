from dotenv import load_dotenv
import os

from flask import (
    Flask,
    request,
    session,
    render_template,
    redirect,
    flash,
    send_from_directory
)
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
app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "finance-secret-key"
)

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db.init_app(app)


# =========================
# USER HELPER
# =========================
def normalize_username(username):
    """
    Menyamakan format username agar pencarian tidak terpengaruh
    oleh huruf kapital atau spasi.
    """
    return (username or "").strip().lower()


def move_user_transactions(source_user_id, target_user_id):
    """
    Memindahkan semua transaksi dari akun duplikat
    ke akun utama sebelum akun duplikat dihapus.
    """
    if source_user_id == target_user_id:
        return

    ReimburseRequest.query.filter_by(
        user_id=source_user_id
    ).update(
        {"user_id": target_user_id},
        synchronize_session=False
    )

    PurchaseOrderRequest.query.filter_by(
        user_id=source_user_id
    ).update(
        {"user_id": target_user_id},
        synchronize_session=False
    )


def delete_duplicate_user(primary_user, duplicate_user):
    """
    Memindahkan transaksi lalu menghapus akun duplikat.
    """
    if primary_user.id == duplicate_user.id:
        return

    move_user_transactions(
        duplicate_user.id,
        primary_user.id
    )

    db.session.delete(duplicate_user)


def clean_exact_duplicate_users():
    """
    Membersihkan semua username yang sama.

    Contoh yang dianggap sama:
    - Jonathan Tjahyadi
    - jonathan tjahyadi
    - JONATHAN TJAHYADI
    - ' Jonathan Tjahyadi '
    """
    users = User.query.order_by(User.id.asc()).all()
    primary_users = {}

    for user in users:
        normalized = normalize_username(user.username)

        if normalized not in primary_users:
            primary_users[normalized] = user
            continue

        primary_user = primary_users[normalized]

        delete_duplicate_user(
            primary_user,
            user
        )


def create_or_update_system_user(
    aliases,
    username,
    nama_lengkap,
    role,
    divisi,
    default_password,
    reset_password_aliases=None
):
    """
    Membuat atau memperbarui akun bawaan sistem.

    Semua akun lama yang termasuk dalam aliases akan digabungkan
    menjadi satu akun utama.
    """
    normalized_aliases = {
        normalize_username(alias)
        for alias in aliases
    }

    normalized_username = normalize_username(username)

    users = User.query.filter(
        db.func.lower(
            db.func.trim(User.username)
        ).in_(normalized_aliases)
    ).order_by(User.id.asc()).all()

    if users:
        # Prioritaskan akun yang sudah memakai username terbaru.
        primary_user = next(
            (
                user for user in users
                if normalize_username(user.username)
                == normalized_username
            ),
            users[0]
        )

        previous_username = normalize_username(
            primary_user.username
        )

        for duplicate_user in users:
            if duplicate_user.id == primary_user.id:
                continue

            delete_duplicate_user(
                primary_user,
                duplicate_user
            )

        # Password hanya direset saat migrasi dari username lama.
        if reset_password_aliases:
            normalized_reset_aliases = {
                normalize_username(alias)
                for alias in reset_password_aliases
            }

            if previous_username in normalized_reset_aliases:
                primary_user.password = generate_password_hash(
                    default_password
                )

        primary_user.username = username
        primary_user.nama_lengkap = nama_lengkap
        primary_user.role = role
        primary_user.divisi = divisi

        return primary_user

    new_user = User(
        username=username,
        nama_lengkap=nama_lengkap,
        password=generate_password_hash(default_password),
        role=role,
        divisi=divisi
    )

    db.session.add(new_user)

    return new_user


def create_normalized_username_index():
    """
    Membuat unique index agar username yang sama tidak bisa
    tersimpan lagi walaupun penulisan kapital atau spasinya berbeda.
    """
    table = User.__table__
    preparer = db.engine.dialect.identifier_preparer

    table_name = preparer.format_table(table)
    index_name = preparer.quote(
        f"uq_{table.name}_username_normalized"
    )

    db.session.execute(
        db.text(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
            ON {table_name} (LOWER(BTRIM(username)))
            """
        )
    )


# =========================
# AUTO CREATE TABLE + USERS
# =========================
with app.app_context():
    db.create_all()

    try:
        # Mencegah beberapa worker Render menjalankan proses
        # pembuatan dan penggabungan akun secara bersamaan.
        db.session.execute(
            db.text(
                "SELECT pg_advisory_xact_lock(:lock_id)"
            ),
            {"lock_id": 24082026}
        )

        # Bersihkan username yang benar-benar sama terlebih dahulu.
        clean_exact_duplicate_users()

        # =========================
        # ADMIN
        # =========================
        create_or_update_system_user(
            aliases=[
                "Jonathan",
                "Jonathan Tjahyadi"
            ],
            username="Jonathan Tjahyadi",
            nama_lengkap="Jonathan Tjahyadi",
            role="admin",
            divisi="IT",
            default_password="Jonathan@itsupport"
        )

        # =========================
        # DIREKTUR
        # =========================
        create_or_update_system_user(
            aliases=[
                "Martin"
            ],
            username="Martin",
            nama_lengkap="Martin",
            role="direktur",
            divisi="Direksi",
            default_password="123456"
        )

        # =========================
        # ACCOUNTING
        # =========================
        create_or_update_system_user(
            aliases=[
                "Aldo",
                "Muh Aldo Januar"
            ],
            username="Muh Aldo Januar",
            nama_lengkap="Muh Aldo Januar",
            role="accounting",
            divisi="Accounting",
            default_password="Aldo@accounting",
            reset_password_aliases=[
                "Aldo"
            ]
        )

        # Jalankan seluruh perubahan sebelum membuat unique index.
        db.session.flush()

        # Mencegah username duplikat tersimpan lagi.
        create_normalized_username_index()

        db.session.commit()

    except Exception:
        db.session.rollback()
        raise


# =========================
# BASIC ROUTES
# =========================
@app.route("/")
def index():
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login_view():
    if request.method == "POST":
        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        # Login tidak sensitif terhadap huruf besar/kecil.
        user = User.query.filter(
            db.func.lower(
                db.func.trim(User.username)
            ) == username.lower()
        ).first()

        if not user or not check_password_hash(
            user.password,
            password
        ):
            flash(
                "Username / password salah!",
                "danger"
            )
            return redirect("/login")

        # Bersihkan session lama agar sistem tidak bertumpuk.
        session.clear()

        session["user_id"] = user.id
        session["role"] = user.role

        return redirect("/main_dashboard")

    return render_template("login.html")


@app.route("/main_dashboard")
def main_dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user = db.session.get(
        User,
        session["user_id"]
    )

    if not user:
        session.clear()
        return redirect("/login")

    selected_system = request.args.get("system")

    if selected_system == "reimburse":
        session["active_system"] = "reimburse"
        return redirect("/reimburse/list")

    if selected_system == "purchase_order":
        session["active_system"] = "purchase_order"
        return redirect("/purchase-order/list")

    active_system = session.get("active_system")

    if active_system == "reimburse":
        return redirect("/reimburse/list")

    if active_system == "purchase_order":
        return redirect("/purchase-order/list")

    return render_template(
        "main_dashboard.html",
        user=user
    )


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
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


@app.context_processor
def utility_processor():
    def get_user(user_id):
        return db.session.get(
            User,
            user_id
        )

    return dict(get_user=get_user)


# =========================
# REGISTER BLUEPRINT
# =========================
from reimburse.routes import reimburse_bp

app.register_blueprint(
    reimburse_bp,
    url_prefix="/reimburse"
)

from purchase_order.routes import po_bp

app.register_blueprint(
    po_bp,
    url_prefix="/purchase-order"
)


if __name__ == "__main__":
    app.run(debug=True)