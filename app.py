from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "midway_court.db"

app = FastAPI(title="Midway Court Split", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
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


@app.on_event("startup")
def startup() -> None:
    init_db()


class BookingCreate(BaseModel):
    court_name: str = Field(min_length=1)
    booking_date: str
    start_time: str
    end_time: str
    organizer_name: str = Field(min_length=1)
    organizer_email: Optional[str] = None
    total_cost: float = Field(ge=0)
    max_players: int = Field(default=6, ge=1, le=20)
    notes: Optional[str] = None


class JoinCreate(BaseModel):
    name: str = Field(min_length=1)
    email: Optional[str] = None


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
        ),
        2,
    )

    participants = []
    for person in people:
        reimbursements_paid = round(
            float(
                conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE participant_id = ?",
                    (person["id"],),
                ).fetchone()["total"]
            ),
            2,
        )

        if person["is_organizer"]:
            # The organizer paid the full court fee up front. Money received from
            # other players reduces the organizer's net contribution.
            net_contribution = round(float(booking["total_cost"]) - reimbursements_received, 2)
            balance = round(share - net_contribution, 2)
            paid_display = round(float(booking["total_cost"]), 2)
        else:
            net_contribution = reimbursements_paid
            balance = round(max(share - net_contribution, 0), 2)
            paid_display = reimbursements_paid

        participants.append(
            {
                "id": person["id"],
                "name": person["name"],
                "email": person["email"],
                "is_organizer": bool(person["is_organizer"]),
                "share": share,
                "paid": paid_display,
                "net_contribution": net_contribution,
                "balance": balance,
            }
        )

    outstanding_reimbursements = round(
        sum(p["balance"] for p in participants if not p["is_organizer"] and p["balance"] > 0),
        2,
    )
    organizer_to_receive = round(
        max(-next((p["balance"] for p in participants if p["is_organizer"]), 0), 0),
        2,
    )

    return {
        "id": booking["id"],
        "court_name": booking["court_name"],
        "booking_date": booking["booking_date"],
        "start_time": booking["start_time"],
        "end_time": booking["end_time"],
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


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "templates" / "index.html").read_text())


@app.get("/api/bookings")
def list_bookings() -> list[dict]:
    with get_conn() as conn:
        ids = conn.execute(
            "SELECT id FROM bookings ORDER BY booking_date ASC, start_time ASC, id DESC"
        ).fetchall()
        return [_booking_summary(conn, row["id"]) for row in ids]


@app.get("/api/bookings/{booking_id}")
def get_booking(booking_id: int) -> dict:
    with get_conn() as conn:
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingCreate) -> dict:
    _validate_datetime_fields(payload.booking_date, payload.start_time, payload.end_time)

    with get_conn() as conn:
        overlap = conn.execute(
            """
            SELECT id FROM bookings
            WHERE court_name = ? AND booking_date = ?
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
             organizer_email, total_cost, max_players, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.court_name,
                payload.booking_date,
                payload.start_time,
                payload.end_time,
                payload.organizer_name,
                payload.organizer_email,
                payload.total_cost,
                payload.max_players,
                payload.notes,
            ),
        )
        booking_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO participants (booking_id, name, email, is_organizer)
            VALUES (?, ?, ?, 1)
            """,
            (booking_id, payload.organizer_name, payload.organizer_email),
        )
        conn.commit()
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings/{booking_id}/join", status_code=201)
def join_booking(booking_id: int, payload: JoinCreate) -> dict:
    with get_conn() as conn:
        booking = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        current = conn.execute(
            "SELECT COUNT(*) AS c FROM participants WHERE booking_id = ?", (booking_id,)
        ).fetchone()["c"]
        if current >= booking["max_players"]:
            raise HTTPException(status_code=409, detail="This booking is full")

        if payload.email:
            duplicate = conn.execute(
                "SELECT id FROM participants WHERE booking_id = ? AND lower(email) = lower(?)",
                (booking_id, payload.email),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="This email already joined the booking")

        conn.execute(
            "INSERT INTO participants (booking_id, name, email) VALUES (?, ?, ?)",
            (booking_id, payload.name, payload.email),
        )
        conn.commit()
        return _booking_summary(conn, booking_id)


@app.post("/api/bookings/{booking_id}/payments", status_code=201)
def add_payment(booking_id: int, payload: PaymentCreate) -> dict:
    with get_conn() as conn:
        participant = conn.execute(
            "SELECT * FROM participants WHERE id = ? AND booking_id = ?",
            (payload.participant_id, booking_id),
        ).fetchone()
        if not participant:
            raise HTTPException(status_code=404, detail="Participant not found for this booking")
        if participant["is_organizer"]:
            raise HTTPException(status_code=400, detail="Organizer already paid the full court fee")

        summary = _booking_summary(conn, booking_id)
        person_summary = next(p for p in summary["participants"] if p["id"] == payload.participant_id)
        if payload.amount > person_summary["balance"] + 0.001:
            raise HTTPException(
                status_code=400,
                detail=f"Payment is more than the remaining balance (${person_summary['balance']:.2f})",
            )

        conn.execute(
            """
            INSERT INTO payments (booking_id, participant_id, amount, method, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (booking_id, payload.participant_id, payload.amount, payload.method, payload.note),
        )
        conn.commit()
        return _booking_summary(conn, booking_id)


@app.delete("/api/bookings/{booking_id}", status_code=204)
def delete_booking(booking_id: int):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Booking not found")
    return None
