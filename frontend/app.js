const form = document.getElementById("scan-form");
const input = document.getElementById("username-input");
const btn = document.getElementById("scan-btn");
const errorEl = document.getElementById("form-error");
const scanningPanel = document.getElementById("scanning-panel");
const ticker = document.getElementById("scan-ticker");
const summaryBar = document.getElementById("summary-bar");
const summaryUsernameText = document.getElementById("summary-username-text");
const countAvailable = document.getElementById("count-available");
const countTaken = document.getElementById("count-taken");
const countUnknown = document.getElementById("count-unknown");
const resultsEl = document.getElementById("results");
const platformCountEl = document.getElementById("platform-count");

const USERNAME_RE = /^[A-Za-z0-9_.\-]{1,39}$/;

let tickerInterval = null;
let platformNames = [];

// Warm up: fetch the platform list so the ticker + header count reflect reality.
fetch("/api/platforms")
  .then((r) => r.json())
  .then((data) => {
    platformNames = data.platforms.map((p) => p.name);
    platformCountEl.textContent = data.count;
  })
  .catch(() => {
    platformNames = ["GitHub", "Reddit", "npm", "PyPI", "Dribbble"];
  });

function startTicker() {
  let i = 0;
  scanningPanel.classList.remove("hidden");
  ticker.textContent = "initializing…";
  tickerInterval = setInterval(() => {
    const name = platformNames.length
      ? platformNames[i % platformNames.length]
      : "platform";
    ticker.textContent = `pinging ${name}…`;
    i++;
  }, 110);
}

function stopTicker() {
  clearInterval(tickerInterval);
  scanningPanel.classList.add("hidden");
}

function setError(message) {
  errorEl.textContent = message || "";
}

function statusLabel(status) {
  if (status === "available") return "Available";
  if (status === "taken") return "Taken";
  return "Unknown";
}

function renderResults(username, payload) {
  summaryUsernameText.textContent = username;
  countAvailable.textContent = payload.summary.available;
  countTaken.textContent = payload.summary.taken;
  countUnknown.textContent = payload.summary.unknown;
  summaryBar.classList.remove("hidden");

  resultsEl.innerHTML = "";

  const byCategory = new Map();
  for (const r of payload.results) {
    if (!byCategory.has(r.category)) byCategory.set(r.category, []);
    byCategory.get(r.category).push(r);
  }

  let cardIndex = 0;
  for (const [category, items] of byCategory) {
    const confirmed = items.filter((i) => i.status !== "unknown");
    const manual = items.filter((i) => i.status === "unknown");

    // Skip a category entirely only if it has nothing at all (shouldn't happen).
    if (confirmed.length === 0 && manual.length === 0) continue;

    const block = document.createElement("div");
    block.className = "category-block";

    const title = document.createElement("h2");
    title.className = "category-title";
    title.textContent = category;
    block.appendChild(title);

    if (confirmed.length > 0) {
      const grid = document.createElement("div");
      grid.className = "card-grid";
      for (const item of confirmed) {
        grid.appendChild(buildCard(item, cardIndex));
        cardIndex++;
      }
      block.appendChild(grid);
    }

    if (manual.length > 0) {
      block.appendChild(buildManualDetails(manual, confirmed.length === 0));
    }

    resultsEl.appendChild(block);
  }
}

function buildCard(item, cardIndex) {
  const card = document.createElement("a");
  card.className = "result-card";
  card.href = item.url;
  card.target = "_blank";
  card.rel = "noopener noreferrer";
  card.style.animationDelay = `${Math.min(cardIndex * 25, 500)}ms`;

  card.innerHTML = `
    <div class="card-top">
      <span class="card-name">${escapeHtml(item.name)}</span>
    </div>
    <span class="card-url">${escapeHtml(shortUrl(item.url))}</span>
    <span class="status-pill ${item.status}">
      <span class="status-dot"></span>${statusLabel(item.status)}
    </span>
    ${item.note ? `<span class="card-note">${escapeHtml(item.note)}</span>` : ""}
  `;
  return card;
}

function buildManualDetails(manualItems, openByDefault) {
  const details = document.createElement("details");
  details.className = "manual-check";
  if (openByDefault) details.open = true;

  const summary = document.createElement("summary");
  summary.innerHTML = `
    <span class="manual-check-dot"></span>
    ${manualItems.length} platform${manualItems.length === 1 ? "" : "s"} need a manual check
    <span class="manual-check-hint">(bot-protected or JS-only — we won't guess)</span>
  `;
  details.appendChild(summary);

  const list = document.createElement("div");
  list.className = "manual-check-list";
  for (const item of manualItems) {
    const row = document.createElement("a");
    row.className = "manual-check-row";
    row.href = item.url;
    row.target = "_blank";
    row.rel = "noopener noreferrer";
    row.innerHTML = `
      <span class="manual-check-name">${escapeHtml(item.name)}</span>
      <span class="manual-check-note">${escapeHtml(item.note || "check manually")}</span>
    `;
    list.appendChild(row);
  }
  details.appendChild(list);
  return details;
}

function shortUrl(url) {
  return url.replace(/^https?:\/\//, "");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  setError("");

  const username = input.value.trim();
  if (!username) {
    setError("Type a username first.");
    return;
  }
  if (!USERNAME_RE.test(username)) {
    setError("Use 1-39 characters: letters, numbers, underscore, dot, or hyphen.");
    return;
  }

  btn.disabled = true;
  summaryBar.classList.add("hidden");
  resultsEl.innerHTML = "";
  startTicker();

  try {
    const resp = await fetch(`/api/check/${encodeURIComponent(username)}`);
    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || "Something went wrong.");
    }

    stopTicker();
    renderResults(username, data);
  } catch (err) {
    stopTicker();
    setError(err.message || "Couldn't reach the scanner. Is the backend running?");
  } finally {
    btn.disabled = false;
  }
});
