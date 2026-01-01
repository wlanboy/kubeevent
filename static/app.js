const PAGE_SIZE = 20;
let currentPage = 1;
let searchPage = 1;
const SEARCH_PAGE_SIZE = 20;

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

let evtSource = null;
let currentLimit = 100;

function connectStream() {
    if (evtSource) evtSource.close();

    evtSource = new EventSource(`/events/stream?limit=${currentLimit}`);

    evtSource.onmessage = e => {
        latestEvents = JSON.parse(e.data);
        renderStream();
    };
}

// Initial verbinden
connectStream();

// Dropdown-Handler
document.getElementById("limitSelect").addEventListener("change", e => {
    currentLimit = parseInt(e.target.value);
    connectStream();
});

function severityClass(type) {
    if (type === "Warning") return "sev-Warning";
    if (type === "Error") return "sev-Error";
    return "sev-Normal";
}

function renderStream() {
    const filter = streamFilter.value.toLowerCase();

    const filtered = latestEvents.filter(ev => {
        const f = filter;

        return !f ||
            (ev.type && ev.type.toLowerCase().includes(f)) ||
            (ev.reason && ev.reason.toLowerCase().includes(f)) ||
            (ev.message && ev.message.toLowerCase().includes(f)) ||
            (ev.involved_name && ev.involved_name.toLowerCase().includes(f)) ||
            (ev.involved_kind && ev.involved_kind.toLowerCase().includes(f)) ||
            (ev.namespace && ev.namespace.toLowerCase().includes(f));
    });

    const pageData = paginate(filtered);

    streamBody.innerHTML = "";
    pageData.forEach(ev => {
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

    renderPagination(
        document.getElementById("streamPagination"),
        filtered.length,
        renderStream
    );

    updateStats();
}

streamFilter.addEventListener("input", renderStream);

// --- Suche ---
const searchResults = document.getElementById("searchResults");
const searchBtn = document.getElementById("searchBtn");
const searchInput = document.getElementById("searchInput");

async function doSearch(page = 1) {
    searchPage = page;

    const q = searchInput.value || "";
    const url = `/events/search?q=${encodeURIComponent(q)}&page=${page}&page_size=${SEARCH_PAGE_SIZE}`;

    const res = await fetch(url);

    if (!res.ok) {
        console.error("Search failed:", res.status, await res.text());
        return;
    }

    const data = await res.json();
    const items = data.items || [];
    const totalPages = data.pages || 1;

    searchResults.innerHTML = "";
    items.forEach(ev => {
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

    renderSearchPagination(totalPages);
}

searchBtn.onclick = doSearch(1);
searchInput.onkeydown = e => { if (e.key === "Enter") doSearch(1); };

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

function sortTable(tableBody, columnIndex, ascending) {
    const rows = Array.from(tableBody.querySelectorAll("tr"));

    rows.sort((a, b) => {
        const A = a.children[columnIndex].innerText.toLowerCase();
        const B = b.children[columnIndex].innerText.toLowerCase();

        if (!isNaN(Date.parse(A)) && !isNaN(Date.parse(B))) {
            return ascending ? new Date(A) - new Date(B) : new Date(B) - new Date(A);
        }

        return ascending ? A.localeCompare(B) : B.localeCompare(A);
    });

    rows.forEach(r => tableBody.appendChild(r));
}

document.querySelectorAll("th").forEach((th, index) => {
    let asc = true;
    th.style.cursor = "pointer";

    th.addEventListener("click", () => {
        const tableBody = th.closest("table").querySelector("tbody");
        sortTable(tableBody, index, asc);
        asc = !asc;
    });
});

function paginate(data) {
    const start = (currentPage - 1) * PAGE_SIZE;
    return data.slice(start, start + PAGE_SIZE);
}

function renderPagination(container, totalItems, onPageChange) {
    const totalPages = Math.ceil(totalItems / PAGE_SIZE);
    container.innerHTML = "";

    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#";
        a.innerText = i;
        if (i === currentPage) a.setAttribute("aria-current", "page");

        a.addEventListener("click", e => {
            e.preventDefault();
            currentPage = i;
            onPageChange();
        });

        li.appendChild(a);
        container.appendChild(li);
    }
}

function renderSearchPagination(totalPages) {
    const container = document.getElementById("searchPagination");
    container.innerHTML = "";

    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement("li");
        const a = document.createElement("a");

        a.href = "#";
        a.innerText = i;

        if (i === searchPage) {
            a.setAttribute("aria-current", "page");
        }

        a.addEventListener("click", e => {
            e.preventDefault();
            doSearch(i);
        });

        li.appendChild(a);
        container.appendChild(li);
    }
}
