"""
StudioHub — Event studios x Freelance photographers & videographers
---------------------------------------------------------------------
Studios post events with the crew they need; freelancers mark the dates
they are free; both sides match and book. Single-file Flask backend.

Run:  python3 app.py   ->  http://localhost:5000
"""
import os
import sqlite3
from datetime import date
TODAY = date.today
from functools import wraps

from flask import (Flask, Response, render_template, request, redirect, url_for,
                   flash, session, jsonify, g)
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "studiohub.db")

# Roles a studio can need / a freelancer can offer
ROLES = {
    "trad_photographer": "Traditional Photographer",
    "trad_videographer": "Traditional Videographer",
    "candid_photographer": "Candid Photographer",
    "candid_videographer": "Candid Videographer",
    "drone": "Drone Pilot",
    "livestream": "Live Streamer",
    "led_wall": "LED Wall",
}

# Tamil Nadu districts (event district dropdown + filter)
TN_DISTRICTS = [
    "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore",
    "Dharmapuri", "Dindigul", "Erode", "Kallakurichi", "Kanchipuram",
    "Kanyakumari", "Karur", "Krishnagiri", "Madurai", "Mayiladuthurai",
    "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai",
    "Ramanathapuram", "Ranipet", "Salem", "Sivaganga", "Tenkasi",
    "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli", "Tirunelveli",
    "Tirupathur", "Tiruppur", "Tiruvallur", "Tiruvannamalai", "Tiruvarur",
    "Vellore", "Viluppuram", "Virudhunagar",
]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-change-me-in-production")

# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('studio','freelancer')),
    phone         TEXT DEFAULT '',
    instagram_url TEXT DEFAULT '',
    youtube_url   TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS freelancer_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    skills  TEXT NOT NULL DEFAULT '',  -- ',key,key,' comma padded
    rate    INTEGER DEFAULT 0,        -- Rs per day
    city    TEXT DEFAULT '',
    bio     TEXT DEFAULT '',
    upi_id  TEXT DEFAULT ''           -- UPI id for advance payments
);
CREATE TABLE IF NOT EXISTS availability (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    avail_date TEXT NOT NULL,
    UNIQUE (user_id, avail_date)
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    studio_id  INTEGER NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL,
    event_date TEXT NOT NULL,
    end_date   TEXT,                  -- NULL = single-day event
    location   TEXT DEFAULT '',
    district   TEXT DEFAULT '',
    details    TEXT DEFAULT '',
    status     TEXT DEFAULT 'open',   -- open / closed
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS event_roles (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    role_key TEXT NOT NULL,
    count    INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER NOT NULL REFERENCES events(id),
    role_key     TEXT NOT NULL,
    freelancer_id INTEGER NOT NULL REFERENCES users(id),
    status       TEXT NOT NULL,       -- applied/invited/booked/declined/cancelled
    initiated_by TEXT NOT NULL,       -- freelancer / studio
    advance_amount INTEGER DEFAULT 0, -- Rs agreed advance
    advance_paid   INTEGER DEFAULT 0, -- 0/1
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE (event_id, role_key, freelancer_id)
);
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS note_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL,
    event_date TEXT NOT NULL,
    location   TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    link TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS favorites (          -- studio saves a freelancer
    user_id INTEGER NOT NULL REFERENCES users(id),
    target_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, target_user_id)
);
CREATE TABLE IF NOT EXISTS event_favorites (    -- freelancer saves an event
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id INTEGER NOT NULL REFERENCES events(id),
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, event_id)
);
CREATE TABLE IF NOT EXISTS staff_admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    perms TEXT DEFAULT '',           -- comma list: dashboard,users,events,bookings
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id),
    receiver_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS portfolio_photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    caption    TEXT DEFAULT '',
    data       BLOB NOT NULL,
    mime       TEXT DEFAULT 'image/jpeg',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ratings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id    INTEGER NOT NULL REFERENCES bookings(id),
    studio_id     INTEGER NOT NULL REFERENCES users(id),
    freelancer_id INTEGER NOT NULL REFERENCES users(id),
    stars         INTEGER NOT NULL,   -- 1 to 5
    comment       TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now')),
    UNIQUE (booking_id)
);
"""


def using_postgres():
    return os.environ.get("DATABASE_URL", "").strip().startswith("postgres")


class DBConn:
    """Thin wrapper: identical API for SQLite (local) and PostgreSQL (Render).
    Set DATABASE_URL env var to use Postgres."""

    def __init__(self):
        url = os.environ.get("DATABASE_URL", "").strip()
        if url.startswith("postgres"):
            import psycopg2
            from psycopg2.extras import DictCursor
            self.pg = True
            self.conn = psycopg2.connect(url, sslmode="require",
                                         cursor_factory=DictCursor)
        else:
            self.pg = False
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _pg_run(self, sql, params):
        """Run one statement on Postgres; auto-rollback so a failed
        statement never leaves the connection in aborted state."""
        sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(params))
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            raise
        return cur

    def execute(self, sql, params=()):
        if self.pg:
            return self._pg_run(sql, params)
        return self.conn.execute(sql, tuple(params))

    def executescript(self, script):
        if self.pg:
            cur = self.conn.cursor()
            for stmt in script.split(";"):
                s = stmt.strip()
                if s:
                    try:
                        cur.execute(s)
                    except Exception:
                        self.conn.rollback()
                        raise
            self.conn.commit()
            return cur
        return self.conn.executescript(script)

    def insert(self, sql, params=()):
        """INSERT; returns the new row id."""
        if self.pg:
            if "returning" not in sql.lower():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
            return self._pg_run(sql, params).fetchone()[0]
        cur = self.conn.execute(sql, tuple(params))
        return cur.lastrowid

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    if "db" not in g:
        g.db = DBConn()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        try:
            db.commit()
        except Exception:
            pass
        db.close()


def reset_admin(username="admin", password="admin123"):
    """Set the single admin account to the given username/password."""
    db = DBConn()
    db.executescript(SCHEMA_PG if db.pg else SCHEMA)
    row = db.execute("SELECT id FROM admins ORDER BY id LIMIT 1").fetchone()
    if row:
        db.execute("UPDATE admins SET username = ?, password_hash = ? WHERE id = ?",
                   (username, generate_password_hash(password), row[0]))
    else:
        db.insert("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                  (username, generate_password_hash(password)))
    db.commit()
    db.close()


# SQLite and PostgreSQL speak slightly different DDL
SCHEMA_PG = (SCHEMA
             .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
             .replace("datetime('now')", "CURRENT_TIMESTAMP")
             .replace(" BLOB", " BYTEA"))


def init_db():
    db = DBConn()
    db.executescript(SCHEMA_PG if db.pg else SCHEMA)
    # migrations: add new columns to existing tables (fresh DBs already have them)
    migrations = [
        "ALTER TABLE events ADD COLUMN end_date TEXT",
        "ALTER TABLE freelancer_profiles ADD COLUMN upi_id TEXT DEFAULT ''",
        "ALTER TABLE bookings ADD COLUMN advance_amount INTEGER DEFAULT 0",
        "ALTER TABLE bookings ADD COLUMN advance_paid INTEGER DEFAULT 0",
        "ALTER TABLE events ADD COLUMN district TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN instagram_url TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN youtube_url TEXT DEFAULT ''",
    ]
    for m in migrations:
        try:
            db.execute(m)
        except Exception:
            pass  # column already exists
    # seed the default super admin (username: admin / password: admin123)
    if not db.execute("SELECT 1 FROM admins").fetchone():
        db.insert("INSERT INTO admins (username, password_hash) VALUES ('admin', ?)",
                  (generate_password_hash("admin123"),))
    db.commit()
    db.close()
    # admin recovery: if ADMIN_USERNAME + ADMIN_PASSWORD env vars are set,
    # they override the stored admin login on every startup (used on Render).
    env_user = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    env_pass = os.environ.get("ADMIN_PASSWORD", "")
    if env_user and len(env_pass) >= 6:
        reset_admin(env_user, env_pass)


init_db()

# ---------------------------------------------------------------- helpers
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def freelancer_profile(uid):
    return get_db().execute(
        "SELECT * FROM freelancer_profiles WHERE user_id = ?", (uid,)).fetchone()


def skills_list(profile_row):
    if not profile_row or not profile_row["skills"]:
        return []
    return [s for s in profile_row["skills"].strip(",").split(",") if s]


def role_label(key):
    return ROLES.get(key, key)


app.jinja_env.globals.update(role_label=role_label, ROLES=ROLES, TN_DISTRICTS=TN_DISTRICTS)


def notify(user_id, message, link=""):
    """Create an in-app notification for a user (bell icon)."""
    try:
        db = get_db()
        db.execute("INSERT INTO notifications (user_id, message, link) VALUES (?,?,?)",
                   (user_id, message, link))
        db.commit()
    except Exception:
        pass  # never break a booking action because of a notification


@app.context_processor
def inject_unread_count():
    uid = session.get("uid")
    if not uid:
        return {"unread_count": 0}
    try:
        c = get_db().execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
            (uid,)).fetchone()[0]
    except Exception:
        c = 0
    return {"unread_count": c}


# ------------------------------------------------ site settings (key/value)
SOCIAL_KEYS = ["social_instagram", "social_youtube", "social_facebook", "social_x"]

def get_setting(db, key, default=""):
    try:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return (row["value"] or "") if row else default
    except Exception:
        return default

def set_setting(db, key, value):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row:
        db.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))
    else:
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))

@app.context_processor
def inject_unread_msgs():
    uid = session.get("uid")
    if not uid:
        return {"unread_msgs": 0}
    try:
        c = get_db().execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0",
            (uid,)).fetchone()[0]
    except Exception:
        c = 0
    return {"unread_msgs": c}


@app.context_processor
def inject_social_links():
    try:
        db = get_db()
        return {"social_links": {k: get_setting(db, k) for k in SOCIAL_KEYS}}
    except Exception:
        return {"social_links": {k: "" for k in SOCIAL_KEYS}}

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            flash("Please log in first.", "error")
            return redirect(url_for("landing"))
        return fn(*args, **kwargs)
    return wrapper


def event_date_str(ev):
    """'2026-10-05' or '2026-10-05 to 2026-10-07' for multi-day."""
    if ev["end_date"] and ev["end_date"] != ev["event_date"]:
        return ev["event_date"] + " to " + ev["end_date"]
    return ev["event_date"]


app.jinja_env.globals.update(event_date_str=event_date_str)


def event_end(ev):
    """End date of an event row/dict (single-day events end on their start date)."""
    return ev["end_date"] or ev["event_date"]


def event_dates(ev):
    """All ISO dates an event spans (1..N days)."""
    from datetime import timedelta
    start = date.fromisoformat(ev["event_date"])
    end = date.fromisoformat(event_end(ev))
    out = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def events_overlap(ev1, ev2):
    """True if two events share at least one date."""
    return (ev1["event_date"] <= event_end(ev2)) and (ev2["event_date"] <= event_end(ev1))


def already_booked_on_date(db, freelancer_id, ev):
    """True if the freelancer has a confirmed booking that overlaps this event."""
    return already_booked_excluding(db, freelancer_id, ev, None)


def already_booked_excluding(db, freelancer_id, ev, exclude_event_id):
    """Same, but ignoring bookings on one specific event."""
    rows = db.execute(
        """SELECT b.event_id, e.event_date, e.end_date FROM bookings b
           JOIN events e ON e.id = b.event_id
           WHERE b.freelancer_id = ? AND b.status = 'booked'""",
        (freelancer_id,)).fetchall()
    end = event_end(ev)
    for r in rows:
        if exclude_event_id is not None and r["event_id"] == exclude_event_id:
            continue
        r_end = r["end_date"] or r["event_date"]
        if ev["event_date"] <= r_end and r["event_date"] <= end:
            return True
    return False


def date_is_locked(db, freelancer_id, d):
    """True if date d falls inside any confirmed multi/single-day booking."""
    return db.execute(
        """SELECT 1 FROM bookings b JOIN events e ON e.id = b.event_id
           WHERE b.freelancer_id = ? AND b.status = 'booked'
             AND e.event_date <= ? AND COALESCE(e.end_date, e.event_date) >= ?""",
        (freelancer_id, d, d)).fetchone() is not None


def event_with_roles(event_row):
    """Attach role-wise booking info to an event row."""
    db = get_db()
    ev = dict(event_row)
    ev["studio_name"] = db.execute(
        "SELECT name FROM users WHERE id = ?", (ev["studio_id"],)).fetchone()[0]
    roles = []
    for r in db.execute(
            "SELECT * FROM event_roles WHERE event_id = ? ORDER BY id", (ev["id"],)):
        role = dict(r)
        role["label"] = ROLES.get(role["role_key"], role["role_key"])
        role["bookings"] = []
        for b in db.execute(
            """SELECT b.*, u.name AS freelancer_name, u.phone AS freelancer_phone,
                      fp.rate AS rate, fp.upi_id AS upi_id,
                      r.stars AS rating, r.comment AS rating_comment
               FROM bookings b JOIN users u ON u.id = b.freelancer_id
               LEFT JOIN freelancer_profiles fp ON fp.user_id = u.id
               LEFT JOIN ratings r ON r.booking_id = b.id
               WHERE b.event_id = ? AND b.role_key = ?
               ORDER BY CASE b.status WHEN 'booked' THEN 0 WHEN 'applied' THEN 1
                         WHEN 'invited' THEN 2 ELSE 3 END, b.created_at DESC""",
            (ev["id"], role["role_key"])):
            b = dict(b)
            b["avg"], b["rcount"] = avg_rating(db, b["freelancer_id"])
            role["bookings"].append(b)
        role["booked_count"] = sum(1 for b in role["bookings"] if b["status"] == "booked")
        role["filled"] = role["booked_count"] >= role["count"]
        roles.append(role)
    ev["roles"] = roles
    return ev


# ---------------------------------------------------------------- auth
@app.route("/")
def landing():
    if session.get("uid"):
        u = current_user()
        return redirect(url_for("studio_home" if u["role"] == "studio" else "freelancer_home"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    if request.method == "GET":
        if session.get("uid"):
            u = current_user()
            return redirect(url_for("studio_home" if u["role"] == "studio" else "freelancer_home"))
        return render_template("register.html")
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role")
    phone = request.form.get("phone", "").strip()

    if not (name and email and password and role in ("studio", "freelancer")):
        flash("Please fill all required fields.", "error")
        return redirect(url_for("register"))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("register"))
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        flash("This email is already registered. Try logging in.", "error")
        return redirect(url_for("landing"))

    uid = db.insert(
        "INSERT INTO users (name, email, password_hash, role, phone) VALUES (?,?,?,?,?)",
        (name, email, generate_password_hash(password), role, phone))

    if role == "freelancer":
        skills = request.form.getlist("skills")
        valid = [s for s in skills if s in ROLES]
        if not valid:
            db.execute("DELETE FROM users WHERE id = ?", (uid,))
            db.commit()
            flash("Please pick at least one skill (photographer / videographer).", "error")
            return redirect(url_for("register"))
        rate = request.form.get("rate", "0").strip() or 0
        try:
            rate = int(rate)
        except ValueError:
            rate = 0
        db.execute(
            "INSERT INTO freelancer_profiles (user_id, skills, rate, city, bio) VALUES (?,?,?,?,?)",
            (uid, "," + ",".join(valid) + ",", rate,
             request.form.get("city", "").strip(), request.form.get("bio", "").strip()))
    db.commit()

    session["uid"] = uid
    flash(f"Welcome to StudioHub, {name}!", "success")
    return redirect(url_for("studio_home" if role == "studio" else "freelancer_home"))


@app.route("/login", methods=["POST"])
def login():
    db = get_db()
    identifier = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if login_locked(identifier):
        flash("Too many wrong attempts. Try again in 5 minutes.", "error")
        return redirect(url_for("landing"))
    # accept email OR mobile number as login id
    user = db.execute(
        """SELECT * FROM users WHERE email = ?
           OR (phone != '' AND phone = ?)""",
        (identifier, identifier)).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        login_ok(identifier)
        session["uid"] = user["id"]
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("studio_home" if user["role"] == "studio" else "freelancer_home"))
    login_failed(identifier)
    flash("Wrong email/phone or password. Check your password too (6+ characters).", "error")
    return redirect(url_for("landing"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out. See you soon!", "success")
    return redirect(url_for("landing"))


# ---------------------------------------------------------------- freelancer
@app.route("/freelancer")
@login_required
def freelancer_home():
    u = current_user()
    if u["role"] != "freelancer":
        return redirect(url_for("studio_home"))
    db = get_db()
    profile = freelancer_profile(u["id"])
    my_skills = skills_list(profile)

    # events on my available dates that need one of my skills
    matches = []
    placeholders = ",".join("?" for _ in my_skills) or "''"
    q = f"""SELECT DISTINCT e.* FROM events e
            JOIN event_roles er ON er.event_id = e.id
            JOIN availability a ON a.user_id = ?
                 AND a.avail_date >= e.event_date
                 AND a.avail_date <= COALESCE(e.end_date, e.event_date)
            WHERE e.status = 'open' AND e.event_date >= ?
              AND er.role_key IN ({placeholders})
            ORDER BY e.event_date"""
    rows = db.execute(q, [u["id"], TODAY().isoformat()] + my_skills).fetchall()
    for r in rows:
        ev = event_with_roles(r)
        # which of my skills this event needs, and my status there
        ev["my_matches"] = []
        for role in ev["roles"]:
            if role["role_key"] in my_skills:
                mine = next((b for b in role["bookings"] if b["freelancer_id"] == u["id"]), None)
                ev["my_matches"].append({"role": role, "my_booking": mine})
        matches.append(ev)

    my_bookings = []
    for b in db.execute(
            """SELECT b.*, e.title AS event_title, e.event_date, e.end_date, e.location, e.studio_id
               FROM bookings b JOIN events e ON e.id = b.event_id
               WHERE b.freelancer_id = ? ORDER BY e.event_date DESC""", (u["id"],)):
        b = dict(b)
        b["date_str"] = event_date_str(b)
        b["studio_name"] = db.execute(
            "SELECT name FROM users WHERE id = ?", (b["studio_id"],)).fetchone()[0]
        my_bookings.append(b)

    avail_dates = [r["avail_date"] for r in db.execute(
        "SELECT avail_date FROM availability WHERE user_id = ? ORDER BY avail_date", (u["id"],))]

    return render_template("freelancer_home.html", user=u, profile=profile,
                           matches=matches, my_bookings=my_bookings,
                           avail_dates=avail_dates)


@app.route("/api/availability", methods=["GET", "POST"])
def api_availability():
    if not session.get("uid"):
        return jsonify({"ok": False}), 401
    u = current_user()
    if u["role"] != "freelancer":
        return jsonify({"ok": False, "error": "studio accounts cannot set availability"}), 400
    db = get_db()
    if request.method == "GET":
        rows = db.execute("SELECT avail_date FROM availability WHERE user_id = ?",
                          (u["id"],)).fetchall()
        # booked info per date (confirmed app bookings + manual note events)
        booked = {}
        for b in db.execute(
                """SELECT e.title, e.event_date, e.end_date, e.location, e.district,
                          e.studio_id, b.role_key
                   FROM bookings b JOIN events e ON e.id = b.event_id
                   WHERE b.freelancer_id = ? AND b.status = 'booked'""",
                (u["id"],)):
            studio = db.execute("SELECT name FROM users WHERE id = ?",
                                (b["studio_id"],)).fetchone()
            for d in event_dates(b):
                booked[d] = {"type": "app", "title": b["title"],
                             "studio": studio[0] if studio else "",
                             "location": b["location"] or "",
                             "district": b["district"] or "",
                             "role": role_label(b["role_key"]),
                             "date_str": event_date_str(b)}
        for n in db.execute(
                "SELECT * FROM note_events WHERE user_id = ?", (u["id"],)):
            booked[n["event_date"]] = {"type": "note", "title": n["title"],
                                       "studio": "", "location": n["location"] or "",
                                       "district": "", "role": "",
                                       "date_str": n["event_date"],
                                       "notes": n["notes"] or ""}
        return jsonify({"dates": [r["avail_date"] for r in rows], "booked": booked})
    data = request.get_json(force=True, silent=True) or {}
    d = (data.get("date") or "").strip()
    try:
        date.fromisoformat(d)
    except ValueError:
        return jsonify({"ok": False, "error": "bad date"}), 400
    existing = db.execute(
        "SELECT 1 FROM availability WHERE user_id = ? AND avail_date = ?", (u["id"], d)).fetchone()
    if existing:
        # don't remove if booked on that date
        if date_is_locked(db, u["id"], d):
            return jsonify({"ok": False, "error": "You have a confirmed booking on this date."}), 400
        db.execute("DELETE FROM availability WHERE user_id = ? AND avail_date = ?", (u["id"], d))
        available = False
    else:
        db.execute("INSERT INTO availability (user_id, avail_date) VALUES (?,?)", (u["id"], d))
        available = True
    db.commit()
    return jsonify({"ok": True, "available": available})


@app.route("/freelancer/profile", methods=["GET", "POST"])
@login_required
def freelancer_profile_edit():
    u = current_user()
    if u["role"] != "freelancer":
        return redirect(url_for("studio_home"))
    db = get_db()
    if request.method == "POST":
        valid = [s for s in request.form.getlist("skills") if s in ROLES]
        if not valid:
            flash("Keep at least one skill selected.", "error")
        else:
            try:
                rate = int(request.form.get("rate", "0") or 0)
            except ValueError:
                rate = 0
            db.execute(
                """UPDATE freelancer_profiles SET skills = ?, rate = ?, city = ?, bio = ?, upi_id = ?
                   WHERE user_id = ?""",
                ("," + ",".join(valid) + ",", rate,
                 request.form.get("city", "").strip(),
                 request.form.get("bio", "").strip(),
                 request.form.get("upi_id", "").strip(), u["id"]))
            db.execute("""UPDATE users SET phone = ?, instagram_url = ?, youtube_url = ?
                          WHERE id = ?""",
                       (request.form.get("phone", "").strip(),
                        request.form.get("instagram_url", "").strip(),
                        request.form.get("youtube_url", "").strip(), u["id"]))
            db.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("freelancer_home"))
    profile = freelancer_profile(u["id"])
    photos = [dict(r) for r in db.execute(
        "SELECT id, caption, created_at FROM portfolio_photos WHERE user_id = ? ORDER BY id DESC",
        (u["id"],))]
    reviews = [dict(r) for r in db.execute(
        """SELECT r.stars, r.comment, r.created_at, su.name AS studio_name
           FROM ratings r JOIN users su ON su.id = r.studio_id
           WHERE r.freelancer_id = ? ORDER BY r.id DESC LIMIT 20""", (u["id"],))]
    avg, cnt = avg_rating(db, u["id"])
    return render_template("profile.html", user=u, profile=profile,
                           my_skills=skills_list(profile),
                           photos=photos, reviews=reviews, avg=avg, rating_count=cnt)


@app.route("/apply", methods=["POST"])
@login_required
def apply():
    u = current_user()
    if u["role"] != "freelancer":
        flash("Only freelancer accounts can apply.", "error")
        return redirect(url_for("studio_home"))
    db = get_db()
    event_id = request.form.get("event_id", type=int)
    role_key = request.form.get("role_key")
    ev = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not ev or ev["status"] != "open" or ev["event_date"] < TODAY().isoformat():
        flash("This event is not open for applications.", "error")
        return redirect(url_for("freelancer_home"))
    if role_key not in skills_list(freelancer_profile(u["id"])):
        flash("That role is not one of your skills.", "error")
        return redirect(url_for("freelancer_home"))
    if not db.execute("SELECT 1 FROM event_roles WHERE event_id = ? AND role_key = ?",
                      (event_id, role_key)).fetchone():
        flash("That role is not needed for this event.", "error")
        return redirect(url_for("freelancer_home"))
    if already_booked_excluding(db, u["id"], ev, event_id):
        flash("You are already booked on another event that day.", "error")
        return redirect(url_for("freelancer_home"))
    if db.execute("SELECT 1 FROM bookings WHERE event_id = ? AND role_key = ? AND freelancer_id = ?",
                  (event_id, role_key, u["id"])).fetchone():
        flash("You already applied for this role.", "error")
        return redirect(url_for("freelancer_home"))
    # make sure ALL event dates are marked available
    for d in event_dates(ev):
        if not db.execute("SELECT 1 FROM availability WHERE user_id = ? AND avail_date = ?",
                          (u["id"], d)).fetchone():
            db.execute("INSERT INTO availability (user_id, avail_date) VALUES (?,?)",
                       (u["id"], d))
    db.execute(
        """INSERT INTO bookings (event_id, role_key, freelancer_id, status, initiated_by)
           VALUES (?,?,?,'applied','freelancer')""", (event_id, role_key, u["id"]))
    db.commit()
    flash(f"Applied as {role_label(role_key)} for '{ev['title']}'. The studio will confirm.", "success")
    notify(ev["studio_id"],
           f"{u['name']} applied as {role_label(role_key)} for '{ev['title']}' ( {event_date_str(ev)} ).",
           f"/event/{event_id}")
    return redirect(url_for("freelancer_home"))


# ---------------------------------------------------------------- freelancer: notes

@app.route("/schedule-notes")
@login_required
def schedule_notes():
    """Date-wise schedule: freelancer = app-booked events; studio = own events."""
    u = current_user()
    db = get_db()
    today = TODAY().isoformat()
    if u["role"] == "studio":
        events = []
        for r in db.execute(
                "SELECT * FROM events WHERE studio_id = ? ORDER BY event_date",
                (u["id"],)).fetchall():
            events.append(event_with_roles(r))
        upcoming = [e for e in events if e["event_date"] >= today]
        past = [e for e in events if e["event_date"] < today]
        notes_up = [n for n in db.execute(
            "SELECT * FROM note_events WHERE user_id = ? AND event_date >= ? ORDER BY event_date",
            (u["id"], today)).fetchall()]
        notes_past = [n for n in db.execute(
            "SELECT * FROM note_events WHERE user_id = ? AND event_date < ? ORDER BY event_date",
            (u["id"], today)).fetchall()]
        return render_template("schedule_notes.html", user=u,
                               upcoming=upcoming, past=past, studio_view=True,
                               notes_upcoming=notes_up, notes_past=notes_past)
    items = []
    for b in db.execute(
            """SELECT b.id, b.role_key, b.advance_amount, b.advance_paid,
                      e.title, e.event_date, e.end_date, e.location, e.district,
                      e.studio_id, e.details
               FROM bookings b JOIN events e ON e.id = b.event_id
               WHERE b.freelancer_id = ? AND b.status = 'booked'
               ORDER BY e.event_date""", (u["id"],)):
        b = dict(b)
        b["date_str"] = event_date_str(b)
        b["studio_name"] = db.execute(
            "SELECT name FROM users WHERE id = ?", (b["studio_id"],)).fetchone()[0]
        b["role"] = role_label(b["role_key"])
        items.append(b)
    upcoming = [i for i in items if i["event_date"] >= today]
    past = [i for i in items if i["event_date"] < today]
    notes_up = [n for n in db.execute(
        "SELECT * FROM note_events WHERE user_id = ? AND event_date >= ? ORDER BY event_date",
        (u["id"], today)).fetchall()]
    notes_past = [n for n in db.execute(
        "SELECT * FROM note_events WHERE user_id = ? AND event_date < ? ORDER BY event_date",
        (u["id"], today)).fetchall()]
    return render_template("schedule_notes.html", user=u,
                           upcoming=upcoming, past=past,
                           notes_upcoming=notes_up, notes_past=notes_past)


@app.route("/note-events", methods=["GET", "POST"])
@login_required
def note_events_page():
    """Manually note outside bookings (not booked through the app)."""
    u = current_user()
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        if not (title and event_date):
            flash("Function name and date are required.", "error")
            return redirect(url_for("note_events_page"))
        try:
            date.fromisoformat(event_date)
        except ValueError:
            flash("Invalid date.", "error")
            return redirect(url_for("note_events_page"))
        db.insert(
            """INSERT INTO note_events (user_id, title, event_date, location, notes)
               VALUES (?,?,?,?,?)""",
            (u["id"], title, event_date, location, notes))
        # freelancers: show it inside My Availability as a booked date too
        if u["role"] == "freelancer" and not db.execute(
                "SELECT 1 FROM availability WHERE user_id = ? AND avail_date = ?",
                (u["id"], event_date)).fetchone():
            db.execute("INSERT INTO availability (user_id, avail_date) VALUES (?,?)",
                       (u["id"], event_date))
        db.commit()
        flash(f"Noted: {title} on {event_date}.", "success")
        return redirect(url_for("note_events_page"))
    today = TODAY().isoformat()
    notes_upcoming, notes_past = [], []
    for n in db.execute(
            "SELECT * FROM note_events WHERE user_id = ? ORDER BY event_date",
            (u["id"],)).fetchall():
        (notes_upcoming if n["event_date"] >= today else notes_past).append(n)
    return render_template("note_events.html", user=u,
                           notes_upcoming=notes_upcoming, notes_past=notes_past)


@app.route("/note-events/delete/<int:note_id>", methods=["POST"])
@login_required
def note_event_delete(note_id):
    u = current_user()
    db = get_db()
    n = db.execute("SELECT * FROM note_events WHERE id = ? AND user_id = ?",
                   (note_id, u["id"])).fetchone()
    if n:
        db.execute("DELETE FROM note_events WHERE id = ?", (note_id,))
        db.commit()
        flash("Note event removed.", "success")
    return redirect(url_for("note_events_page"))


@app.route("/studio/profile", methods=["GET", "POST"])
@login_required
def studio_profile():
    """Simple profile page for studio accounts."""
    u = current_user()
    if u["role"] != "studio":
        return redirect(url_for("freelancer_profile_edit"))
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name:
            flash("Studio name cannot be empty.", "error")
        else:
            db.execute("""UPDATE users SET name = ?, phone = ?, instagram_url = ?, youtube_url = ?
                          WHERE id = ?""",
                       (name, phone,
                        request.form.get("instagram_url", "").strip(),
                        request.form.get("youtube_url", "").strip(), u["id"]))
            db.commit()
            flash("Profile updated.", "success")
        return redirect(url_for("studio_profile"))
    return render_template("studio_profile.html", user=u)


# ---------------------------------------------------------------- studio
@app.route("/studio")
@login_required
def studio_home():
    u = current_user()
    if u["role"] != "studio":
        return redirect(url_for("freelancer_home"))
    db = get_db()
    today = TODAY().isoformat()
    events = []
    for r in db.execute("SELECT * FROM events WHERE studio_id = ? ORDER BY event_date DESC",
                        (u["id"],)):
        ev = event_with_roles(r)
        ev["applicant_count"] = sum(
            len([b for b in role["bookings"] if b["status"] in ("applied", "invited")])
            for role in ev["roles"])
        events.append(ev)

    # calendar payload: date -> list of events on that date (app events + notes)
    cal = {}
    for ev in events:
        for d in event_dates(ev):
            cal.setdefault(d, []).append(
                {"type": "event", "title": ev["title"], "id": ev["id"],
                 "status": ev["status"], "date_str": event_date_str(ev)})
    for n in db.execute("SELECT * FROM note_events WHERE user_id = ?", (u["id"],)):
        cal.setdefault(n["event_date"], []).append(
            {"type": "note", "title": n["title"], "id": 0,
             "status": "", "date_str": n["event_date"]})

    # crew availability: freelancers free on my upcoming events' dates
    import json as _json
    crew = []
    upcoming = [e for e in events if e["event_date"] >= today][:6]
    for ev in upcoming:
        role_keys = [r["role_key"] for r in ev["roles"]]
        found = {}
        for a in db.execute(
                """SELECT DISTINCT u.id, u.name, fp.skills, fp.rate
                   FROM availability a JOIN users u ON u.id = a.user_id
                   LEFT JOIN freelancer_profiles fp ON fp.user_id = u.id
                   WHERE a.avail_date >= ? AND a.avail_date <= ?""",
                (ev["event_date"], event_end(ev))):
            sk = [s for s in (a["skills"] or "").strip(",").split(",") if s]
            if any(k in sk for k in role_keys):
                found[a["id"]] = {"id": a["id"], "name": a["name"],
                                  "rate": a["rate"] or 0,
                                  "skills": [k for k in role_keys if k in sk]}
        crew.append({"ev": ev, "freelancers": sorted(found.values(), key=lambda f: f["name"])})
    return render_template("studio_home.html", user=u, events=events,
                           cal_data=_json.dumps(cal), crew=crew)


@app.route("/studio/post", methods=["GET", "POST"])
@login_required
def studio_post_page():
    """Dedicated create-event page (with copy-from-event prefill)."""
    u = current_user()
    if u["role"] != "studio":
        return redirect(url_for("freelancer_home"))
    if request.method == "POST":
        return _post_event_submit(u)
    db = get_db()
    pre = None
    copy_id = request.args.get("copy", 0, type=int)
    if copy_id:
        r = db.execute("SELECT * FROM events WHERE id = ? AND studio_id = ?",
                       (copy_id, u["id"])).fetchone()
        if r:
            pre = dict(r)
    return render_template("studio_post.html", user=u, pre=pre)


def _post_event_submit(u):
    db = get_db()
    u = current_user()
    if u["role"] != "studio":
        flash("Only studio accounts can post events.", "error")
        return redirect(url_for("freelancer_home"))
    db = get_db()
    title = request.form.get("title", "").strip()
    event_date = request.form.get("event_date", "").strip()
    end_date = request.form.get("end_date", "").strip() or None
    roles = [r for r in request.form.getlist("roles") if r in ROLES]
    if not (title and event_date and roles):
        flash("Event name, date and at least one role are required.", "error")
        return redirect(url_for("studio_post_page"))
    district = request.form.get("district", "").strip()
    if district not in TN_DISTRICTS:
        district = ""
    try:
        date.fromisoformat(event_date)
        if end_date:
            date.fromisoformat(end_date)
            if end_date < event_date:
                raise ValueError
    except ValueError:
        flash("Invalid dates (end date must be same day or after start).", "error")
        return redirect(url_for("studio_post_page"))
    eid = db.insert(
        """INSERT INTO events (studio_id, title, event_date, end_date, location, district, details)
           VALUES (?,?,?,?,?,?,?)""",
        (u["id"], title, event_date, end_date,
         request.form.get("location", "").strip(), district,
         request.form.get("details", "").strip()))
    for r in roles:
        db.execute("INSERT INTO event_roles (event_id, role_key) VALUES (?,?)", (eid, r))
    db.commit()
    flash(f"Event '{title}' posted — freelancers free on {event_date} can now see it.", "success")
    return redirect(url_for("event_detail", event_id=eid))


@app.route("/event/<int:event_id>")
@login_required
def event_detail(event_id):
    u = current_user()
    db = get_db()
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        flash("Event not found.", "error")
        return redirect(url_for("landing"))
    ev = event_with_roles(row)

    if u["role"] == "studio" and row["studio_id"] == u["id"]:
        # candidates available per role on this date
        for role in ev["roles"]:
            if role["filled"]:
                role["candidates"] = []
                continue
            skill_pat = f"%{role['role_key']}%"
            cands = []
            ev_days = event_dates(ev)
            for c in db.execute(
                    """SELECT DISTINCT u.id, u.name, u.phone, fp.rate, fp.city, fp.bio
                       FROM users u
                       JOIN freelancer_profiles fp ON fp.user_id = u.id
                       WHERE u.role = 'freelancer' AND fp.skills LIKE ?""",
                    (skill_pat,)):
                c = dict(c)
                free_days = {r["avail_date"] for r in db.execute(
                    "SELECT avail_date FROM availability WHERE user_id = ?", (c["id"],))}
                if not all(d in free_days for d in ev_days):
                    continue
                c["avg"], c["rcount"] = avg_rating(db, c["id"])
                c["busy"] = already_booked_excluding(db, c["id"], ev, ev["id"])
                c["existing"] = db.execute(
                    "SELECT status FROM bookings WHERE event_id=? AND role_key=? AND freelancer_id=?",
                    (ev["id"], role["role_key"], c["id"])).fetchone()
                cands.append(c)
            role["candidates"] = cands
        return render_template("event_studio.html", user=u, ev=ev)
    else:
        # freelancer or other viewer: read-only + apply buttons for freelancers
        profile = freelancer_profile(u["id"]) if u["role"] == "freelancer" else None
        my_skills = skills_list(profile)
        my_statuses = {}
        for b in db.execute("SELECT role_key, status FROM bookings WHERE event_id = ? AND freelancer_id = ?",
                            (ev["id"], u["id"])):
            my_statuses[b["role_key"]] = b["status"]
        return render_template("event_view.html", user=u, ev=ev,
                               my_skills=my_skills, my_statuses=my_statuses)


@app.route("/invite", methods=["POST"])
@login_required
def invite():
    u = current_user()
    if u["role"] != "studio":
        flash("Only studio accounts can invite.", "error")
        return redirect(url_for("freelancer_home"))
    db = get_db()
    event_id = request.form.get("event_id", type=int)
    role_key = request.form.get("role_key")
    freelancer_id = request.form.get("freelancer_id", type=int)
    ev = db.execute("SELECT * FROM events WHERE id = ? AND studio_id = ?",
                    (event_id, u["id"])).fetchone()
    fr = db.execute("SELECT * FROM users WHERE id = ? AND role = 'freelancer'",
                    (freelancer_id,)).fetchone()
    if not ev or not fr or role_key not in ROLES:
        flash("Invalid request.", "error")
        return redirect(url_for("studio_home"))
    if role_key not in skills_list(freelancer_profile(freelancer_id)):
        flash("That is not this freelancer's skill.", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    if not db.execute("SELECT 1 FROM availability WHERE user_id = ? AND avail_date = ?",
                     (freelancer_id, ev["event_date"])).fetchone():
        flash("That freelancer is not available on the event date.", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    if db.execute("SELECT 1 FROM bookings WHERE event_id=? AND role_key=? AND freelancer_id=?",
                  (event_id, role_key, freelancer_id)).fetchone():
        flash("Already requested for this role.", "error")
        return redirect(url_for("event_detail", event_id=event_id))
    db.execute(
        """INSERT INTO bookings (event_id, role_key, freelancer_id, status, initiated_by)
           VALUES (?,?,?,'invited','studio')""", (event_id, role_key, freelancer_id))
    db.commit()
    flash(f"Booking request sent to {fr['name']} for {role_label(role_key)}.", "success")
    notify(freelancer_id,
           f"{u['name']} (studio) sent you a booking request: {role_label(role_key)} for '{ev['title']}' ( {event_date_str(ev)} ).",
           f"/event/{event_id}")
    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/respond", methods=["POST"])
@login_required
def respond():
    """Shared: accept/decline (requests), cancel (confirmed bookings), close (events)."""
    u = current_user()
    db = get_db()
    action = request.form.get("action")
    booking_id = request.form.get("booking_id", type=int)

    if action == "close_event":
        event_id = request.form.get("event_id", type=int)
        db.execute("UPDATE events SET status = 'closed' WHERE id = ? AND studio_id = ?",
                   (event_id, u["id"]))
        db.commit()
        flash("Event closed.", "success")
        return redirect(url_for("studio_home"))

    b = db.execute(
        """SELECT b.*, e.studio_id, e.event_date, e.end_date, e.title AS event_title, e.status AS event_status
           FROM bookings b JOIN events e ON e.id = b.event_id WHERE b.id = ?""",
        (booking_id,)).fetchone()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("landing"))

    is_studio = (u["role"] == "studio" and b["studio_id"] == u["id"])
    is_freelancer = (u["role"] == "freelancer" and b["freelancer_id"] == u["id"])

    if action == "accept" and is_freelancer and b["status"] == "invited":
        if already_booked_excluding(db, u["id"], b, b["event_id"]):
            flash("You are already booked on another event that day.", "error")
            return redirect(url_for("freelancer_home"))
        db.execute("UPDATE bookings SET status = 'booked' WHERE id = ?", (booking_id,))
        db.commit()
        flash(f"Confirmed! You are booked as {role_label(b['role_key'])} for '{b['event_title']}'.", "success")
        notify(b["studio_id"],
               f"{u['name']} accepted your booking request: {role_label(b['role_key'])} for '{b['event_title']}' ({b['event_date']}).",
               f"/event/{b['event_id']}")

    elif action == "accept" and is_studio and b["status"] == "applied":
        if already_booked_excluding(db, b["freelancer_id"], b, b["event_id"]):
            flash("That freelancer is already booked elsewhere that day.", "error")
            return redirect(url_for("event_detail", event_id=b["event_id"]))
        db.execute("UPDATE bookings SET status = 'booked' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Applicant confirmed and booked.", "success")
        notify(b["freelancer_id"],
               f"You are BOOKED: {role_label(b['role_key'])} for '{b['event_title']}' ({b['event_date']}). 🎉",
               f"/event/{b['event_id']}")

    elif action == "decline" and (is_studio or is_freelancer) and b["status"] in ("applied", "invited"):
        db.execute("UPDATE bookings SET status = 'declined' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Request declined.", "success")
        other = b["studio_id"] if is_freelancer else b["freelancer_id"]
        notify(other,
               f"Request declined: {role_label(b['role_key'])} for '{b['event_title']}' ({b['event_date']}).")

    elif action == "cancel" and (is_studio or is_freelancer) and b["status"] == "booked":
        db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Booking cancelled.", "success")
        other = b["studio_id"] if is_freelancer else b["freelancer_id"]
        notify(other,
               f"Booking cancelled: {role_label(b['role_key'])} for '{b['event_title']}' ({b['event_date']}).")

    else:
        flash("You cannot do that.", "error")

    if is_studio and action != "cancel":
        return redirect(url_for("event_detail", event_id=b["event_id"]))
    if is_studio:
        return redirect(url_for("studio_home"))
    return redirect(url_for("freelancer_home"))


# ---------------------------------------------------------------- events browse
@app.route("/events")
@login_required
def browse_events():
    u = current_user()
    db = get_db()
    f_date = request.args.get("date", "").strip()
    f_skill = request.args.get("skill", "").strip()
    f_district = request.args.get("district", "").strip()
    today = TODAY().isoformat()

    q = """SELECT DISTINCT e.* FROM events e
            LEFT JOIN event_roles er ON er.event_id = e.id
            WHERE e.event_date >= ?"""
    params = [today]
    if f_skill in ROLES:
        q += " AND er.role_key = ?"
        params.append(f_skill)
    if f_district in TN_DISTRICTS:
        q += " AND e.district = ?"
        params.append(f_district)
    if f_date:
        try:
            date.fromisoformat(f_date)
            q += " AND e.event_date <= ? AND COALESCE(e.end_date, e.event_date) >= ?"
            params += [f_date, f_date]
        except ValueError:
            f_date = ""
    q += " ORDER BY e.event_date"

    events = []
    saved_set = set()
    if u["role"] == "freelancer":
        saved_set = {r["event_id"] for r in db.execute(
            "SELECT event_id FROM event_favorites WHERE user_id = ?", (u["id"],))}
    for r in db.execute(q, params).fetchall():
        ev = event_with_roles(r)
        ev["is_saved"] = ev["id"] in saved_set
        events.append(ev)
    return render_template("browse_events.html", user=u, events=events,
                           f_date=f_date, f_skill=f_skill, f_district=f_district,
                           role_opts=ROLES, district_opts=TN_DISTRICTS)



# ---------------------------------------------------------------- portfolio
@app.route("/portfolio/upload", methods=["POST"])
@login_required
def portfolio_upload():
    u = current_user()
    if u["role"] != "freelancer":
        flash("Only freelancers have a portfolio.", "error")
        return redirect(url_for("studio_home"))
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM portfolio_photos WHERE user_id = ?",
                       (u["id"],)).fetchone()[0]
    if count >= 8:
        flash("Portfolio limit reached (8 photos). Delete one first.", "error")
        return redirect(url_for("freelancer_profile_edit"))
    f = request.files.get("photo")
    if not f or not f.filename:
        flash("Choose a photo first.", "error")
        return redirect(url_for("freelancer_profile_edit"))
    if not f.mimetype.startswith("image/"):
        flash("Only image files are allowed.", "error")
        return redirect(url_for("freelancer_profile_edit"))
    # compress/resize so the DB stays small
    from io import BytesIO
    from PIL import Image as PILImage
    try:
        img = PILImage.open(f.stream)
        img = img.convert("RGB")
        img.thumbnail((1200, 1200))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=78)
        data = buf.getvalue()
    except Exception:
        flash("Could not read that image.", "error")
        return redirect(url_for("freelancer_profile_edit"))
    caption = request.form.get("caption", "").strip()[:100]
    db.execute("INSERT INTO portfolio_photos (user_id, caption, data, mime) VALUES (?,?,?,?)",
               (u["id"], caption, data, "image/jpeg"))
    db.commit()
    flash("Photo added to your portfolio.", "success")
    return redirect(url_for("freelancer_profile_edit"))


@app.route("/portfolio/delete/<int:photo_id>", methods=["POST"])
@login_required
def portfolio_delete(photo_id):
    u = current_user()
    db = get_db()
    db.execute("DELETE FROM portfolio_photos WHERE id = ? AND user_id = ?",
               (photo_id, u["id"]))
    db.commit()
    flash("Photo removed.", "success")
    return redirect(url_for("freelancer_profile_edit"))


@app.route("/portfolio/photo/<int:photo_id>")
@login_required
def portfolio_photo(photo_id):
    db = get_db()
    p = db.execute("SELECT data, mime FROM portfolio_photos WHERE id = ?",
                   (photo_id,)).fetchone()
    if not p:
        return "", 404
    data = p["data"]
    if not isinstance(data, bytes):
        data = bytes(data)  # psycopg2 returns memoryview
    return Response(data, mimetype=p["mime"] or "image/jpeg")


@app.route("/u/<int:user_id>")
@login_required
def public_profile(user_id):
    """Portfolio + reviews of a freelancer (for studios)."""
    db = get_db()
    fr = db.execute("SELECT * FROM users WHERE id = ? AND role = 'freelancer'",
                    (user_id,)).fetchone()
    if not fr:
        flash("Freelancer not found.", "error")
        return redirect(url_for("landing"))
    profile = freelancer_profile(user_id)
    photos = [dict(r) for r in db.execute(
        "SELECT id, caption, created_at FROM portfolio_photos WHERE user_id = ? ORDER BY id DESC",
        (user_id,))]
    reviews = [dict(r) for r in db.execute(
        """SELECT r.stars, r.comment, r.created_at, su.name AS studio_name
           FROM ratings r JOIN users su ON su.id = r.studio_id
           WHERE r.freelancer_id = ? ORDER BY r.id DESC LIMIT 20""", (user_id,))]
    avg, cnt = avg_rating(db, user_id)
    u = current_user()
    is_saved = False
    if u and u["role"] == "studio":
        is_saved = bool(db.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND target_user_id = ?",
            (u["id"], user_id)).fetchone())
    return render_template("public_profile.html", fr=fr, profile=profile,
                           photos=photos, reviews=reviews, avg=avg, rating_count=cnt,
                           is_saved=is_saved, user=u)


# ---------------------------------------------------------------- ratings
def avg_rating(db, freelancer_id):
    row = db.execute(
        "SELECT AVG(stars), COUNT(*) FROM ratings WHERE freelancer_id = ?",
        (freelancer_id,)).fetchone()
    cnt = row[1] or 0
    avg = round(row[0], 1) if row[0] is not None else 0
    return avg, cnt


def stars_str(avg):
    full = int(avg)
    half = 1 if (avg - full) >= 0.5 else 0
    return ("★" * full) + ("½" * half) + ("☆" * (5 - full - half))


app.jinja_env.globals.update(stars_str=stars_str)


@app.route("/rate", methods=["POST"])
@login_required
def rate():
    u = current_user()
    if u["role"] != "studio":
        flash("Only studios can rate freelancers.", "error")
        return redirect(url_for("freelancer_home"))
    db = get_db()
    booking_id = request.form.get("booking_id", type=int)
    stars = request.form.get("stars", type=int)
    comment = request.form.get("comment", "").strip()[:300]
    b = db.execute(
        """SELECT b.*, e.studio_id FROM bookings b
           JOIN events e ON e.id = b.event_id WHERE b.id = ?""", (booking_id,)).fetchone()
    if not b or b["studio_id"] != u["id"]:
        flash("Booking not found.", "error")
        return redirect(url_for("studio_home"))
    if b["status"] != "booked":
        flash("You can rate only after a booking is confirmed.", "error")
        return redirect(url_for("event_detail", event_id=b["event_id"]))
    if not stars or not (1 <= stars <= 5):
        flash("Pick 1 to 5 stars.", "error")
        return redirect(url_for("event_detail", event_id=b["event_id"]))
    if db.execute("SELECT 1 FROM ratings WHERE booking_id = ?", (booking_id,)).fetchone():
        flash("You already rated this booking.", "error")
        return redirect(url_for("event_detail", event_id=b["event_id"]))
    db.execute(
        """INSERT INTO ratings (booking_id, studio_id, freelancer_id, stars, comment)
           VALUES (?,?,?,?,?)""", (booking_id, u["id"], b["freelancer_id"], stars, comment))
    db.commit()
    fr = db.execute("SELECT name FROM users WHERE id = ?", (b["freelancer_id"],)).fetchone()[0]
    notify(b["freelancer_id"],
           f"{u['name']} rated you {stars}/5 ⭐",
           f"/u/{b['freelancer_id']}")
    flash(f"Rating saved for {fr}.", "success")
    return redirect(url_for("event_detail", event_id=b["event_id"]))


# ---------------------------------------------------------------- advance payment (UPI)
@app.route("/advance", methods=["POST"])
@login_required
def advance():
    u = current_user()
    db = get_db()
    booking_id = request.form.get("booking_id", type=int)
    action = request.form.get("action")
    b = db.execute(
        """SELECT b.*, e.studio_id, e.title AS event_title, e.event_date, e.end_date
           FROM bookings b JOIN events e ON e.id = b.event_id WHERE b.id = ?""",
        (booking_id,)).fetchone()
    if not b or b["studio_id"] != u["id"] or u["role"] != "studio":
        flash("Booking not found.", "error")
        return redirect(url_for("studio_home"))
    if b["status"] != "booked":
        flash("Advance applies to confirmed bookings only.", "error")
        return redirect(url_for("event_detail", event_id=b["event_id"]))
    if action == "set":
        try:
            amount = int(request.form.get("amount", "0") or 0)
        except ValueError:
            amount = 0
        if amount < 0:
            amount = 0
        db.execute("UPDATE bookings SET advance_amount = ? WHERE id = ?", (amount, booking_id))
        db.commit()
        flash("Advance amount saved.", "success")
    elif action == "paid":
        db.execute("UPDATE bookings SET advance_paid = 1 WHERE id = ?", (booking_id,))
        db.commit()
        notify(b["freelancer_id"],
               f"Advance paid: Rs.{b['advance_amount']} for '{b['event_title']}'.",
               f"/event/{b['event_id']}")
        flash("Advance marked as paid — freelancer notified.", "success")
    return redirect(url_for("event_detail", event_id=b["event_id"]))


# ---------------------------------------------------------------- security
@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    u = current_user()
    db = get_db()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not check_password_hash(u["password_hash"], current):
        flash("Current password is wrong.", "error")
    elif len(new) < 6:
        flash("New password must be at least 6 characters.", "error")
    elif new != confirm:
        flash("New passwords do not match.", "error")
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(new), u["id"]))
        db.commit()
        flash("Password changed successfully.", "success")
    return redirect(url_for("freelancer_profile_edit")
                    if u["role"] == "freelancer" else url_for("studio_home"))


# simple in-memory login throttling: 5 fails -> 5 minute lock
LOGIN_FAILS = {}

from time import time as _time


def login_locked(identifier):
    info = LOGIN_FAILS.get(identifier)
    if info and info["fails"] >= 5 and _time() < info["until"]:
        return True
    return False


def login_failed(identifier):
    info = LOGIN_FAILS.setdefault(identifier, {"fails": 0, "until": 0})
    info["fails"] += 1
    if info["fails"] >= 5:
        info["until"] = _time() + 300  # 5 minutes


def login_ok(identifier):
    LOGIN_FAILS.pop(identifier, None)


# ---------------------------------------------------------------- notifications
@app.route("/notifications")
@login_required
def notifications_page():
    u = current_user()
    db = get_db()
    items = []
    for n in db.execute(
            """SELECT * FROM notifications WHERE user_id = ?
               ORDER BY id DESC LIMIT 100""", (u["id"],)):
        items.append(dict(n))
    # opening the page marks everything as read
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (u["id"],))
    db.commit()
    return render_template("notifications.html", user=u, items=items)


# ---------------------------------------------------------------- super admin
def admin_perms():
    return [p for p in (session.get("admin_perms") or "").split(",") if p]

def is_super_admin():
    return session.get("admin") and "all" in admin_perms()

def admin_required(fn):
    perm = getattr(fn, "_perm", None)
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("Admin login required.", "error")
            return redirect(url_for("admin_page"))
        if perm and not (is_super_admin() or perm in admin_perms()):
            for p, ep in (("dashboard", "admin_dashboard"), ("users", "admin_users"),
                          ("events", "admin_events"), ("bookings", "admin_bookings")):
                if is_super_admin() or p in admin_perms():
                    flash("Your admin account has no access to that section.", "error")
                    return redirect(url_for(ep))
            flash("Your admin account has no sections assigned. Contact the super admin.", "error")
            session.pop("admin", None)
            session.pop("admin_user", None)
            session.pop("admin_perms", None)
            return redirect(url_for("admin_page"))
        return fn(*args, **kwargs)
    return wrapper

def requires_perm(perm):
    def deco(fn):
        fn._perm = perm
        return fn
    return deco



# ---------------------------------------------------------------- creators / saved / summary / messages

@app.route("/creators")
@login_required
def creators():
    """Find freelancers: search + skill / price / rating filters."""
    u = current_user()
    db = get_db()
    q = request.args.get("q", "").strip().lower()
    skill = request.args.get("skill", "").strip()
    price = request.args.get("price", "").strip()
    rating = request.args.get("rating", "").strip()
    try:
        price_v = int(price) if price else 0
    except ValueError:
        price_v = 0
    try:
        rating_v = float(rating) if rating else 0.0
    except ValueError:
        rating_v = 0.0

    out = []
    for r in db.execute(
            """SELECT u.id, u.name, u.phone, fp.skills, fp.rate, fp.city
               FROM users u JOIN freelancer_profiles fp ON fp.user_id = u.id
               WHERE u.role = 'freelancer'""").fetchall():
        c = dict(r)
        c["skills"] = [s for s in (c["skills"] or "").strip(",").split(",") if s]
        if skill in ROLES and skill not in c["skills"]:
            continue
        if q and q not in c["name"].lower() and q not in (c["city"] or "").lower():
            continue
        if price_v and not (0 < (c["rate"] or 0) <= price_v):
            continue
        c["avg"], c["rcount"] = avg_rating(db, c["id"])
        if rating_v and (c["rcount"] == 0 or c["avg"] < rating_v):
            continue
        ph = db.execute("SELECT id FROM portfolio_photos WHERE user_id = ? ORDER BY id LIMIT 1",
                        (c["id"],)).fetchone()
        c["photo_id"] = ph["id"] if ph else None
        c["saved"] = bool(db.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND target_user_id = ?",
            (u["id"], c["id"])).fetchone())
        out.append(c)
    out.sort(key=lambda c: (-(c["avg"] or 0), c["name"].lower()))
    return render_template("creators.html", user=u, creators=out,
                           q=request.args.get("q", "").strip(),
                           skill=skill, price=price, rating=rating)


@app.route("/api/favorite", methods=["POST"])
@login_required
def api_favorite():
    u = current_user()
    db = get_db()
    data = request.get_json(force=True, silent=True) or {}
    ftype = data.get("type")
    try:
        target = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False}), 400
    if ftype == "user":
        if not db.execute("SELECT 1 FROM users WHERE id = ?", (target,)).fetchone():
            return jsonify({"ok": False}), 404
        if db.execute("SELECT 1 FROM favorites WHERE user_id = ? AND target_user_id = ?",
                      (u["id"], target)).fetchone():
            db.execute("DELETE FROM favorites WHERE user_id = ? AND target_user_id = ?",
                       (u["id"], target))
            saved = False
        else:
            db.execute("INSERT INTO favorites (user_id, target_user_id) VALUES (?,?)",
                       (u["id"], target))
            saved = True
        db.commit()
        return jsonify({"ok": True, "saved": saved})
    if ftype == "event":
        if not db.execute("SELECT 1 FROM events WHERE id = ?", (target,)).fetchone():
            return jsonify({"ok": False}), 404
        if db.execute("SELECT 1 FROM event_favorites WHERE user_id = ? AND event_id = ?",
                      (u["id"], target)).fetchone():
            db.execute("DELETE FROM event_favorites WHERE user_id = ? AND event_id = ?",
                       (u["id"], target))
            saved = False
        else:
            db.execute("INSERT INTO event_favorites (user_id, event_id) VALUES (?,?)",
                       (u["id"], target))
            saved = True
        db.commit()
        return jsonify({"ok": True, "saved": saved})
    return jsonify({"ok": False}), 400


@app.route("/saved")
@login_required
def saved_page():
    u = current_user()
    db = get_db()
    if u["role"] == "studio":
        items = []
        for r in db.execute(
                """SELECT u.id, u.name, u.phone, fp.skills, fp.rate, fp.city
                   FROM favorites f JOIN users u ON u.id = f.target_user_id
                   LEFT JOIN freelancer_profiles fp ON fp.user_id = u.id
                   WHERE f.user_id = ? ORDER BY u.name""", (u["id"],)).fetchall():
            c = dict(r)
            c["avg"], c["rcount"] = avg_rating(db, c["id"])
            c["skills"] = [s for s in (c["skills"] or "").strip(",").split(",") if s]
            ph = db.execute("SELECT id FROM portfolio_photos WHERE user_id = ? ORDER BY id LIMIT 1",
                            (c["id"],)).fetchone()
            c["photo_id"] = ph["id"] if ph else None
            items.append(c)
        return render_template("saved.html", user=u, freelancers=items)
    events = []
    for r in db.execute(
            """SELECT e.* FROM event_favorites ef JOIN events e ON e.id = ef.event_id
               WHERE ef.user_id = ? ORDER BY e.event_date""", (u["id"],)).fetchall():
        events.append(event_with_roles(r))
    studios = []
    for r in db.execute(
            """SELECT u.id, u.name, u.phone, u.instagram_url, u.youtube_url
               FROM favorites f JOIN users u ON u.id = f.target_user_id
               WHERE f.user_id = ? AND u.role = 'studio' ORDER BY u.name""",
            (u["id"],)).fetchall():
        studios.append(dict(r))
    return render_template("saved.html", user=u, events=events, studios=studios)


@app.route("/s/<int:user_id>")
@login_required
def studio_public(user_id):
    """Public profile of a studio (for freelancers)."""
    u = current_user()
    db = get_db()
    st = db.execute("SELECT * FROM users WHERE id = ? AND role = 'studio'",
                    (user_id,)).fetchone()
    if not st:
        flash("Studio not found.", "error")
        return redirect(url_for("landing"))
    today = TODAY().isoformat()
    evts = []
    for r in db.execute(
            """SELECT * FROM events WHERE studio_id = ? AND event_date >= ?
               ORDER BY event_date LIMIT 10""", (user_id, today)).fetchall():
        evts.append(event_with_roles(r))
    is_saved = bool(db.execute(
        "SELECT 1 FROM favorites WHERE user_id = ? AND target_user_id = ?",
        (u["id"], user_id)).fetchone())
    return render_template("studio_public.html", user=u, st=st, events=evts,
                           is_saved=is_saved)


@app.route("/booking/<int:booking_id>")
@login_required
def booking_summary(booking_id):
    u = current_user()
    db = get_db()
    b = db.execute(
        """SELECT b.*, e.title, e.event_date, e.end_date, e.location, e.district,
                  e.studio_id, e.details
           FROM bookings b JOIN events e ON e.id = b.event_id
           WHERE b.id = ?""", (booking_id,)).fetchone()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("landing"))
    if u["role"] == "studio" and b["studio_id"] != u["id"]:
        flash("That booking belongs to another studio.", "error")
        return redirect(url_for("studio_home"))
    if u["role"] == "freelancer" and b["freelancer_id"] != u["id"]:
        flash("That booking belongs to someone else.", "error")
        return redirect(url_for("freelancer_home"))
    b = dict(b)
    b["date_str"] = event_date_str(b)
    b["role"] = role_label(b["role_key"])
    studio = db.execute("SELECT name, phone FROM users WHERE id = ?",
                        (b["studio_id"],)).fetchone()
    fr = db.execute("SELECT name, phone FROM users WHERE id = ?",
                    (b["freelancer_id"],)).fetchone()
    fp = db.execute("SELECT rate, upi_id FROM freelancer_profiles WHERE user_id = ?",
                    (b["freelancer_id"],)).fetchone()
    b["studio_name"] = studio["name"]
    b["studio_phone"] = studio["phone"] or ""
    b["freelancer_name"] = fr["name"]
    b["freelancer_phone"] = fr["phone"] or ""
    b["rate"] = fp["rate"] if fp else 0
    b["upi_id"] = (fp["upi_id"] if fp and fp["upi_id"] else "")
    return render_template("booking_summary.html", user=u, b=b)


@app.route("/messages")
@login_required
def messages_page():
    u = current_user()
    db = get_db()
    convs = {}
    for m in db.execute(
            """SELECT * FROM messages WHERE sender_id = ? OR receiver_id = ?
               ORDER BY id""", (u["id"], u["id"])).fetchall():
        other = m["receiver_id"] if m["sender_id"] == u["id"] else m["sender_id"]
        c = convs.setdefault(other, {"user_id": other, "unread": 0})
        c["last"] = m["body"]
        c["last_time"] = (m["created_at"] or "")[:16]
        if m["receiver_id"] == u["id"] and not m["is_read"]:
            c["unread"] += 1
    out = []
    for oid, c in convs.items():
        other = db.execute("SELECT name, role FROM users WHERE id = ?", (oid,)).fetchone()
        c["name"] = other["name"] if other else "Unknown"
        c["role"] = other["role"] if other else ""
        out.append(c)
    out.sort(key=lambda c: c.get("last_time") or "", reverse=True)
    return render_template("messages.html", user=u, convs=out)


@app.route("/messages/<int:other_id>")
@login_required
def chat_page(other_id):
    u = current_user()
    db = get_db()
    if other_id == u["id"]:
        return redirect(url_for("messages_page"))
    other = db.execute("SELECT * FROM users WHERE id = ?", (other_id,)).fetchone()
    if not other:
        flash("User not found.", "error")
        return redirect(url_for("messages_page"))
    return render_template("chat.html", user=u, other=other)


@app.route("/api/messages/<int:other_id>", methods=["GET", "POST"])
@login_required
def api_messages(other_id):
    u = current_user()
    db = get_db()
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (other_id,)).fetchone():
        return jsonify({"ok": False}), 404
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        body = (data.get("body") or "").strip()
        if not body:
            return jsonify({"ok": False, "error": "empty"}), 400
        db.insert("INSERT INTO messages (sender_id, receiver_id, body) VALUES (?,?,?)",
                  (u["id"], other_id, body[:2000]))
        db.commit()
        try:
            notify(other_id, f"New message from {u['name']}", f"/messages/{u['id']}")
        except Exception:
            pass
        return jsonify({"ok": True})
    after = request.args.get("after", 0, type=int)
    if after:
        rows = db.execute(
            """SELECT * FROM messages
               WHERE ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
                 AND id > ? ORDER BY id""", (u["id"], other_id, other_id, u["id"], after)).fetchall()
    else:
        rows = list(reversed(db.execute(
            """SELECT * FROM messages
               WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
               ORDER BY id DESC LIMIT 60""", (u["id"], other_id, other_id, u["id"])).fetchall()))
        db.execute("""UPDATE messages SET is_read = 1
                     WHERE sender_id = ? AND receiver_id = ? AND is_read = 0""",
                   (other_id, u["id"]))
        db.commit()
    msgs = [{"id": m["id"], "mine": m["sender_id"] == u["id"],
             "body": m["body"], "t": (m["created_at"] or "")[11:16]} for m in rows]
    return jsonify({"ok": True, "messages": msgs})


@app.route("/admin")
def admin_page():
    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html")


@app.route("/admin/login", methods=["POST"])
def admin_login():
    db = get_db()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    a = db.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
    if a and check_password_hash(a["password_hash"], password):
        session["admin"] = True
        session["admin_user"] = a["username"]
        session["admin_perms"] = "all"
        flash("Welcome back, Super Admin!", "success")
        return redirect(url_for("admin_dashboard"))
    s = db.execute("SELECT * FROM staff_admins WHERE username = ?", (username,)).fetchone()
    if s and check_password_hash(s["password_hash"], password):
        session["admin"] = True
        session["admin_user"] = s["username"]
        session["admin_perms"] = s["perms"] or ""
        flash(f"Welcome, {s['username']}!", "success")
        if "dashboard" in admin_perms():
            return redirect(url_for("admin_dashboard"))
        for p, ep in (("users", "admin_users"), ("events", "admin_events"), ("bookings", "admin_bookings")):
            if p in admin_perms():
                return redirect(url_for(ep))
        return redirect(url_for("admin_settings"))
    flash("Wrong admin username or password.", "error")
    return redirect(url_for("admin_page"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.pop("admin_user", None)
    session.pop("admin_perms", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/dashboard")
@admin_required
@requires_perm("dashboard")
def admin_dashboard():
    db = get_db()
    stats = {
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "studios": db.execute("SELECT COUNT(*) FROM users WHERE role='studio'").fetchone()[0],
        "freelancers": db.execute("SELECT COUNT(*) FROM users WHERE role='freelancer'").fetchone()[0],
        "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "open_events": db.execute("SELECT COUNT(*) FROM events WHERE status='open'").fetchone()[0],
        "bookings": db.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
        "confirmed": db.execute("SELECT COUNT(*) FROM bookings WHERE status='booked'").fetchone()[0],
    }
    recent = []
    for b in db.execute(
            """SELECT b.*, e.title AS event_title, e.event_date,
                      su.name AS studio_name, fu.name AS freelancer_name
               FROM bookings b
               JOIN events e ON e.id = b.event_id
               JOIN users su ON su.id = e.studio_id
               JOIN users fu ON fu.id = b.freelancer_id
               ORDER BY b.id DESC LIMIT 10"""):
        recent.append(dict(b))

    # ---- reports ----
    bookings_month = [dict(r) for r in db.execute(
        """SELECT substr(created_at, 1, 7) AS ym, COUNT(*) AS c
           FROM bookings GROUP BY substr(created_at, 1, 7)
           ORDER BY ym DESC LIMIT 6""")]
    bookings_month.reverse()
    top_freelancers = [dict(r) for r in db.execute(
        """SELECT u.name, COUNT(*) AS c FROM bookings b
           JOIN users u ON u.id = b.freelancer_id
           WHERE b.status = 'booked'
           GROUP BY u.id, u.name ORDER BY c DESC LIMIT 5""")]
    top_studios = [dict(r) for r in db.execute(
        """SELECT u.name, COUNT(*) AS c FROM events e
           JOIN users u ON u.id = e.studio_id
           GROUP BY u.id, u.name ORDER BY c DESC LIMIT 5""")]
    role_demand = [dict(r) for r in db.execute(
        """SELECT role_key, COUNT(*) AS c FROM event_roles
           GROUP BY role_key ORDER BY c DESC""")]
    return render_template("admin_dashboard.html", stats=stats, recent=recent,
                           bookings_month=bookings_month,
                           top_freelancers=top_freelancers,
                           top_studios=top_studios,
                           role_demand=role_demand)


@app.route("/admin/users")
@admin_required
@requires_perm("users")
def admin_users():
    db = get_db()
    role_filter = request.args.get("role", "").strip()
    users = []
    q = "SELECT * FROM users"
    if role_filter in ("studio", "freelancer"):
        q += " WHERE role = ?"
        rows = db.execute(q + " ORDER BY id", (role_filter,)).fetchall()
    else:
        rows = db.execute(q + " ORDER BY id").fetchall()
    for u in rows:
        u = dict(u)
        if u["role"] == "freelancer":
            p = db.execute("SELECT * FROM freelancer_profiles WHERE user_id = ?",
                            (u["id"],)).fetchone()
            u["skills"] = skills_list(p)
            u["rate"] = p["rate"] if p else 0
            u["city"] = p["city"] if p else ""
        users.append(u)
    return render_template("admin_users.html", users=users)


@app.route("/admin/user/<int:user_id>", methods=["GET", "POST"])
@admin_required
@requires_perm("users")
def admin_user_edit(user_id):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not u:
        flash("User not found.", "error")
        return redirect(url_for("admin_users"))
    profile = db.execute("SELECT * FROM freelancer_profiles WHERE user_id = ?",
                         (user_id,)).fetchone()

    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "delete":
            # cascade: remove everything this user owns
            if u["role"] == "studio":
                for ev in db.execute("SELECT id FROM events WHERE studio_id = ?",
                                     (user_id,)).fetchall():
                    db.execute("DELETE FROM bookings WHERE event_id = ?", (ev["id"],))
                    db.execute("DELETE FROM event_roles WHERE event_id = ?", (ev["id"],))
                db.execute("DELETE FROM events WHERE studio_id = ?", (user_id,))
            else:
                db.execute("DELETE FROM availability WHERE user_id = ?", (user_id,))
                db.execute("DELETE FROM freelancer_profiles WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM bookings WHERE freelancer_id = ?", (user_id,))
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            flash(f"User '{u['name']}' and all their data deleted.", "success")
            return redirect(url_for("admin_users"))

        # save edits
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        new_password = request.form.get("new_password", "")
        if not (name and email):
            flash("Name and email are required.", "error")
        elif db.execute("SELECT 1 FROM users WHERE email = ? AND id != ?",
                        (email, user_id)).fetchone():
            flash("Another account already uses that email.", "error")
        elif new_password and len(new_password) < 6:
            flash("New password must be at least 6 characters.", "error")
        else:
            db.execute("UPDATE users SET name = ?, email = ?, phone = ? WHERE id = ?",
                       (name, email, phone, user_id))
            if new_password:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (generate_password_hash(new_password), user_id))
            if u["role"] == "freelancer":
                valid = [s for s in request.form.getlist("skills") if s in ROLES]
                if not valid:
                    db.rollback()
                    flash("Freelancer needs at least one skill.", "error")
                else:
                    try:
                        rate = int(request.form.get("rate", "0") or 0)
                    except ValueError:
                        rate = 0
                    if profile:
                        db.execute(
                            """UPDATE freelancer_profiles SET skills=?, rate=?, city=?, bio=?
                               WHERE user_id = ?""",
                            ("," + ",".join(valid) + ",", rate,
                             request.form.get("city", "").strip(),
                             request.form.get("bio", "").strip(), user_id))
                    else:
                        db.execute(
                            """INSERT INTO freelancer_profiles (user_id, skills, rate, city, bio)
                               VALUES (?,?,?,?,?)""",
                            (user_id, "," + ",".join(valid) + ",", rate,
                             request.form.get("city", "").strip(),
                             request.form.get("bio", "").strip()))
            db.commit()
            flash(f"User '{name}' updated.", "success")
            return redirect(url_for("admin_users"))

        db.rollback()
        u = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        profile = db.execute("SELECT * FROM freelancer_profiles WHERE user_id = ?",
                             (user_id,)).fetchone()

    return render_template("admin_user_edit.html", u=u, profile=profile,
                           my_skills=skills_list(profile))


@app.route("/admin/events")
@admin_required
@requires_perm("events")
def admin_events():
    db = get_db()
    f_status = request.args.get("status", "").strip()
    f_district = request.args.get("district", "").strip()
    events = []
    q = "SELECT e.*, u.name AS studio_name FROM events e JOIN users u ON u.id = e.studio_id WHERE 1=1"
    params = []
    if f_status in ("open", "closed"):
        q += " AND e.status = ?"
        params.append(f_status)
    if f_district in TN_DISTRICTS:
        q += " AND e.district = ?"
        params.append(f_district)
    rows = db.execute(q + " ORDER BY e.event_date DESC", params).fetchall()
    for r in rows:
        ev = dict(r)
        ev["roles"] = [dict(x) for x in db.execute(
            "SELECT * FROM event_roles WHERE event_id = ?", (ev["id"],))]
        ev["booking_count"] = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE event_id = ?",
            (ev["id"],)).fetchone()[0]
        events.append(ev)
    return render_template("admin_events.html", events=events,
                           f_status=f_status, f_district=f_district,
                           district_opts=TN_DISTRICTS)


@app.route("/admin/event/<int:event_id>", methods=["GET", "POST"])
@admin_required
@requires_perm("events")
def admin_event_edit(event_id):
    db = get_db()
    ev = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not ev:
        flash("Event not found.", "error")
        return redirect(url_for("admin_events"))

    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "delete":
            db.execute("DELETE FROM bookings WHERE event_id = ?", (event_id,))
            db.execute("DELETE FROM event_roles WHERE event_id = ?", (event_id,))
            db.execute("DELETE FROM events WHERE id = ?", (event_id,))
            db.commit()
            flash(f"Event '{ev['title']}' deleted.", "success")
            return redirect(url_for("admin_events"))

        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        status = request.form.get("status", "open")
        if not (title and event_date):
            flash("Title and date are required.", "error")
        else:
            db.execute(
                "UPDATE events SET title=?, event_date=?, location=?, details=?, status=? WHERE id=?",
                (title, event_date, request.form.get("location", "").strip(),
                 request.form.get("details", "").strip(),
                 status if status in ("open", "closed") else "open", event_id))
            # update roles: can only remove roles with no bookings
            wanted = [r for r in request.form.getlist("roles") if r in ROLES]
            current = [r["role_key"] for r in db.execute(
                "SELECT role_key FROM event_roles WHERE event_id = ?", (event_id,))]
            for r in wanted:
                if r not in current:
                    db.execute("INSERT INTO event_roles (event_id, role_key) VALUES (?,?)",
                               (event_id, r))
            for r in current:
                if r not in wanted:
                    has_booking = db.execute(
                        "SELECT 1 FROM bookings WHERE event_id=? AND role_key=?",
                        (event_id, r)).fetchone()
                    if has_booking:
                        flash(f"Cannot remove {role_label(r)} — bookings exist for it. "
                              f"Delete those bookings first.", "error")
                    else:
                        db.execute("DELETE FROM event_roles WHERE event_id=? AND role_key=?",
                                   (event_id, r))
            db.commit()
            flash(f"Event '{title}' updated.", "success")
            return redirect(url_for("admin_events"))

    roles = [r["role_key"] for r in db.execute(
        "SELECT role_key FROM event_roles WHERE event_id = ?", (event_id,))]
    return render_template("admin_event_edit.html", ev=ev, current_roles=roles)


@app.route("/admin/bookings")
@admin_required
@requires_perm("bookings")
def admin_bookings():
    db = get_db()
    bookings = []
    for b in db.execute(
            """SELECT b.*, e.title AS event_title, e.event_date, e.studio_id,
                      su.name AS studio_name, fu.name AS freelancer_name
               FROM bookings b
               JOIN events e ON e.id = b.event_id
               JOIN users su ON su.id = e.studio_id
               JOIN users fu ON fu.id = b.freelancer_id
               ORDER BY b.id DESC"""):
        bookings.append(dict(b))
    return render_template("admin_bookings.html", bookings=bookings)


@app.route("/admin/booking/<int:booking_id>", methods=["POST"])
@admin_required
@requires_perm("bookings")
def admin_booking_update(booking_id):
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("admin_bookings"))
    action = request.form.get("action")
    if action == "delete":
        db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        db.commit()
        flash("Booking deleted.", "success")
    elif action == "status":
        new_status = request.form.get("status", "")
        if new_status in ("applied", "invited", "booked", "declined", "cancelled"):
            db.execute("UPDATE bookings SET status = ? WHERE id = ?", (new_status, booking_id))
            db.commit()
            flash(f"Booking status changed to {new_status}.", "success")
        else:
            flash("Invalid status.", "error")
    return redirect(url_for("admin_bookings"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if not is_super_admin():
        flash("Only the super admin can open settings.", "error")
        for p, ep in (("dashboard", "admin_dashboard"), ("users", "admin_users"),
                      ("events", "admin_events"), ("bookings", "admin_bookings")):
            if p in admin_perms():
                return redirect(url_for(ep))
        return redirect(url_for("admin_page"))
    return _admin_settings_impl()


def _admin_settings_impl():
    db = get_db()
    admin = db.execute("SELECT * FROM admins ORDER BY id LIMIT 1").fetchone()
    if request.method == "POST" and request.form.get("action") == "staff_new":
        suser = request.form.get("staff_username", "").strip().lower()
        spass = request.form.get("staff_password", "")
        perms = ",".join(p for p in request.form.getlist("perms")
                         if p in ("dashboard", "users", "events", "bookings"))
        if not suser or len(spass) < 6:
            flash("Staff username + password (min 6 chars) required.", "error")
        elif db.execute("SELECT 1 FROM staff_admins WHERE username = ?", (suser,)).fetchone() \
                or db.execute("SELECT 1 FROM admins WHERE username = ?", (suser,)).fetchone():
            flash("That username is already taken.", "error")
        elif not perms:
            flash("Pick at least one section for the staff account.", "error")
        else:
            db.insert("INSERT INTO staff_admins (username, password_hash, perms) VALUES (?,?,?)",
                      (suser, generate_password_hash(spass), perms))
            db.commit()
            flash(f"Staff account '{suser}' created.", "success")
        return redirect(url_for("admin_settings"))
    if request.method == "POST" and request.form.get("action") == "staff_del":
        sid = request.form.get("staff_id", 0, type=int)
        db.execute("DELETE FROM staff_admins WHERE id = ?", (sid,))
        db.commit()
        flash("Staff account removed.", "success")
        return redirect(url_for("admin_settings"))
    if request.method == "POST" and request.form.get("action") == "social":
        for k in SOCIAL_KEYS:
            v = request.form.get(k, "").strip()
            if v and not (v.startswith("http://") or v.startswith("https://")):
                v = "https://" + v
            set_setting(db, k, v)
        db.commit()
        flash("Social media links saved. They now show on the home page.", "success")
        return redirect(url_for("admin_settings"))
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_username = request.form.get("username", "").strip().lower()
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(admin["password_hash"], current_pw):
            flash("Current password is wrong.", "error")
        elif not new_username:
            flash("Username cannot be empty.", "error")
        elif new_password and new_password != confirm:
            flash("New passwords do not match.", "error")
        elif new_password and len(new_password) < 6:
            flash("New password must be at least 6 characters.", "error")
        else:
            if new_password:
                db.execute("UPDATE admins SET username=?, password_hash=? WHERE id=?",
                           (new_username, generate_password_hash(new_password), admin["id"]))
            else:
                db.execute("UPDATE admins SET username=? WHERE id=?",
                           (new_username, admin["id"]))
            db.commit()
            flash("Admin login updated. Use the new details next time.", "success")
            return redirect(url_for("admin_page"))
        return redirect(url_for("admin_settings"))
    staff = db.execute("SELECT * FROM staff_admins ORDER BY id").fetchall()
    return render_template("admin_settings.html", admin_username=admin["username"],
                           social={k: get_setting(db, k) for k in SOCIAL_KEYS},
                           staff=staff)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "resetadmin":
        reset_admin()
        print("=" * 50)
        print("Admin login reset!")
        print("  username: admin")
        print("  password: admin123")
        print("Login panni Settings la password maathunga!")
        print("=" * 50)
    else:
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=False)
