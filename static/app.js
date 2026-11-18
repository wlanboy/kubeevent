"use strict";

const STREAM_PAGE_SIZE = 20;
const SEARCH_PAGE_SIZE = 20;
const STATS_REFRESH_MS = 30000;
const HIGHLIGHT_MS = 4000;
const STREAM_RETRY_MS = 5000;
const TABS = ["stream", "search", "stats"];

const $ = id => document.getElementById(id);

// --- DOM-Helfer: baut Elemente ohne innerHTML, Texte landen immer als Textknoten ---
function h(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") node.className = value;
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : String(child));
    }
    return node;
}

// --- Zeit ---
const relativeFormat = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const TIME_UNITS = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];

function parseTime(value) {
    if (!value) return null;
    // Ältere Antworten ohne Zeitzone sind UTC
    const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
    const date = new Date(hasZone ? value : value + "Z");
    return Number.isNaN(date.getTime()) ? null : date;
}

function relativeTime(date) {
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    for (const [unit, size] of TIME_UNITS) {
        if (Math.abs(seconds) >= size || unit === "second") {
            return relativeFormat.format(Math.round(seconds / size), unit);
        }
    }
    return "";
}

function timeElement(date) {
    if (!date) return "";
    return h("time", { datetime: date.toISOString(), title: date.toLocaleString(), "data-relative": "" },
        relativeTime(date));
}

function formatTime(value) {
    const date = parseTime(value);
    return date ? date.toLocaleString() : "–";
}

function eventTime(ev) {
    return parseTime(ev.last_timestamp) || parseTime(ev.created_at);
}

setInterval(() => {
    document.querySelectorAll("time[data-relative]").forEach(el => {
        el.textContent = relativeTime(new Date(el.dateTime));
    });
}, 30000);

// --- Event-Tabelle (Stream und Suche) ---
function typeClass(type) {
    return type === "Warning" ? "type-warning" : "type-normal";
}

function filterLink(label, onSelect) {
    return h("a", {
        href: "#",
        class: "filter-link",
        title: `Filter by ${label}`,
        onclick: e => { e.preventDefault(); e.stopPropagation(); onSelect(); }
    }, label);
}

function detailsRow(ev) {
    const entries = [
        ["Message", h("span", { class: "full-message" }, ev.message || "–")],
        ["Type", ev.type || "–"],
        ["Reason", ev.reason || "–"],
        ["Count", ev.count ?? "–"],
        ["Object", `${ev.involved_kind || "?"} ${ev.namespace}/${ev.involved_name || "?"}`],
        ["Component", ev.component || "–"],
        ["Host", ev.host || "–"],
        ["First seen", formatTime(ev.first_timestamp)],
        ["Last seen", formatTime(ev.last_timestamp)],
        ["Received", formatTime(ev.created_at)],
        ["Event name", ev.name || "–"],
        ["UID", ev.uid || "–"],
    ];
    return h("tr", { class: "details-row" },
        h("td", { colspan: "5" },
            h("dl", { class: "details" }, entries.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))));
}

/**
 * Baut die Zeilen für ein Event. ctx liefert:
 *  expanded: Set der aufgeklappten Event-IDs
 *  onNamespace(ns), onName(name): Klick auf die Filter-Links
 *  highlightAge(ev): ms seit Eingang, oder null wenn nicht hervorheben
 */
function eventRows(ev, ctx) {
    const isOpen = ctx.expanded.has(ev.id);
    const age = ctx.highlightAge ? ctx.highlightAge(ev) : null;

    const row = h("tr", {
        class: "event-row" + (age !== null ? " is-new" : ""),
        tabindex: "0",
        "aria-expanded": String(isOpen),
        title: "Click for details",
    },
        h("td", { class: "col-time" }, timeElement(eventTime(ev))),
        h("td", { class: "col-type" }, h("span", { class: "type-pill " + typeClass(ev.type) }, ev.type || "")),
        h("td", { class: "col-reason" }, h("code", {}, ev.reason || "")),
        h("td", {},
            h("div", { class: "msg-wrap" },
                ev.count > 1 ? h("span", { class: "count-badge " + typeClass(ev.type) }, `${ev.count}x`) : null,
                h("span", { class: "msg" }, ev.message || ""))),
        h("td", { class: "col-object" },
            h("div", { class: "obj" },
                h("kbd", {}, ev.involved_kind || "?"),
                h("div", {},
                    h("div", { class: "obj-ns" }, filterLink(ev.namespace, () => ctx.onNamespace(ev.namespace))),
                    h("div", { class: "obj-name" },
                        ev.involved_name ? filterLink(ev.involved_name, () => ctx.onName(ev.involved_name)) : "?")))),
    );
    if (age !== null) row.style.setProperty("--kv-flash-delay", `-${age}ms`);

    const toggle = () => {
        // Beim Markieren von Text nicht auf- oder zuklappen
        if (String(window.getSelection() || "").length > 0) return;
        const open = !ctx.expanded.has(ev.id);
        if (open) {
            ctx.expanded.add(ev.id);
            row.after(detailsRow(ev));
        } else {
            ctx.expanded.delete(ev.id);
            if (row.nextElementSibling?.classList.contains("details-row")) row.nextElementSibling.remove();
        }
        row.setAttribute("aria-expanded", String(open));
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", e => {
        if (e.target === row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(); }
    });

    return isOpen ? [row, detailsRow(ev)] : [row];
}

function messageRow(text, isError = false) {
    return h("tr", { class: "empty-row" + (isError ? " is-error" : "") }, h("td", { colspan: "5" }, text));
}

function rangeInfo(start, shown, total) {
    if (total === 0) return "";
    return `Showing ${start + 1}–${start + shown} of ${total}`;
}

// --- Pagination ---
function pageWindow(page, pages) {
    const wanted = new Set([1, pages]);
    for (let p = page - 2; p <= page + 2; p++) if (p >= 1 && p <= pages) wanted.add(p);
    const result = [];
    let previous = 0;
    for (const p of [...wanted].sort((a, b) => a - b)) {
        if (p - previous > 1) result.push(null);
        result.push(p);
        previous = p;
    }
    return result;
}

function renderPager(container, page, pages, onSelect) {
    container.replaceChildren();
    if (pages <= 1) return;

    const link = (label, target, { current = false, disabled = false, ariaLabel = null } = {}) => {
        if (disabled) return h("li", {}, h("span", { class: "pager-gap", "aria-disabled": "true" }, label));
        return h("li", {}, h("a", {
            href: "#",
            "aria-current": current ? "page" : null,
            "aria-label": ariaLabel,
            onclick: e => { e.preventDefault(); onSelect(target); }
        }, label));
    };

    container.append(link("‹ Prev", page - 1, { disabled: page === 1, ariaLabel: "Previous page" }));
    for (const p of pageWindow(page, pages)) {
        container.append(p === null ? link("…", 0, { disabled: true }) : link(String(p), p, { current: p === page }));
    }
    container.append(link("Next ›", page + 1, { disabled: page === pages, ariaLabel: "Next page" }));
}

// --- URL-Zustand (#tab?param=...) ---
const tabState = { stream: {}, search: {}, stats: {} };

function buildHash(tab, params) {
    const clean = Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined);
    const query = new URLSearchParams(clean).toString();
    return `#${tab}${query ? "?" + query : ""}`;
}

function readHash() {
    const raw = location.hash.slice(1);
    const split = raw.indexOf("?");
    const tab = split === -1 ? raw : raw.slice(0, split);
    const params = new URLSearchParams(split === -1 ? "" : raw.slice(split + 1));
    return { tab: TABS.includes(tab) ? tab : "stream", params };
}

/** Neuer History-Eintrag; löst über hashchange route() aus. */
function navigate(tab, params = {}) {
    tabState[tab] = params;
    const hash = buildHash(tab, params);
    if (hash === location.hash) route();
    else location.hash = hash;
}

/** Zustand in der URL festhalten, ohne neu zu laden (z. B. beim Tippen). */
function rememberState(tab, params) {
    tabState[tab] = params;
    history.replaceState(null, "", buildHash(tab, params));
}

// --- Tabs ---
const tabLinks = [...document.querySelectorAll(".tab")];

function showTab(tab) {
    for (const link of tabLinks) {
        const active = link.dataset.tab === tab;
        link.setAttribute("aria-selected", String(active));
        link.tabIndex = active ? 0 : -1;
        $("tab-" + link.dataset.tab).hidden = !active;
    }
}

tabLinks.forEach((link, index) => {
    link.addEventListener("click", e => {
        e.preventDefault();
        navigate(link.dataset.tab, tabState[link.dataset.tab]);
    });
    link.addEventListener("keydown", e => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
        if (!step) return;
        e.preventDefault();
        const next = tabLinks[(index + step + tabLinks.length) % tabLinks.length];
        next.focus();
        next.click();
    });
});

function route() {
    const { tab, params } = readHash();
    showTab(tab);
    tabState[tab] = Object.fromEntries(params);

    if (tab === "stream") {
        const filter = params.get("filter") || "";
        if ($("streamFilter").value !== filter) {
            $("streamFilter").value = filter;
            stream.page = 1;
        }
        renderStream();
    } else if (tab === "search") {
        applySearchParams(params);
        loadFacets();
        doSearch();
    } else {
        $("statsRange").value = params.get("hours") || "24";
        loadStats();
    }
    updateStatsTimer(tab === "stats");
}

window.addEventListener("hashchange", route);

// --- Stream ---
const stream = {
    events: [],
    limit: 100,
    page: 1,
    paused: false,
    pending: 0,
    source: null,
    retryTimer: null,
    arrivedAt: new Map(),
    expanded: new Set(),
};

const streamCtx = {
    expanded: stream.expanded,
    onNamespace: value => setStreamFilter(value),
    onName: value => setStreamFilter(value),
    highlightAge: ev => {
        const arrived = stream.arrivedAt.get(ev.id);
        if (arrived === undefined) return null;
        const age = Date.now() - arrived;
        return age < HIGHLIGHT_MS ? age : null;
    },
};

const STATUS_LABELS = {
    connecting: "Connecting…",
    live: "Live",
    reconnecting: "Reconnecting…",
    disconnected: "Disconnected – retrying",
};

function setStatus(state) {
    const el = $("connStatus");
    el.dataset.state = state;
    el.textContent = STATUS_LABELS[state];
}

/** Neueste zuerst, wie der Server-Snapshot (created_at, dann id). */
function byReceivedDesc(a, b) {
    const diff = (parseTime(b.created_at)?.getTime() ?? 0) - (parseTime(a.created_at)?.getTime() ?? 0);
    return diff !== 0 ? diff : b.id - a.id;
}

function connectStream() {
    if (stream.source) stream.source.close();
    clearTimeout(stream.retryTimer);
    setStatus("connecting");

    const source = new EventSource(`/events/stream?limit=${stream.limit}`);
    stream.source = source;

    source.onopen = () => setStatus("live");

    source.addEventListener("snapshot", e => {
        stream.events = JSON.parse(e.data);
        stream.arrivedAt.clear();
        renderStreamIfIdle(0);
    });

    source.addEventListener("append", e => {
        const known = new Set(stream.events.map(ev => ev.id));
        const fresh = JSON.parse(e.data).filter(ev => !known.has(ev.id));
        if (fresh.length === 0) return;

        const now = Date.now();
        fresh.forEach(ev => stream.arrivedAt.set(ev.id, now));
        stream.events = fresh.concat(stream.events).sort(byReceivedDesc).slice(0, stream.limit);
        renderStreamIfIdle(fresh.length);
    });

    source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) {
            setStatus("disconnected");
            stream.retryTimer = setTimeout(connectStream, STREAM_RETRY_MS);
        } else {
            setStatus("reconnecting");
        }
    };
}

function selectionInside(element) {
    const selection = window.getSelection();
    return selection && !selection.isCollapsed && element.contains(selection.anchorNode);
}

/** Bei Pause oder markiertem Text nur zählen, sonst neu zeichnen. */
function renderStreamIfIdle(newCount) {
    if (stream.paused || selectionInside($("streamBody"))) {
        stream.pending += newCount;
        updatePauseButton();
        return;
    }
    renderStream();
}

document.addEventListener("selectionchange", () => {
    if (stream.pending > 0 && !stream.paused && !selectionInside($("streamBody"))) renderStream();
});

function streamMatches(ev, filter) {
    if (!filter) return true;
    return [ev.type, ev.reason, ev.message, ev.involved_name, ev.involved_kind, ev.namespace, ev.component, ev.host]
        .some(value => value && value.toLowerCase().includes(filter));
}

function renderStream() {
    stream.pending = 0;
    const now = Date.now();
    for (const [id, arrived] of stream.arrivedAt) {
        if (now - arrived >= HIGHLIGHT_MS) stream.arrivedAt.delete(id);
    }
    const ids = new Set(stream.events.map(ev => ev.id));
    for (const id of stream.expanded) if (!ids.has(id)) stream.expanded.delete(id);

    const filter = $("streamFilter").value.trim().toLowerCase();
    const filtered = stream.events.filter(ev => streamMatches(ev, filter));
    const pages = Math.max(1, Math.ceil(filtered.length / STREAM_PAGE_SIZE));
    stream.page = Math.min(stream.page, pages);
    const start = (stream.page - 1) * STREAM_PAGE_SIZE;
    const pageItems = filtered.slice(start, start + STREAM_PAGE_SIZE);

    let rows;
    if (pageItems.length > 0) rows = pageItems.flatMap(ev => eventRows(ev, streamCtx));
    else if (stream.events.length > 0) rows = [messageRow("No events match the filter.")];
    else rows = [messageRow("Waiting for events…")];
    $("streamBody").replaceChildren(...rows);

    renderPager($("streamPagination"), stream.page, pages, p => { stream.page = p; renderStream(); });
    $("streamInfo").textContent = rangeInfo(start, pageItems.length, filtered.length)
        + (filter && filtered.length ? ` (filtered from ${stream.events.length})` : "");
    updatePauseButton();
}

function updatePauseButton() {
    const button = $("streamPause");
    button.setAttribute("aria-pressed", String(stream.paused));
    if (stream.paused) button.textContent = stream.pending > 0 ? `Resume (${stream.pending} new)` : "Resume";
    else button.textContent = "Pause";
}

function setStreamFilter(value) {
    $("streamFilter").value = value;
    stream.page = 1;
    rememberState("stream", { filter: value });
    renderStream();
    $("streamFilter").scrollIntoView({ behavior: "smooth", block: "center" });
}

$("streamFilter").addEventListener("input", e => {
    stream.page = 1;
    rememberState("stream", { filter: e.target.value });
    renderStream();
});

$("streamClear").addEventListener("click", () => {
    $("streamFilter").value = "";
    stream.page = 1;
    rememberState("stream", {});
    renderStream();
});

$("streamPause").addEventListener("click", () => {
    stream.paused = !stream.paused;
    if (stream.paused) updatePauseButton();
    else renderStream();
});

$("limitSelect").addEventListener("change", e => {
    stream.limit = parseInt(e.target.value, 10);
    stream.page = 1;
    connectStream();
});

// --- Suche ---
const search = { page: 1, controller: null, expanded: new Set() };

const searchCtx = {
    expanded: search.expanded,
    onNamespace: value => {
        ensureOption($("searchNamespace"), value);
        $("searchNamespace").value = value;
        submitSearch();
    },
    onName: value => {
        $("searchInput").value = value;
        submitSearch();
    },
    highlightAge: null,
};

function ensureOption(select, value) {
    if (value && ![...select.options].some(o => o.value === value)) select.append(h("option", { value }, value));
}

function setSelect(select, value) {
    ensureOption(select, value);
    select.value = value;
}

function searchFormParams() {
    return {
        q: $("searchInput").value.trim(),
        type: $("searchType").value,
        ns: $("searchNamespace").value,
        kind: $("searchKind").value,
        range: $("searchRange").value,
        page: search.page > 1 ? search.page : "",
    };
}

function applySearchParams(params) {
    $("searchInput").value = params.get("q") || "";
    setSelect($("searchType"), params.get("type") || "");
    setSelect($("searchNamespace"), params.get("ns") || "");
    setSelect($("searchKind"), params.get("kind") || "");
    setSelect($("searchRange"), params.get("range") || "");
    search.page = Math.max(1, parseInt(params.get("page"), 10) || 1);
}

function submitSearch(page = 1) {
    search.page = page;
    navigate("search", searchFormParams());
}

function fillSelect(select, values) {
    const current = select.value;
    select.replaceChildren(h("option", { value: "" }, "All"), ...values.map(v => h("option", { value: v }, v)));
    setSelect(select, current);
}

async function loadFacets() {
    try {
        const res = await fetch("/events/facets");
        if (!res.ok) return;
        const data = await res.json();
        fillSelect($("searchNamespace"), data.namespaces || []);
        fillSelect($("searchKind"), data.kinds || []);
    } catch (e) {
        console.warn("Could not load filter values", e);
    }
}

async function doSearch() {
    const form = searchFormParams();
    const api = new URLSearchParams({ page: search.page, page_size: SEARCH_PAGE_SIZE });
    if (form.q) api.set("q", form.q);
    if (form.type) api.set("type", form.type);
    if (form.ns) api.set("namespace", form.ns);
    if (form.kind) api.set("kind", form.kind);
    if (form.range) api.set("since", new Date(Date.now() - Number(form.range) * 3600000).toISOString());

    search.controller?.abort();
    const controller = new AbortController();
    search.controller = controller;

    const body = $("searchResults");
    $("searchBtn").setAttribute("aria-busy", "true");
    $("searchInfo").textContent = "Searching…";

    try {
        const res = await fetch(`/events/search?${api}`, { signal: controller.signal });
        if (!res.ok) throw new Error(`server responded with HTTP ${res.status}`);
        const data = await res.json();
        const items = data.items || [];

        // Seite hinter dem Ende (z. B. nach Retention): auf die letzte Seite springen
        if (items.length === 0 && data.total > 0 && search.page > 1) {
            submitSearch(Math.max(1, data.pages));
            return;
        }

        search.expanded.clear();
        body.replaceChildren(...(items.length
            ? items.flatMap(ev => eventRows(ev, searchCtx))
            : [messageRow("No events found.")]));
        $("searchInfo").textContent = rangeInfo((search.page - 1) * SEARCH_PAGE_SIZE, items.length, data.total);
        renderPager($("searchPagination"), search.page, data.pages || 1, p => submitSearch(p));
    } catch (e) {
        if (e.name === "AbortError") return;
        body.replaceChildren(messageRow(`Search failed: ${e.message}`, true));
        $("searchInfo").textContent = "";
        $("searchPagination").replaceChildren();
    } finally {
        if (search.controller === controller) $("searchBtn").removeAttribute("aria-busy");
    }
}

$("searchForm").addEventListener("submit", e => { e.preventDefault(); submitSearch(); });
["searchType", "searchNamespace", "searchKind", "searchRange"].forEach(id => {
    $(id).addEventListener("change", () => submitSearch());
});
$("searchReset").addEventListener("click", () => {
    $("searchInput").value = "";
    ["searchType", "searchNamespace", "searchKind", "searchRange"].forEach(id => { $(id).value = ""; });
    submitSearch();
});

// --- Stats ---
let statsTimer = null;
let statsController = null;

function updateStatsTimer(active) {
    clearInterval(statsTimer);
    statsTimer = active ? setInterval(() => { if (!document.hidden) loadStats(); }, STATS_REFRESH_MS) : null;
}

async function loadStats() {
    const hours = $("statsRange").value;
    statsController?.abort();
    const controller = new AbortController();
    statsController = controller;
    $("statsRefresh").setAttribute("aria-busy", "true");

    try {
        const res = await fetch(`/events/stats?hours=${encodeURIComponent(hours)}`, { signal: controller.signal });
        if (!res.ok) throw new Error(`server responded with HTTP ${res.status}`);
        renderStats(await res.json());
        $("statsUpdated").textContent = `Updated ${new Date().toLocaleTimeString()} · refreshes every ${STATS_REFRESH_MS / 1000}s`;
    } catch (e) {
        if (e.name === "AbortError") return;
        $("statsUpdated").textContent = `Loading stats failed: ${e.message}`;
    } finally {
        if (statsController === controller) $("statsRefresh").removeAttribute("aria-busy");
    }
}

function tile(label, value, variant = "", note = null) {
    return h("article", { class: `tile ${variant}` },
        h("small", {}, label),
        h("h3", {}, String(value)),
        note ? h("small", { class: "muted" }, note) : null);
}

function topList(title, rows, emptyText) {
    return h("article", {},
        h("header", {}, h("strong", {}, title)),
        rows.length === 0
            ? h("p", { class: "muted" }, emptyText)
            : h("table", { class: "striped" },
                h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, r.label), h("td", { class: "num" }, r.count))))));
}

function renderStats(s) {
    const range = String(s.hours);
    const warnings = s.by_type.Warning || 0;
    const share = s.total ? Math.round((warnings / s.total) * 100) : 0;
    const toSearch = params => () => navigate("search", { type: "Warning", range, ...params });

    const link = (text, onClick) => h("a", {
        href: "#",
        onclick: e => { e.preventDefault(); onClick(); }
    }, text);

    $("statsContent").replaceChildren(
        h("div", { class: "tiles" },
            tile("Events", s.total, "accent"),
            tile("Warnings", warnings, warnings > 0 ? "warn" : "", s.total ? `${share}% of all events` : null),
            tile("Namespaces", s.namespaces),
            tile("Watch restarts", s.watcher.restarts, s.watcher.restarts > 0 ? "warn" : "", "since app start"),
            tile("Watch errors", s.watcher.errors, s.watcher.errors > 0 ? "error" : "", "since app start"),
        ),
        h("div", { class: "top-lists" },
            topList("Namespaces with most warnings",
                s.top_warning_namespaces.map(r => ({
                    label: link(r.namespace, toSearch({ ns: r.namespace })),
                    count: r.count,
                })),
                "No warnings in this time window."),
            topList("Most frequent warning reasons",
                s.top_warning_reasons.map(r => ({
                    label: r.reason ? link(r.reason, toSearch({ q: r.reason })) : "(none)",
                    count: r.count,
                })),
                "No warnings in this time window."),
            topList("Objects with most warnings",
                s.top_warning_objects.map(r => ({
                    label: h("span", {},
                        link(r.name || "?", toSearch({ q: r.name || "", ns: r.namespace })),
                        h("span", { class: "sub" }, `${r.kind || "?"} · ${r.namespace}`)),
                    count: r.count,
                })),
                "No warnings in this time window."),
        ),
    );
}

$("statsRange").addEventListener("change", e => navigate("stats", { hours: e.target.value }));
$("statsRefresh").addEventListener("click", loadStats);

// --- Start ---
connectStream();
route();
