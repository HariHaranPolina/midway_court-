# Midway Court Split

A small full-stack app for managing Midway Park pickleball court bookings, players, split costs, and reimbursements.

## What it does

- Create a booking for Pickleball Courts 1–6
- Record who booked the court and paid the full court fee up front
- Prevent overlapping bookings for the same court/time
- Let 4, 5, 6, or another configured number of players join
- Automatically divide the court price by the current number of players
- Recalculate the split whenever another player joins
- Show how much each joined player still owes the person who booked the court
- Record reimbursements such as Zelle, Venmo, Cash, or Apple Cash
- Show how much the organizer still needs to receive
- Store everything in SQLite for easy local development

> The payment feature in this starter app is **payment tracking**. It records reimbursements but does not actually charge cards or move money.

## Example

Suppose Hari pays Forsyth County **$40** for the court.

- Hari only → Hari's share is $40 and nobody owes him anything.
- Sam joins → 2 people → $20 each → Sam owes Hari $20.
- John and Mike join → 4 people → $10 each → Sam, John, and Mike each owe Hari $10.
- Sam records a $10 Zelle payment → Sam is settled and Hari's amount still to receive drops by $10.

## Run on macOS

```bash
cd midway_court
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## Push into your existing GitHub repo

Copy these project files into your local `midway_court` repository, then:

```bash
git add .
git commit -m "Build court booking and split payment tracker"
git branch -M main
git push -u origin main
```

If your local folder is not connected to GitHub yet:

```bash
git init
git add .
git commit -m "Initial Midway court booking app"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/midway_court.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

## Main files

```text
midway_court/
├── app.py
├── requirements.txt
├── Dockerfile
├── README.md
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   └── styles.css
└── tests/
    └── test_app.py
```

## API

- `GET /api/bookings`
- `POST /api/bookings`
- `GET /api/bookings/{id}`
- `POST /api/bookings/{id}/join`
- `POST /api/bookings/{id}/payments`
- `DELETE /api/bookings/{id}`

## Good next upgrades

- User accounts/login
- A shareable "Join this court" link
- Online database such as PostgreSQL/Supabase
- Real Stripe payment checkout
- Automatic payment reminders
- Calendar view of all six courts
