const $ = (s) => document.querySelector(s);
const money = n => `$${Number(n).toFixed(2)}`;
async function api(url, options={}) {
  const r = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  if (!r.ok) { let m=`Request failed (${r.status})`; try {m=(await r.json()).detail||m;} catch(_){} throw new Error(m); }
  return r.json();
}
const bookingId = Number(location.pathname.split("/").pop());
let booking;
let allPlayers=[];

function row(p) {
  let status = p.is_organizer ? (p.balance < 0 ? `To receive ${money(-p.balance)}` : "Settled") : (p.balance > 0 ? `Owes ${money(p.balance)}` : "Settled");
  return `<article class="court-player-row">
    <div><strong>${p.name}</strong>${p.is_organizer ? '<span class="badge">Court holder</span>' : ''}</div>
    <div>Share <strong>${money(p.share)}</strong></div>
    <div>${p.is_organizer ? 'Paid court' : 'Paid'} <strong>${money(p.paid)}</strong></div>
    <div>Account <strong>${p.account_balance == null ? '—' : money(p.account_balance)}</strong></div>
    <div class="${p.balance > 0 ? 'due' : 'paid'}"><strong>${status}</strong></div>
  </article>`;
}

async function load() {
  booking = await api(`/api/bookings/${bookingId}`);
  allPlayers = await api("/api/players");
  $("#court-title").textContent = booking.court_name;
  $("#court-subtitle").textContent = `${booking.booking_date} · ${booking.start_time}–${booking.end_time} · Held by ${booking.organizer_name}`;
  $("#court-cost").textContent = money(booking.total_cost);
  $("#court-count").textContent = `${booking.participant_count}/${booking.max_players}`;
  $("#court-share").textContent = money(booking.share_per_person);
  $("#court-receive").textContent = money(booking.organizer_to_receive);
  $("#court-players").innerHTML = booking.participants.map(row).join("");

  const joinedIds = new Set(booking.participants.map(p => p.player_id));
  const available = allPlayers.filter(p => !joinedIds.has(p.id));
  $("#join_player").innerHTML = available.length ? available.map(p => `<option value="${p.id}">${p.name} · balance ${money(p.balance)}</option>`).join("") : '<option value="">No available players</option>';
  $("#join-form button").disabled = !available.length || booking.participant_count >= booking.max_players;

  const payers = booking.participants.filter(p => !p.is_organizer && p.balance > 0);
  $("#pay_player").innerHTML = payers.length ? payers.map(p => `<option value="${p.id}">${p.name} · owes ${money(p.balance)}</option>`).join("") : '<option value="">Everyone settled</option>';
  $("#payment-form button").disabled = !payers.length;
}

$("#join-form").addEventListener("submit", async e => {
  e.preventDefault(); const msg=$("#join-msg"); msg.textContent="";
  try {
    await api(`/api/bookings/${bookingId}/join`, {method:"POST", body:JSON.stringify({
      player_id: Number($("#join_player").value), initial_payment: Number($("#initial_payment").value || 0)
    })});
    $("#initial_payment").value = 0; await load();
  } catch(e) { msg.textContent=e.message; }
});

$("#payment-form").addEventListener("submit", async e => {
  e.preventDefault(); const msg=$("#pay-msg"); msg.textContent="";
  try {
    await api(`/api/bookings/${bookingId}/payments`, {method:"POST", body:JSON.stringify({
      participant_id:Number($("#pay_player").value), amount:Number($("#pay_amount").value), method:$("#pay_method").value
    })});
    $("#pay_amount").value=""; await load();
  } catch(e) { msg.textContent=e.message; }
});
load().catch(e => { document.body.innerHTML += `<p class="message">${e.message}</p>`; });