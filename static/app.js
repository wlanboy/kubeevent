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

        if (target === "stats") {
            updateStats();
        }
    });
});

// --- Hilfsfunktion: Event-Zeile generieren (Shared für Stream & Suche) ---
function createEventRowHtml(ev, isSearch = false) {
    const date = isSearch ? new Date(ev.created_at).toLocaleString() : new Date(ev.created_at).toLocaleTimeString();

    let statusColor = "var(--pico-primary)"; 
    let badgeColor = "#1e88e5"; 

    if (ev.type === 'Warning') {
        statusColor = "#fb8c00"; 
        badgeColor = "#fb8c00"; 
    } else if (ev.type === 'Error' || ev.reason?.toLowerCase().includes('fail')) {
        statusColor = "#e53935"; 
        badgeColor = "#e53935";
    }

    return `
        <td style="font-size: 0.8rem; vertical-align: top; white-space: nowrap;">${date}</td>
        <td style="vertical-align: top; font-weight: bold; color: ${statusColor};">${ev.type || ""}</td>
        <td style="vertical-align: top;"><code style="color: var(--pico-contrast);">${ev.reason || ""}</code></td>
        <td>
            <div style="display: flex; align-items: flex-start; gap: 8px;">
                ${ev.count > 1 ? `
                    <span style="background-color: ${badgeColor}; color: white; padding: 2px 8px; border-radius: 1rem; font-size: 0.7rem; font-weight: bold; margin-top: 2px; white-space: nowrap;">
                        ${ev.count}x
                    </span>` : ''}
                <span style="line-height: 1.5; font-size: 0.95rem;">${ev.message || ""}</span>
            </div>
        </td>
        <td style="font-size: 0.8rem; vertical-align: top;">
            <div style="display: flex; align-items: flex-start; gap: 12px;">
                <kbd style="font-size: 0.6rem; background: var(--pico-muted-background); color: var(--pico-muted-color); text-transform: uppercase; min-width: 45px; text-align: center;">
                    ${ev.involved_kind}
                </kbd>
                <div style="line-height: 1.2;">
                    <div style="color: var(--pico-muted-color); font-size: 0.75rem;">
                        <a href="javascript:void(0)" onclick="applyFilter('${ev.namespace}')" style="color:inherit">${ev.namespace}</a>
                    </div>
                    <div style="font-weight: bold; color: var(--pico-contrast);">
                        <a href="javascript:void(0)" onclick="applyFilter('${ev.involved_name}')" style="color:inherit">${ev.involved_name}</a>
                    </div>
                </div>
            </div>
        </td>
    `;
}

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

connectStream();

document.getElementById("limitSelect").addEventListener("change", e => {
    currentLimit = parseInt(e.target.value);
    connectStream();
});

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
        tr.innerHTML = createEventRowHtml(ev, false);
        streamBody.appendChild(tr);
    });

    renderPagination(document.getElementById("streamPagination"), filtered.length, renderStream);
}

streamFilter.addEventListener("input", renderStream);

// --- Suche ---
async function doSearch(page = 1) {
    searchPage = page;
    const q = document.getElementById("searchInput").value || "";
    const url = `/events/search?q=${encodeURIComponent(q)}&page=${page}&page_size=${SEARCH_PAGE_SIZE}`;
    const res = await fetch(url);
    if (!res.ok) return;

    const data = await res.json();
    const items = data.items || [];
    document.getElementById("searchResults").innerHTML = "";
    items.forEach(ev => {
        const tr = document.createElement("tr");
        tr.innerHTML = createEventRowHtml(ev, true);
        document.getElementById("searchResults").appendChild(tr);
    });
    renderSearchPagination(data.pages || 1);
}

document.getElementById("searchBtn").onclick = () => doSearch(1);
document.getElementById("searchInput").onkeydown = e => { if (e.key === "Enter") doSearch(1); };

// --- Stats ---
async function updateStats() {
    const container = document.getElementById("statsList");
    container.style.opacity = "0.5"; // Lade-Feedback

    try {
        const res = await fetch('/metrics');
        const text = await res.text();
        const lines = text.split('\n');

        const stats = {
            total: 0, restarts: 0, errors: 0,
            namespaces: new Set(), deployments: new Set(), pods: new Set(),
            badNamespaces: new Set(), badDeployments: new Set(), badPods: new Set()
        };

        lines.forEach(line => {
            if (!line.startsWith('kubeevents_') || line.includes('_created')) return;
            const match = line.match(/^([a-z0-9_]+)\{(.*)\}\s+(\d+)/);
            if (!match) {
                const simpleMatch = line.match(/^(kubeevents_total|kubeevents_watch_restarts_total|kubeevents_watch_errors_total)\s+(\d+)/);
                if (simpleMatch) {
                    const val = parseInt(simpleMatch[2]);
                    if (simpleMatch[1].includes('total')) stats.total = val;
                    if (simpleMatch[1].includes('restarts')) stats.restarts = val;
                    if (simpleMatch[1].includes('errors')) stats.errors = val;
                }
                return;
            };

            const [_, name, labelStr, valueStr] = match;
            const val = parseInt(valueStr);
            if (val === 0) return;

            const labels = Object.fromEntries(labelStr.split(',').map(s => s.split('=').map(v => v.replace(/"/g, ''))));
            const isBad = labels.type === 'Warning' || labels.type === 'Error';

            if (name === 'kubeevents_namespace_total') { stats.namespaces.add(labels.namespace); if (isBad) stats.badNamespaces.add(labels.namespace); }
            if (name === 'kubeevents_deployment_total') { stats.deployments.add(labels.deployment); if (isBad) stats.badDeployments.add(labels.deployment); }
            if (name === 'kubeevents_pod_total') { stats.pods.add(labels.pod); if (isBad) stats.badPods.add(labels.pod); }
        });

        renderStatsUI(stats);
    } catch (e) { console.error("Stats Error:", e); }
    container.style.opacity = "1";
}

function renderStatsUI(s) {
    const container = document.getElementById("statsList");
    container.style.cursor = "pointer";
    container.onclick = (e) => { if (e.target.tagName !== 'A') updateStats(); };

    const makeClickable = (list, color) => {
        if (list.size === 0) return '<span style="color: var(--pico-muted-color);">None</span>';
        return Array.from(list).map(item => `
            <a href="javascript:void(0)" onclick="event.stopPropagation(); applyFilter('${item}')" 
               style="color: ${color}; text-decoration: underline; margin-right: 8px; font-weight: 500;">${item}</a>
        `).join('');
    };

    container.innerHTML = `
        <div class="grid">
            <article style="padding: 1rem; border-top: 4px solid var(--pico-primary);">
                <small>Total Events <cite>(Click to refresh)</cite></small>
                <h3 style="margin:0">${s.total}</h3>
            </article>
            <article style="padding: 1rem; border-top: 4px solid var(--pico-secondary);">
                <small>Active (NS/Depl/Pods)</small>
                <h3 style="margin:0">${s.namespaces.size} / ${s.deployments.size} / ${s.pods.size}</h3>
            </article>
            <article style="padding: 1rem; border-top: 4px solid ${s.restarts > 0 ? '#fb8c00' : 'var(--pico-muted-border)'}">
                <small>Watch Restarts</small>
                <h3 style="margin:0">${s.restarts}</h3>
            </article>
            <article style="padding: 1rem; border-top: 4px solid ${s.errors > 0 ? '#e53935' : 'var(--pico-muted-border)'}">
                <small>Watch Errors</small>
                <h3 style="margin:0">${s.errors}</h3>
            </article>
        </div>
        <div class="grid" style="margin-top: 1rem; background: var(--pico-card-background-color); padding: 1rem; border-radius: 8px;">
            <div><strong style="color: #fb8c00;">⚠️ Bad Namespaces:</strong><div style="font-size: 0.85rem;">${makeClickable(s.badNamespaces, '#fb8c00')}</div></div>
            <div><strong style="color: #fb8c00;">⚠️ Bad Deployments:</strong><div style="font-size: 0.85rem;">${makeClickable(s.badDeployments, '#fb8c00')}</div></div>
            <div><strong style="color: #e53935;">🔥 Critical Pods:</strong><div style="font-size: 0.85rem;">${makeClickable(s.badPods, '#e53935')}</div></div>
        </div>
    `;
}

function applyFilter(value) {
    const filterInput = document.getElementById('streamFilter');
    filterInput.value = value;
    document.querySelector('.tab[data-tab="stream"]').click(); // Tab-Wechsel
    renderStream();
    filterInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// --- Pagination & Sort ---
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
        a.href = "#"; a.innerText = i;
        if (i === currentPage) a.setAttribute("aria-current", "page");
        a.onclick = e => { e.preventDefault(); currentPage = i; onPageChange(); };
        li.appendChild(a); container.appendChild(li);
    }
}

function renderSearchPagination(totalPages) {
    const container = document.getElementById("searchPagination");
    container.innerHTML = "";
    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#"; a.innerText = i;
        if (i === searchPage) a.setAttribute("aria-current", "page");
        a.onclick = e => { e.preventDefault(); doSearch(i); };
        li.appendChild(a); container.appendChild(li);
    }
}