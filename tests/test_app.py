from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

import app as app_module


def test_booking_join_and_payment_flow():
    with tempfile.TemporaryDirectory() as td:
        app_module.DB_PATH = Path(td) / "test.db"
        app_module.init_db()
        client = TestClient(app_module.app)

        created = client.post(
            "/api/bookings",
            json={
                "court_name": "Pickleball Court 1",
                "booking_date": "2026-08-20",
                "start_time": "20:00",
                "end_time": "22:00",
                "organizer_name": "Hari",
                "total_cost": 40,
                "max_players": 5,
            },
        )
        assert created.status_code == 201
        booking = created.json()
        assert booking["share_per_person"] == 40.0
        assert booking["organizer_to_receive"] == 0.0

        joined = client.post(
            f"/api/bookings/{booking['id']}/join", json={"name": "Sam"}
        )
        assert joined.status_code == 201
        booking = joined.json()
        assert booking["share_per_person"] == 20.0
        assert booking["organizer_to_receive"] == 20.0

        sam = next(p for p in booking["participants"] if p["name"] == "Sam")
        assert sam["balance"] == 20.0

        paid = client.post(
            f"/api/bookings/{booking['id']}/payments",
            json={"participant_id": sam["id"], "amount": 20, "method": "Zelle"},
        )
        assert paid.status_code == 201
        booking = paid.json()
        sam = next(p for p in booking["participants"] if p["name"] == "Sam")
        assert sam["balance"] == 0.0
        assert booking["organizer_to_receive"] == 0.0
        assert booking["remaining_total"] == 0.0
