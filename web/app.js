"use strict";

// Frontend for channel-tuner. Reads the read-only API and draws two charts.
// No SQLite access here: the JSON from /api/* is the contract with the backend.

const NON_OVERLAPPING_CHANNELS = [1, 6, 11];

let occupancyChart = null;
let timelineChart = null;

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${url} (${response.status})`);
  }
  return response.json();
}

function channelColor(channel) {
  // Highlight the non-overlapping channels so the "good" ones stand out.
  return NON_OVERLAPPING_CHANNELS.includes(channel) ? "#1d9e75" : "#6b7280";
}

async function loadSummary() {
  const summary = await fetchJson("/api/summary");
  document.getElementById("stat-scans").textContent = summary.scans;
  document.getElementById("stat-observations").textContent = summary.observations;
  document.getElementById("stat-networks").textContent = summary.unique_networks;
}

async function loadLocations() {
  const locations = await fetchJson("/api/locations");
  const select = document.getElementById("location-select");
  select.innerHTML = "";
  const options = locations.length > 0 ? locations : ["default"];
  for (const location of options) {
    const option = document.createElement("option");
    option.value = location;
    option.textContent = location;
    select.appendChild(option);
  }
  return select.value;
}

function withCandidateChannels(rows) {
  // Ensure the non-overlapping candidates always appear, even with zero APs,
  // so an empty (ideal) channel is visible instead of missing from the chart.
  const byChannel = new Map(rows.map((row) => [row.channel, row]));
  for (const channel of NON_OVERLAPPING_CHANNELS) {
    if (!byChannel.has(channel)) {
      byChannel.set(channel, { channel, band: "2.4GHz", ap_count: 0, avg_rssi: null });
    }
  }
  return [...byChannel.values()].sort((a, b) => a.channel - b.channel);
}

async function renderScore(location) {
  const data = await fetchJson(
    `/api/channel-score?location=${encodeURIComponent(location)}`
  );
  const cards = data.candidates
    .map((candidate) => {
      const value =
        candidate.interference_dbm === null
          ? "clear"
          : `${candidate.interference_dbm} dBm`;
      const isBest = candidate.channel === data.recommended ? " best" : "";
      return `<div class="candidate${isBest}">
        <span class="candidate-ch">Ch ${candidate.channel}</span>
        <span class="candidate-val">${value}</span>
        <small>${candidate.ap_count} APs</small>
      </div>`;
    })
    .join("");
  document.getElementById("recommendation").innerHTML = `
    <div class="rec-headline">
      Recommended 2.4&nbsp;GHz channel: <strong>${data.recommended}</strong>
    </div>
    <div class="candidates">${cards}</div>
    <p class="rec-note">Lower interference is better; "clear" means no detected networks.</p>`;
}

async function renderOccupancy(location) {
  const data = await fetchJson(
    `/api/channel-occupancy?location=${encodeURIComponent(location)}`
  );
  const channels = withCandidateChannels(data.channels);
  const labels = channels.map((row) => row.channel);
  const counts = channels.map((row) => row.ap_count);
  const colors = channels.map((row) => channelColor(row.channel));

  if (occupancyChart) {
    occupancyChart.destroy();
  }
  occupancyChart = new Chart(document.getElementById("occupancy-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Access points", data: counts, backgroundColor: colors }],
    },
    options: {
      scales: {
        x: { title: { display: true, text: "Channel" } },
        y: { beginAtZero: true, title: { display: true, text: "Access points" } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

async function renderTimeline(location) {
  const data = await fetchJson(
    `/api/timeline?location=${encodeURIComponent(location)}`
  );
  const labels = data.points.map((row) => row.timestamp);
  const counts = data.points.map((row) => row.ap_count);

  if (timelineChart) {
    timelineChart.destroy();
  }
  timelineChart = new Chart(document.getElementById("timeline-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Access points",
          data: counts,
          borderColor: "#1d9e75",
          tension: 0.25,
        },
      ],
    },
    options: {
      scales: { y: { beginAtZero: true } },
      plugins: { legend: { display: false } },
    },
  });
}

async function refresh(location) {
  await Promise.all([
    renderScore(location),
    renderOccupancy(location),
    renderTimeline(location),
  ]);
}

async function main() {
  try {
    await loadSummary();
    const location = await loadLocations();
    await refresh(location);

    document
      .getElementById("location-select")
      .addEventListener("change", (event) => refresh(event.target.value));
  } catch (error) {
    console.error(error);
  }
}

main();
