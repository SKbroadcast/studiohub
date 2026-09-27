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
