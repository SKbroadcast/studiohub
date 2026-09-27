# 📸 StudioHub

**Event studios × Freelance photographers & videographers**

Studios post events with the crew they need (traditional/candid photographer &
videographer). Freelancers mark the dates they are free. Both sides see each
other, match, and book — simple.

## How it works

1. **Studio** registers → posts an event ("Priya Wedding, Oct 5, need 1
   Traditional Photographer + 1 Candid Videographer").
2. **Freelancer** registers with skills (photography/videography,
   traditional/candid) and taps a calendar to mark free dates.
3. Freelancer's dashboard automatically shows **matching events** — only events
   on their free dates that need their skills. They hit **Apply**.
4. Studio sees the applicant on the event and hits **Book** — or opens the
   event page and directly **sends a booking request** to any freelancer who is
   free that date.
5. Both sides confirm. Double-booking the same date is blocked automatically.

## Run it locally

```bash
pip install -r requirements.txt
python3 app.py
# open http://localhost:5000
```

The SQLite database (`studiohub.db`) is created automatically on first run.

> Default port is 5000. Set `PORT` env var to change (the app also honours
> `PORT` on hosting platforms).
> For production, set `SECRET_KEY` env var to a long random string.

## Deploying (free options)

- **Render / Railway**: create a Python web service, point it at this folder,
  start command `python3 app.py`. The SQLite file lives on the instance disk —
  fine to start, upgrade to PostgreSQL later when you outgrow it.
- Any VPS with Python 3.10+ works the same way.

## Tech

- Python 3 + Flask (backend, single file `app.py`)
- SQLite (users, freelancer profiles, availability dates, events, bookings)
- Vanilla HTML/CSS/JS — no build step, mobile-friendly dark UI

## What's inside

| File | Purpose |
|---|---|
| `app.py` | Entire backend: auth, availability, events, bookings |
| `templates/` | Pages: landing/login, freelancer dashboard, studio dashboard, event pages |
| `static/style.css` | Styling (dark theme, responsive) |
| `static/app.js` | Availability calendar (tap dates to mark free) |

## Roles supported

- Traditional Photographer
- Traditional Videographer
- Candid Photographer
- Candid Videographer

## Safety rules built in

- One confirmed booking per freelancer per date (across all studios).
- A booked date cannot be removed from the availability calendar.
- Applying to an event auto-marks that date as free.
- Studios can only invite freelancers who are actually free on the event date.

## Ideas for v2

- Advance payment / UPI integration (Razorpay)
- WhatsApp notifications on invite/confirm
- Portfolio galleries, ratings & reviews
- Mobile app (same backend, Flutter or React Native front-end)
- Multi-day events & recurring availability (e.g. "free every Sunday")

## Super Admin Panel

Separate admin login at **`/admin`** (also linked from the landing page).

- **Default login:** username `admin` · password `admin123` — **change it in Settings right away**
- **Dashboard:** overall stats (users, studios, freelancers, events, bookings) + recent activity
- **Users:** edit any account (name, email, phone, skills, rate, city, bio), reset passwords, delete users (with all their data)
- **Events:** edit/delete any event across all studios (title, date, status, crew roles)
- **Bookings:** view all, change any booking status, delete bookings
- **Settings:** change the admin username & password

Admin accounts are stored in the `admins` table; the default one is seeded
automatically on first run. Existing databases are upgraded automatically.

### Forgot the admin login?

- **On your computer:** in the app folder run:
  `python app.py resetadmin`
  This resets to username `admin` / password `admin123`. Log in and change it in Settings.
- **On Render (hosted):** Dashboard → your service → **Environment** → add
  `ADMIN_USERNAME` and `ADMIN_PASSWORD` env vars → Save. The service restarts and
  those become the admin login. After logging in, you can delete those env vars
  (otherwise they override the stored password on every restart).

## v3 features

- **Multi-day events** — post events with a start and end date. Matching, conflict
  checks and the availability lock all respect the full date range.
- **Portfolio gallery** — freelancers upload up to 8 photos (auto-compressed).
  Studios view them on the freelancer's public profile (`/u/<id>`).
- **Ratings & reviews** — studios rate confirmed bookings (1-5 stars + review).
  Averages show everywhere freelancers are listed.
- **Advance payments (UPI)** — freelancers add a UPI ID; the event page shows a
  "Pay via UPI" deep link (opens any UPI app with amount prefilled) and the studio
  can mark the advance as paid. The freelancer is notified.
- **Security** — users can change their own password; 5 wrong logins locks the
  account for 5 minutes.
- **Admin reports** — bookings per month, top freelancers, top studios, role demand.

## PostgreSQL (data survives restarts on Render)

1. Render dashboard → **New +** → **Postgres** → create (free plan)
2. Open the Postgres service → **Connections** → copy the **Internal Database URL**
3. Open the StudioHub web service → **Environment** → add env var:
   `DATABASE_URL` = that URL → Save (service restarts)
4. All tables are created automatically on first start.

Without `DATABASE_URL` the app uses local SQLite (`studiohub.db`) — perfect for
running on your own computer.


## v11
- Tagline: "Book Your Wedding Crew in Minutes"
- Social links on home page (set them in Admin -> Settings)
- Admin login only via /admin URL
- Role renamed: "Drone Pilot"
- 3-dot menu (studio: Create event / My events / Profile / Logout; freelancer: Schedule notes / Note events / Events / Profile / Logout), notification bell stays outside
- Studio home: My events first, then post form; all 7 crew roles; district dropdown (TN districts)
- Schedule notes: app-booked events, date-wise
- Note events: manual outside bookings (show as booked in My Availability; tap booked date for details)
- Events page filters: date, skill, district
- New theme: deep navy / electric blue / studio orange / cyan, Inter + Noto Sans Tamil

## v12
- Studio: one "Create event" (duplicate "Post a new event" removed)
- Studio menu now has Schedule notes (own events, date-wise, with crew status)
- "View free freelancers" buttons on studio home & schedule notes
- Freelancer home: My profile card removed (Profile stays in the 3-dot menu)
