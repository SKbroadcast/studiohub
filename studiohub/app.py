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

from flask import (Flask, render_template, request, redirect, url_for,
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
}

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
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS freelancer_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    skills  TEXT NOT NULL DEFAULT '',  -- ',key,key,' comma padded
    rate    INTEGER DEFAULT 0,        -- Rs per day
    city    TEXT DEFAULT '',
    bio     TEXT DEFAULT ''
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
    location   TEXT DEFAULT '',
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
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE (event_id, role_key, freelancer_id)
);
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def reset_admin(username="admin", password="admin123"):
    """Set the single admin account to the given username/password."""
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    row = db.execute("SELECT id FROM admins ORDER BY id LIMIT 1").fetchone()
    if row:
        db.execute("UPDATE admins SET username = ?, password_hash = ? WHERE id = ?",
                   (username, generate_password_hash(password), row[0]))
    else:
        db.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)))
    db.commit()
    db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    # seed the default super admin (username: admin / password: admin123)
    if not db.execute("SELECT 1 FROM admins").fetchone():
        db.execute(
            "INSERT INTO admins (username, password_hash) VALUES ('admin', ?)",
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


app.jinja_env.globals.update(role_label=role_label, ROLES=ROLES)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            flash("Please log in first.", "error")
            return redirect(url_for("landing"))
        return fn(*args, **kwargs)
    return wrapper


def already_booked_on_date(db, freelancer_id, event_date, exclude_event_id=None):
    """Returns True if freelancer has a confirmed booking on this date."""
    q = """SELECT 1 FROM bookings b JOIN events e ON e.id = b.event_id
           WHERE b.freelancer_id = ? AND b.status = 'booked' AND e.event_date = ?"""
    params = [freelancer_id, event_date]
    if exclude_event_id:
        q += " AND b.event_id != ?"
        params.append(exclude_event_id)
    return db.execute(q, params).fetchone() is not None


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
        role["bookings"] = [dict(b) for b in db.execute(
            """SELECT b.*, u.name AS freelancer_name, fp.rate AS rate
               FROM bookings b JOIN users u ON u.id = b.freelancer_id
               LEFT JOIN freelancer_profiles fp ON fp.user_id = u.id
               WHERE b.event_id = ? AND b.role_key = ?
               ORDER BY CASE b.status WHEN 'booked' THEN 0 WHEN 'applied' THEN 1
                         WHEN 'invited' THEN 2 ELSE 3 END, b.created_at DESC""",
            (ev["id"], role["role_key"]))]
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


@app.route("/register", methods=["POST"])
def register():
    db = get_db()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role")
    phone = request.form.get("phone", "").strip()

    if not (name and email and password and role in ("studio", "freelancer")):
        flash("Please fill all required fields.", "error")
        return redirect(url_for("landing"))
    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("landing"))
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        flash("This email is already registered. Try logging in.", "error")
        return redirect(url_for("landing"))

    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, role, phone) VALUES (?,?,?,?,?)",
        (name, email, generate_password_hash(password), role, phone))
    uid = cur.lastrowid

    if role == "freelancer":
        skills = request.form.getlist("skills")
        valid = [s for s in skills if s in ROLES]
        if not valid:
            db.execute("DELETE FROM users WHERE id = ?", (uid,))
            db.commit()
            flash("Please pick at least one skill (photographer / videographer).", "error")
            return redirect(url_for("landing"))
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
    # accept email OR mobile number as login id
    user = db.execute(
        """SELECT * FROM users WHERE email = ?
           OR (phone != '' AND phone = ?)""",
        (identifier, identifier)).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        session["uid"] = user["id"]
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("studio_home" if user["role"] == "studio" else "freelancer_home"))
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
            JOIN availability a ON a.user_id = ? AND a.avail_date = e.event_date
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
            """SELECT b.*, e.title AS event_title, e.event_date, e.location, e.studio_id
               FROM bookings b JOIN events e ON e.id = b.event_id
               WHERE b.freelancer_id = ? ORDER BY e.event_date DESC""", (u["id"],)):
        b = dict(b)
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
        return jsonify({"dates": [r["avail_date"] for r in rows]})
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
        if already_booked_on_date(db, u["id"], d):
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
                """UPDATE freelancer_profiles SET skills = ?, rate = ?, city = ?, bio = ?
                   WHERE user_id = ?""",
                ("," + ",".join(valid) + ",", rate,
                 request.form.get("city", "").strip(),
                 request.form.get("bio", "").strip(), u["id"]))
            db.execute("UPDATE users SET phone = ? WHERE id = ?",
                       (request.form.get("phone", "").strip(), u["id"]))
            db.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("freelancer_home"))
    profile = freelancer_profile(u["id"])
    return render_template("profile.html", user=u, profile=profile,
                           my_skills=skills_list(profile))


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
    if already_booked_on_date(db, u["id"], ev["event_date"], exclude_event_id=event_id):
        flash("You are already booked on another event that day.", "error")
        return redirect(url_for("freelancer_home"))
    if db.execute("SELECT 1 FROM bookings WHERE event_id = ? AND role_key = ? AND freelancer_id = ?",
                  (event_id, role_key, u["id"])).fetchone():
        flash("You already applied for this role.", "error")
        return redirect(url_for("freelancer_home"))
    # make sure the date is marked available
    if not db.execute("SELECT 1 FROM availability WHERE user_id = ? AND avail_date = ?",
                      (u["id"], ev["event_date"])).fetchone():
        db.execute("INSERT INTO availability (user_id, avail_date) VALUES (?,?)",
                   (u["id"], ev["event_date"]))
    db.execute(
        """INSERT INTO bookings (event_id, role_key, freelancer_id, status, initiated_by)
           VALUES (?,?,?,'applied','freelancer')""", (event_id, role_key, u["id"]))
    db.commit()
    flash(f"Applied as {role_label(role_key)} for '{ev['title']}'. The studio will confirm.", "success")
    return redirect(url_for("freelancer_home"))


# ---------------------------------------------------------------- studio
@app.route("/studio")
@login_required
def studio_home():
    u = current_user()
    if u["role"] != "studio":
        return redirect(url_for("freelancer_home"))
    db = get_db()
    events = []
    for r in db.execute("SELECT * FROM events WHERE studio_id = ? ORDER BY event_date DESC",
                        (u["id"],)):
        ev = event_with_roles(r)
        ev["applicant_count"] = sum(
            len([b for b in role["bookings"] if b["status"] in ("applied", "invited")])
            for role in ev["roles"])
        events.append(ev)
    return render_template("studio_home.html", user=u, events=events)


@app.route("/studio/post", methods=["POST"])
@login_required
def post_event():
    u = current_user()
    if u["role"] != "studio":
        flash("Only studio accounts can post events.", "error")
        return redirect(url_for("freelancer_home"))
    db = get_db()
    title = request.form.get("title", "").strip()
    event_date = request.form.get("event_date", "").strip()
    roles = [r for r in request.form.getlist("roles") if r in ROLES]
    if not (title and event_date and roles):
        flash("Event name, date and at least one role are required.", "error")
        return redirect(url_for("studio_home"))
    try:
        date.fromisoformat(event_date)
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("studio_home"))
    cur = db.execute(
        "INSERT INTO events (studio_id, title, event_date, location, details) VALUES (?,?,?,?,?)",
        (u["id"], title, event_date,
         request.form.get("location", "").strip(), request.form.get("details", "").strip()))
    eid = cur.lastrowid
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
            for c in db.execute(
                    """SELECT DISTINCT u.id, u.name, u.phone, fp.rate, fp.city, fp.bio
                       FROM users u
                       JOIN availability a ON a.user_id = u.id AND a.avail_date = ?
                       JOIN freelancer_profiles fp ON fp.user_id = u.id
                       WHERE u.role = 'freelancer' AND fp.skills LIKE ?""",
                    (ev["event_date"], skill_pat)):
                c = dict(c)
                c["busy"] = already_booked_on_date(db, c["id"], ev["event_date"],
                                                   exclude_event_id=ev["id"])
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
        """SELECT b.*, e.studio_id, e.event_date, e.title AS event_title, e.status AS event_status
           FROM bookings b JOIN events e ON e.id = b.event_id WHERE b.id = ?""",
        (booking_id,)).fetchone()
    if not b:
        flash("Booking not found.", "error")
        return redirect(url_for("landing"))

    is_studio = (u["role"] == "studio" and b["studio_id"] == u["id"])
    is_freelancer = (u["role"] == "freelancer" and b["freelancer_id"] == u["id"])

    if action == "accept" and is_freelancer and b["status"] == "invited":
        if already_booked_on_date(db, u["id"], b["event_date"], exclude_event_id=b["event_id"]):
            flash("You are already booked on another event that day.", "error")
            return redirect(url_for("freelancer_home"))
        db.execute("UPDATE bookings SET status = 'booked' WHERE id = ?", (booking_id,))
        db.commit()
        flash(f"Confirmed! You are booked as {role_label(b['role_key'])} for '{b['event_title']}'.", "success")

    elif action == "accept" and is_studio and b["status"] == "applied":
        if already_booked_on_date(db, b["freelancer_id"], b["event_date"], exclude_event_id=b["event_id"]):
            flash("That freelancer is already booked elsewhere that day.", "error")
            return redirect(url_for("event_detail", event_id=b["event_id"]))
        db.execute("UPDATE bookings SET status = 'booked' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Applicant confirmed and booked.", "success")

    elif action == "decline" and (is_studio or is_freelancer) and b["status"] in ("applied", "invited"):
        db.execute("UPDATE bookings SET status = 'declined' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Request declined.", "success")

    elif action == "cancel" and (is_studio or is_freelancer) and b["status"] == "booked":
        db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        db.commit()
        flash("Booking cancelled.", "success")

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
    events = []
    for r in db.execute(
            """SELECT * FROM events WHERE event_date >= ? ORDER BY event_date""",
            (TODAY().isoformat(),)):
        ev = event_with_roles(r)
        if u["role"] == "studio" and ev["studio_id"] != u["id"]:
            pass  # studios can see other studios' events too (market pulse)
        events.append(ev)
    return render_template("browse_events.html", user=u, events=events)


# ---------------------------------------------------------------- super admin
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("Admin login required.", "error")
            return redirect(url_for("admin_page"))
        return fn(*args, **kwargs)
    return wrapper


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
        flash("Welcome back, Super Admin!", "success")
        return redirect(url_for("admin_dashboard"))
    flash("Wrong admin username or password.", "error")
    return redirect(url_for("admin_page"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("admin_page"))


@app.route("/admin/dashboard")
@admin_required
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
    return render_template("admin_dashboard.html", stats=stats, recent=recent)


@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    users = []
    for u in db.execute("SELECT * FROM users ORDER BY id"):
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
def admin_events():
    db = get_db()
    events = []
    for r in db.execute("SELECT e.*, u.name AS studio_name FROM events e "
                        "JOIN users u ON u.id = e.studio_id ORDER BY e.event_date DESC"):
        ev = dict(r)
        ev["roles"] = [dict(x) for x in db.execute(
            "SELECT * FROM event_roles WHERE event_id = ?", (ev["id"],))]
        ev["booking_count"] = db.execute(
            "SELECT COUNT(*) FROM bookings WHERE event_id = ?",
            (ev["id"],)).fetchone()[0]
        events.append(ev)
    return render_template("admin_events.html", events=events)


@app.route("/admin/event/<int:event_id>", methods=["GET", "POST"])
@admin_required
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
    db = get_db()
    admin = db.execute("SELECT * FROM admins ORDER BY id LIMIT 1").fetchone()
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
    return render_template("admin_settings.html", admin_username=admin["username"])


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
