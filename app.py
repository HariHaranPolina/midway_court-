from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "midway_court.db"

app = FastAPI(title="Midway Court Split", version="2.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT,
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                court_name TEXT NOT NULL,
                booking_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                organizer_name TEXT NOT NULL,
                organizer_email TEXT,
                total_cost REAL NOT NULL CHECK(total_cost >= 0),
                max_players INTEGER NOT NULL DEFAULT 6 CHECK(max_players >= 1),
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT,
                is_organizer INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER NOT NULL,
                participant_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                method TEXT NOT NULL DEFAULT 'manual',
                note TEXT,
                paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
                FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
            );
            """
        )

        if not _column_exists(conn, "bookings", "holder_player_id"):
            conn.execute("ALTER TABLE bookings ADD COLUMN holder_player_id INTEGER")
        if not _column_exists(conn, "participants", "player_id"):
            conn.execute("ALTER TABLE participants ADD COLUMN player_id INTEGER")

        # Link older bookings/participants to roster players when possible.
        old_people = conn.execute(
            "SELECT DISTINCT organizer_name, organizer_email FROM bookings WHERE organizer_name IS NOT NULL"
        ).fetchall()
        for row in old_people:
            existing = conn.execute(
                "SELECT id FROM players WHERE lower(name)=lower(?)", (row["organizer_name"],)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT OR IGNORE INTO players(name, email, balance) VALUES (?, ?, 0)",
                    (row["organizer_name"], row["organizer_email"]),
                )

        conn.execute(
            """
            UPDATE bookings
            SET holder_player_id = (
                SELECT p.id FROM players p WHERE lower(p.name)=lower(bookings.organizer_name) LIMIT 1
            )
            WHERE holder_player_id IS NULL
            """
        )
        conn.execute(
            """
            UPDATE participants
            SET player_id = (
                SELECT p.id FROM players p WHERE lower(p.name)=lower(participants.name) LIMIT 1
            )
            WHERE player_id IS NULL
            """
        )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()


class PlayerCreate(BaseModel):
    name: str = Field(min_length=1)
    email: Optional[str] = None
    starting_balance: float = 0


class FundsCreate(BaseModel):
    amount: float = Field(gt=0)


class BookingCreate(BaseModel):
    court_name: str = Field(min_length=1)
    booking_date: str
    start_time: str
    end_time: str
    holder_player_id: Optional[int] = None
    organizer_name: Optional[str] = None
    organizer_email: Optional[str] = None
    total_cost: float = Field(ge=0)
    max_players: int = Field(default=6, ge=1, le=20)
    notes: Optional[str] = None


class JoinCreate(BaseModel):
    player_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None
    initial_payment: float = Field(default=0, ge=0)


class PaymentCreate(BaseModel):
    participant_id: int
    amount: float = Field(gt=0)
    method: str = "manual"
    note: Optional[str] = None


def _validate_datetime_fields(booking_date: str, start_time: str, end_time: str) -> None:
    try:
        start = datetime.fromisoformat(f"{booking_date}T{start_time}")
        end = datetime.fromisoformat(f"{booking_date}T{end_time}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Use date YYYY-MM-DD and time HH:MM") from exc
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be after start time")


def _get_or_create_player(conn: sqlite3.Connection, name: str, email: Optional[str] = None) -> sqlite3.Row:
    player = conn.execute("SELECT * FROM players WHERE lower(name)=lower(?)", (name,)).fetchone()
    if player:
        return player
    cur = conn.execute(
        "INSERT INTO players(name, email, balance) VALUES (?, ?, 0)", (name, email)
    )
    return conn.execute("SELECT * FROM players WHERE id=?", (cur.lastrowid,)).fetchone()


def _booking_summary(conn: sqlite3.Connection, booking_id: int) -> dict:
    booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    people = conn.execute(
        "SELECT * FROM participants WHERE booking_id = ? ORDER BY is_organizer DESC, id ASC",
        (booking_id,),
    ).fetchall()
    count = len(people)
    share = round(float(booking["total_cost"]) / count, 2) if count else 0.0

    reimbursements_received = round(
        float(
            conn.execute(
                """
                SELECT COALESCE(SUM(p.amount), 0) AS total
                FROM payments p
                JOIN participants pr ON pr.id = p.participant_id
                WHERE p.booking_id = ? AND pr.is_organizer = 0
                """,
                (booking_id,),
            ).fetchone()["total"]
        ), 2,
    )

    participants = []
    for person in people:
        paid_by_person = round(
            float(conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE participant_id = ?",
                (person["id"],),
            ).fetchone()["total"]), 2,
        )
        if person["is_organizer"]:
            net_contribution = round(float(booking["total_cost"]) - reimbursements_received, 2)
            balance = round(share - net_contribution, 2)
            paid_display = round(float(booking["total_cost"]), 2)
        else:
            net_contribution = paid_by_person
            balance = round(max(share - net_contribution, 0), 2)
            paid_display = paid_by_person

        account_balance = None
        if person["player_id"]:
            prow = conn.execute("SELECT balance FROM players WHERE id=?", (person["player_id"],)).fetchone()
            if prow:
                account_balance = round(float(prow["balance"]), 2)

        participants.append({
            "id": person["id"],
            "player_id": person["player_id"],
            "name": person["name"],
            "email": person["email"],
            "is_organizer": bool(person["is_organizer"]),
            "share": share,
            "paid": paid_display,
            "net_contribution": net_contribution,
            "balance": balance,
            "account_balance": account_balance,
        })

    outstanding_reimbursements = round(
        sum(p["balance"] for p in participants if not p["is_organizer"] and p["balance"] > 0), 2,
    )
    organizer_to_receive = round(
        max(-next((p["balance"] for p in participants if p["is_organizer"]), 0), 0), 2,
    )

    return {
        "id": booking["id"],
        "court_name": booking["court_name"],
        "booking_date": booking["booking_date"],
        "start_time": booking["start_time"],
        "end_time": booking["end_time"],
        "holder_player_id": booking["holder_player_id"],
        "organizer_name": booking["organizer_name"],
        "organizer_email": booking["organizer_email"],
        "total_cost": round(float(booking["total_cost"]), 2),
        "max_players": booking["max_players"],
        "notes": booking["notes"],
        "participant_count": count,
        "share_per_person": share,
        "reimbursements_received": reimbursements_received,
        "remaining_total": outstanding_reimbursements,
        "organizer_to_receive": organizer_to_receive,
        "participants": participants,
    }


def _transfer_payment(conn: sqlite3.Connection, booking_id: int, participant_id: int, amount: float, method: str, note: Optional[str]) -> None:
    booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    participant = conn.execute(
        "SELECT * FROM participants WHERE id=? AND booking_id=?", (participant_id, booking_id)
    ).fetchone()
    if not booking or not participant:
        raise HTTPException(status_code=404, detail="Booking or participant not found")
    if participant["is_organizer"]:
        raise HTTPException(status_code=400, detail="Organizer does not reimburse themselves")

    summary = _booking_summary(conn, booking_id)
    person_summary = next(p for p in summary["participants"] if p["id"] == participant_id)
    if amount > person_summary["balance"] + 0.001:
        raise HTTPException(status_code=400, detail=f"Payment is more than amount owed (${person_summary['balance']:.2f})")

    conn.execute(
        "INSERT INTO payments(booking_id, participant_id, amount, method, note) VALUES (?, ?, ?, ?, ?)",
        (booking_id, participant_id, amount, method, note),
    )
    if participant["player_id"]:
        conn.execute("UPDATE players SET balance = balance - ? WHERE id=?", (amount, participant["player_id"]))
    if booking["holder_player_id"]:
        conn.execute("UPDATE players SET balance = balance + ? WHERE id=?", (amount, booking["holder_player_id"]))


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "templates" / "index.html").read_text())


@app.get("/new-court", response_class=HTMLResponse)
def new_court_page(holder_id: int = Query(..., ge=1)) -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "templates" / "new_court.html").read_text())


@app.get("/court/{booking_id}", response_class=HTMLResponse)
def court_page(booking_id: int) -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "templates" / "court.html").read_text())


@app.get("/api/players")
def list_players() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM players ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for p in rows:
            held = conn.execute(
                "SELECT id, court_name, booking_date, start_time, end_time FROM bookings WHERE holder_player_id=? ORDER BY booking_date DESC, start_time DESC",
                (p["id"],),
            ).fetchall()
            result.append({
                "id": p["id"],
                "name": p["name"],
                "email": p["email"],
                "balance": round(float(p["balance"]), 2),
                "held_courts": [dict(r) for r in held],
            })
        return result


@app.get("/api/players/{player_id}")
def get_player(player_id: int) -> dict:
    with get_conn() as conn:
        p = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        if not p:
            raise HTTPException(status_code=404, detail="Player not found")
        return {"id": p["id"], "name": p["name"], "email": p["email"], "balance": round(float(p["balance"]), 2)}


@app.post("/api/players", status_code=201)
def create_player(payload: PlayerCreate) -> dict:
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO players(name, email, balance) VALUES (?, ?, ?)",
                (payload.name.strip(), payload.email, payload.starting_balance),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Player already exists")
        p = conn.execute("SELECT * FROM players WHERE id=?", (cur.lastrowid,)).fetchone()
        return {"id": p["id"], "name": p["name"], "email": p["email"], "balance": round(float(p["balance"]), 2)}


@app.post("/api/players/{player_id}/funds")
def add_player_funds(player_id: int, payload: FundsCreate) -> dict:
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM players WHERE id=?", (player_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Player not found")
        conn.execute("UPDATE players SET balance = balance + ? WHERE id=?", (payload.amount, player_id))
        conn.commit()
        p = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        return {"id": p["id"], "name": p["name"], "balance": round(float(p["balance"]), 2)}


@app.get("/api/bookings")
def list_bookings() -> list[dict]:
    with get_conn() as conn:
        ids = conn.execute("SELECT id FROM bookings ORDER BY booking_date ASC, start_time ASC, id DESC").fetchall()
        return [_booking_summary(conn, row["id"]) for row in ids]


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: int) -> dict:
    with get_conn() as conn:
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingCreate) -> dict:
    _validate_datetime_fields(payload.booking_date, payload.start_time, payload.end_time)
    with get_conn() as conn:
        holder = None
        if payload.holder_player_id:
            holder = conn.execute("SELECT * FROM players WHERE id=?", (payload.holder_player_id,)).fetchone()
            if not holder:
                raise HTTPException(status_code=404, detail="Court holder not found")
        elif payload.organizer_name:
            holder = _get_or_create_player(conn, payload.organizer_name.strip(), payload.organizer_email)
        else:
            raise HTTPException(status_code=400, detail="Choose a court holder")

        overlap = conn.execute(
            """
            SELECT id FROM bookings
            WHERE court_name=? AND booking_date=?
              AND NOT (end_time <= ? OR start_time >= ?)
            LIMIT 1
            """,
            (payload.court_name, payload.booking_date, payload.start_time, payload.end_time),
        ).fetchone()
        if overlap:
            raise HTTPException(status_code=409, detail="That court is already booked during this time")

        cur = conn.execute(
            """
            INSERT INTO bookings
            (court_name, booking_date, start_time, end_time, organizer_name,
             organizer_email, total_cost, max_players, notes, holder_player_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.court_name, payload.booking_date, payload.start_time, payload.end_time,
                holder["name"], holder["email"], payload.total_cost, payload.max_players,
                payload.notes, holder["id"],
            ),
        )
        booking_id = cur.lastrowid
        conn.execute(
            "INSERT INTO participants(booking_id, name, email, is_organizer, player_id) VALUES (?, ?, ?, 1, ?)",
            (booking_id, holder["name"], holder["email"], holder["id"]),
        )
        # Court holder pays the full court fee up front.
        conn.execute("UPDATE players SET balance = balance - ? WHERE id=?", (payload.total_cost, holder["id"]))
        conn.commit()
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings/{booking_id}/join", status_code=201)
def join_booking(booking_id: int, payload: JoinCreate) -> dict:
    with get_conn() as conn:
        booking = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        current = conn.execute("SELECT COUNT(*) AS c FROM participants WHERE booking_id=?", (booking_id,)).fetchone()["c"]
        if current >= booking["max_players"]:
            raise HTTPException(status_code=409, detail="This booking is full")

        if payload.player_id:
            player = conn.execute("SELECT * FROM players WHERE id=?", (payload.player_id,)).fetchone()
            if not player:
                raise HTTPException(status_code=404, detail="Player not found")
        elif payload.name:
            player = _get_or_create_player(conn, payload.name.strip(), payload.email)
        else:
            raise HTTPException(status_code=400, detail="Choose a player")

        duplicate = conn.execute(
            "SELECT id FROM participants WHERE booking_id=? AND player_id=?", (booking_id, player["id"])
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Player already joined this court")

        cur = conn.execute(
            "INSERT INTO participants(booking_id, name, email, is_organizer, player_id) VALUES (?, ?, ?, 0, ?)",
            (booking_id, player["name"], player["email"], player["id"]),
        )
        participant_id = cur.lastrowid
        conn.commit()

        if payload.initial_payment > 0:
            _transfer_payment(conn, booking_id, participant_id, payload.initial_payment, "Initial payment", "Paid when joining")
            conn.commit()
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings/{booking_id}/payments", status_code=201)
def record_payment(booking_id: int, payload: PaymentCreate) -> dict:
    with get_conn() as conn:
        _transfer_payment(conn, booking_id, payload.participant_id, payload.amount, payload.method, payload.note)
        conn.commit()
        return _booking_summary(conn, booking_id)
