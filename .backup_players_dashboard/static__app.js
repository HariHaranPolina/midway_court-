const $ = (sel, root = document) => root.querySelector(sel);

const money = (n) => `$${Number(n).toFixed(2)}`;

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function playerRow(p) {
  const role = p.is_organizer ? " <span class='badge'>Booked by · paid court</span>" : "";
  let balanceText;
  let balanceClass;
  if (p.is_organizer && p.balance < 0) {
    balanceText = `To receive: ${money(-p.balance)}`;
    balanceClass = "receive";
  } else if (p.balance > 0) {
    balanceText = `Owes: ${money(p.balance)}`;
    balanceClass = "due";
  } else {
    balanceText = "Settled";
    balanceClass = "paid";
  }

  const paymentText = p.is_organizer
    ? `Paid court: <strong>${money(p.paid)}</strong>`
    : `Payment done: <strong>${money(p.paid)}</strong>`;

  return `
    <div class="player-row">
      <div><strong>${escapeHtml(p.name)}</strong>${role}</div>
      <div>Share: <strong>${money(p.share)}</strong></div>
      <div>${paymentText}</div>
      <div class="${balanceClass}"><strong>${balanceText}</strong></div>
    </div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderBooking(booking) {
  const tpl = $("#booking-template");
  const card = tpl.content.firstElementChild.cloneNode(true);

  $(".court", card).textContent = booking.court_name;
  $(".when", card).textContent = `${booking.booking_date} · ${booking.start_time}–${booking.end_time}`;
  $(".organizer", card).textContent = `Booked by ${booking.organizer_name} · ${booking.participant_count}/${booking.max_players} players`;
  $(".cost", card).textContent = `Court cost ${money(booking.total_cost)}`;
  $(".remaining", card).textContent = `Still owed to ${booking.organizer_name}: ${money(booking.organizer_to_receive)}`;
  $(".split-line", card).textContent = `${booking.participant_count} people → ${money(booking.share_per_person)} each`;
  $(".players", card).innerHTML = booking.participants.map(playerRow).join("");

  const participantSelect = $(".pay-form select[name='participant_id']", card);
  const payers = booking.participants.filter((p) => !p.is_organizer);
  participantSelect.innerHTML = payers.length
    ? payers.map((p) => `<option value="${p.id}">${escapeHtml(p.name)} — owes ${money(p.balance)}</option>`).join("")
    : `<option value="">No joined players yet</option>`;
  $(".pay-form button", card).disabled = payers.length === 0;

  const msg = $(".card-msg", card);

  $(".join-form", card).addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const name = String(form.get("name") || "").trim();
    const amount = Number(form.get("amount") || 0);

    try {
      const joinedBooking = await api(`/api/bookings/${booking.id}/join`, {
        method: "POST",
        body: JSON.stringify({
          name: name,
          email: null
        }),
      });

      if (amount > 0) {
        const players = joinedBooking.participants
          .filter((p) => !p.is_organizer)
          .sort((a, b) => b.id - a.id);

        const newPlayer = players[0];

        if (newPlayer) {
          await api(`/api/bookings/${booking.id}/payments`, {
            method: "POST",
            body: JSON.stringify({
              participant_id: newPlayer.id,
              amount: amount,
              method: "Initial payment"
            }),
          });
        }
      }

      e.currentTarget.reset();
      await loadBookings();
    } catch (err) {
      msg.textContent = err.message;
      await loadBookings();
    }
  });

  $(".pay-form", card).addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    try {
      await api(`/api/bookings/${booking.id}/payments`, {
        method: "POST",
        body: JSON.stringify({
          participant_id: Number(form.get("participant_id")),
          amount: Number(form.get("amount")),
          method: form.get("method"),
        }),
      });
      e.currentTarget.querySelector("input[name='amount']").value = "";
      await loadBookings();
    } catch (err) {
      msg.textContent = err.message;
    }
  });

  return card;
}

async function loadBookings() {
  const container = $("#bookings");
  container.innerHTML = "<p>Loading…</p>";
  try {
    const bookings = await api("/api/bookings");
    container.innerHTML = "";
    if (!bookings.length) {
      container.innerHTML = "<p>No bookings yet. Create the first one above.</p>";
      return;
    }
    bookings.forEach((b) => container.appendChild(renderBooking(b)));
  } catch (err) {
    container.innerHTML = `<p class="message">${escapeHtml(err.message)}</p>`;
  }
}

$("#booking-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#booking-msg");
  msg.textContent = "";
  const payload = {
    court_name: $("#court_name").value,
    booking_date: $("#booking_date").value,
    start_time: $("#start_time").value,
    end_time: $("#end_time").value,
    organizer_name: $("#organizer_name").value,
    organizer_email: $("#organizer_email").value || null,
    total_cost: Number($("#total_cost").value),
    max_players: Number($("#max_players").value),
    notes: $("#notes").value || null,
  };
  try {
    await api("/api/bookings", { method: "POST", body: JSON.stringify(payload) });
    msg.textContent = "Booking created.";
    e.currentTarget.reset();
    $("#max_players").value = 6;
    await loadBookings();
  } catch (err) {
    msg.textContent = err.message;
  }
});

$("#refresh-btn").addEventListener("click", loadBookings);
loadBookings();
