const $ = (sel, root = document) => root.querySelector(sel);
const money = (n) => `$${Number(n).toFixed(2)}`;

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(v) {
  return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function playerCard(p) {
  const courts = p.held_courts.length
    ? p.held_courts.map(c => `<a class="court-link" href="/court/${c.id}">View ${escapeHtml(c.court_name)} · ${c.booking_date} ${c.start_time}</a>`).join("")
    : `<span class="muted">No court currently held</span>`;

  return `<article class="player-card">
    <div class="player-card-top">
      <div><h3>${escapeHtml(p.name)}</h3><span class="muted">Player balance</span></div>
      <strong class="big-balance ${p.balance < 0 ? 'negative' : ''}">${money(p.balance)}</strong>
    </div>
    <div class="held-courts">${courts}</div>
    <div class="player-actions">
      <a class="button-link" href="/new-court?holder_id=${p.id}">Book / Hold court</a>
      <form class="fund-form" data-player-id="${p.id}">
        <input name="amount" type="number" step="0.01" min="0.01" placeholder="Add money" required />
        <button type="submit" class="secondary">Add money</button>
      </form>
    </div>
  </article>`;
}

async function loadPlayers() {
  const box = $("#players");
  box.innerHTML = "<p>Loading…</p>";
  try {
    const players = await api("/api/players");
    box.innerHTML = players.length ? players.map(playerCard).join("") : "<p>No players yet. Add the first player above.</p>";
    document.querySelectorAll(".fund-form").forEach(form => {
      form.addEventListener("submit", async e => {
        e.preventDefault();
        const id = Number(form.dataset.playerId);
        const amount = Number(new FormData(form).get("amount"));
        try {
          await api(`/api/players/${id}/funds`, { method: "POST", body: JSON.stringify({ amount }) });
          await loadPlayers();
        } catch (err) { alert(err.message); }
      });
    });
  } catch (err) { box.innerHTML = `<p class="message">${escapeHtml(err.message)}</p>`; }
}

$("#player-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#player-msg");
  msg.textContent = "";
  try {
    await api("/api/players", { method: "POST", body: JSON.stringify({
      name: $("#player_name").value,
      starting_balance: Number($("#starting_balance").value || 0),
    }) });
    e.currentTarget.reset();
    $("#starting_balance").value = 10;
    await loadPlayers();
  } catch (err) { msg.textContent = err.message; }
});

$("#refresh-btn").addEventListener("click", loadPlayers);
loadPlayers();