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

async function renderOccupancy(location) {
  const data = await fetchJson(
    `/api/channel-occupancy?location=${encodeURIComponent(location)}`
  );
  const labels = data.channels.map((row) => row.channel);
  const counts = data.channels.map((row) => row.ap_count);
  const colors = data.channels.map((row) => channelColor(row.channel));

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
  await Promise.all([renderOccupancy(location), renderTimeline(location)]);
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
