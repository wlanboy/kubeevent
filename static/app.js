// --- Tabs ---
document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", e => {
        e.preventDefault();
        const target = tab.dataset.tab;

        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");

        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        document.getElementById("tab-" + target).classList.add("active");
    });
});

// --- Stream ---
const streamBody = document.getElementById("streamBody");
const streamFilter = document.getElementById("streamFilter");
let latestEvents = [];

const evtSource = new EventSource('/events/stream');
evtSource.onmessage = e => {
    latestEvents = JSON.parse(e.data);
    renderStream();
};

function severityClass(type) {
    if (type === "Warning") return "sev-Warning";
    if (type === "Error") return "sev-Error";
    return "sev-Normal";
}

function renderStream() {
    const filter = streamFilter.value.toLowerCase();
    streamBody.innerHTML = "";

    latestEvents
        .filter(ev =>
            !filter ||
            (ev.reason && ev.reason.toLowerCase().includes(filter)) ||
            (ev.message && ev.message.toLowerCase().includes(filter)) ||
            (ev.involved_name && ev.involved_name.toLowerCase().includes(filter))
        )
        .forEach(ev => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${ev.created_at}</td>
                <td class="${severityClass(ev.type)}">${ev.type || ""}</td>
                <td>${ev.reason || ""}</td>
                <td>${ev.message || ""}</td>
                <td>${ev.namespace}/${ev.involved_name}</td>
            `;
            streamBody.appendChild(tr);
        });

    updateStats();
}

streamFilter.addEventListener("input", renderStream);

// --- Suche ---
const searchResults = document.getElementById("searchResults");
const searchBtn = document.getElementById("searchBtn");
const searchInput = document.getElementById("searchInput");

async function doSearch() {
    const q = searchInput.value;
    const res = await fetch('/events/search?q=' + encodeURIComponent(q));
    const data = await res.json();

    searchResults.innerHTML = "";
    data.forEach(ev => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${ev.created_at}</td>
            <td class="${severityClass(ev.type)}">${ev.type || ""}</td>
            <td>${ev.reason || ""}</td>
            <td>${ev.message || ""}</td>
            <td>${ev.namespace}/${ev.involved_name}</td>
        `;
        searchResults.appendChild(tr);
    });
}

searchBtn.onclick = doSearch;
searchInput.onkeydown = e => { if (e.key === "Enter") doSearch(); };

// --- Stats ---
const statsList = document.getElementById("statsList");

function updateStats() {
    const total = latestEvents.length;
    const warnings = latestEvents.filter(e => e.type === "Warning").length;
    const errors = latestEvents.filter(e => e.type === "Error").length;
    const normals = latestEvents.filter(e => e.type === "Normal").length;

    statsList.innerHTML = `
        <li><strong>Total:</strong> ${total}</li>
        <li class="sev-Normal"><strong>Normal:</strong> ${normals}</li>
        <li class="sev-Warning"><strong>Warning:</strong> ${warnings}</li>
        <li class="sev-Error"><strong>Error:</strong> ${errors}</li>
    `;
}
