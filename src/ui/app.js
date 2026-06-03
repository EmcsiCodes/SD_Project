const state = {
    lastReport: null,
    lastResults: [],
    activeDbPath: "",
};

const elements = {
    workingDirectory: document.getElementById("working-directory"),
    statusBanner: document.getElementById("status-banner"),
    reportGrid: document.getElementById("report-grid"),
    resultsSummary: document.getElementById("results-summary"),
    colorShortcuts: document.getElementById("color-shortcuts"),
    widgetsPanel: document.getElementById("widgets-panel"),
    resultsList: document.getElementById("results-list"),
    indexForm: document.getElementById("index-form"),
    searchForm: document.getElementById("search-form"),
    clearButton: document.getElementById("clear-button"),
    indexButton: document.getElementById("index-button"),
    searchButton: document.getElementById("search-button"),
    root: document.getElementById("root"),
    dbPath: document.getElementById("db-path"),
    ignoreExtensions: document.getElementById("ignore-extensions"),
    ignorePatterns: document.getElementById("ignore-patterns"),
    includeHidden: document.getElementById("include-hidden"),
    maxFileSizeMb: document.getElementById("max-file-size-mb"),
    query: document.getElementById("query"),
    limit: document.getElementById("limit"),
    scope: document.getElementById("scope"),
    rankingStrategy: document.getElementById("ranking-strategy"),
};

document.addEventListener("DOMContentLoaded", () => {
    wireEvents();
    loadConfig();
});

function wireEvents() {
    elements.indexForm.addEventListener("submit", onIndexSubmit);
    elements.searchForm.addEventListener("submit", onSearchSubmit);
    elements.clearButton.addEventListener("click", resetResults);
}

async function loadConfig() {
    setStatus("info", "Loading configuration...");
    try {
        const config = await sendJson("/api/config", { method: "GET" });
        elements.root.value = config.default_root || ".";
        elements.dbPath.value = config.default_db || ".local_search.db";
        state.activeDbPath = elements.dbPath.value;
        elements.workingDirectory.textContent = config.working_directory || config.default_root || ".";
        setStatus("info", "Ready. Index a folder or search an existing database.");
    } catch (error) {
        setStatus("error", error.message);
        elements.workingDirectory.textContent = "Unable to load server configuration.";
    }
}

async function onIndexSubmit(event) {
    event.preventDefault();
    toggleBusy(true, "index");
    setStatus("info", "Indexing is running. Large folders can take a while.");

    try {
        const payload = {
            root: elements.root.value.trim(),
            db_path: elements.dbPath.value.trim(),
            ignore_extensions: elements.ignoreExtensions.value.trim(),
            ignore_patterns: elements.ignorePatterns.value.trim(),
            include_hidden: elements.includeHidden.checked,
            max_file_size_mb: Number(elements.maxFileSizeMb.value || 2),
        };
        const response = await sendJson("/api/index", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        state.lastReport = response.report || null;
        elements.dbPath.value = response.db_path || elements.dbPath.value;
        state.activeDbPath = elements.dbPath.value;
        renderReport(state.lastReport);
        renderColorShortcuts(response.colors || []);
        setStatus(
            "success",
            buildIndexStatus(response)
        );
    } catch (error) {
        setStatus("error", error.message);
    } finally {
        toggleBusy(false, "index");
    }
}

async function onSearchSubmit(event) {
    event.preventDefault();
    toggleBusy(true, "search");
    setStatus("info", "Searching the index...");

    try {
        const payload = {
            db_path: elements.dbPath.value.trim(),
            query: elements.query.value.trim(),
            limit: Number(elements.limit.value || 10),
            scope: elements.scope.value,
            ranking_strategy: elements.rankingStrategy.value,
        };
        const response = await sendJson("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        state.lastResults = response.results || [];
        state.activeDbPath = payload.db_path;
        renderColorShortcuts(response.colors || []);
        renderWidgets(response.widgets || []);
        renderResults(response.query, response.scope, response.ranking_strategy, state.lastResults);
        setStatus(
            "success",
            state.lastResults.length
                ? `Found ${state.lastResults.length} result${state.lastResults.length === 1 ? "" : "s"}.`
                : "Search completed with no matches."
        );
    } catch (error) {
        setStatus("error", error.message);
    } finally {
        toggleBusy(false, "search");
    }
}

function resetResults() {
    state.lastResults = [];
    elements.query.value = "";
    elements.resultsSummary.textContent = "Search results will appear here after the first query.";
    elements.widgetsPanel.innerHTML = "";
    elements.resultsList.innerHTML = [
        '<article class="empty-state">',
        "<h3>Results cleared</h3>",
        "<p>Run another query whenever you are ready.</p>",
        "</article>",
    ].join("");
    setStatus("info", "Results cleared.");
}

function renderReport(report) {
    if (!report) {
        elements.reportGrid.innerHTML = [
            '<article class="metric-card">',
            '<p class="metric-label">Last index</p>',
            '<p class="metric-value">Not run yet</p>',
            "</article>",
        ].join("");
        return;
    }

    const metrics = [
        ["Seen", report.files_seen],
        ["Indexed", report.files_indexed],
        ["Skipped", report.files_skipped],
        ["Deleted", report.files_deleted || 0],
        ["Errors", report.errors_count],
        ["Seconds", report.duration_seconds],
    ];

    elements.reportGrid.innerHTML = metrics
        .map(
            ([label, value]) => `
                <article class="metric-card">
                    <p class="metric-label">${escapeHtml(String(label))}</p>
                    <p class="metric-value">${escapeHtml(String(value))}</p>
                </article>
            `
        )
        .join("");
}

function renderColorShortcuts(colors) {
    if (!colors.length) {
        elements.colorShortcuts.innerHTML = [
            '<p class="shortcut-note">No image colors indexed in this database yet.</p>',
        ].join("");
        return;
    }

    elements.colorShortcuts.innerHTML = colors
        .map(
            (item) => `
                <button class="color-chip" type="button" data-color="${escapeHtml(item.color)}">
                    <span class="color-swatch color-${escapeHtml(item.color)}"></span>
                    <span>${escapeHtml(item.color)} (${escapeHtml(item.count)})</span>
                </button>
            `
        )
        .join("");

    elements.colorShortcuts.querySelectorAll("[data-color]").forEach((button) => {
        button.addEventListener("click", () => {
            elements.query.value = `color:${button.dataset.color}`;
            elements.scope.value = "all";
            elements.query.focus();
        });
    });
}

function buildIndexStatus(response) {
    const colorCount = (response.colors || []).reduce((total, item) => total + Number(item.count || 0), 0);
    const imageText = colorCount ? ` ${colorCount} image file${colorCount === 1 ? "" : "s"} have colors.` : " No image colors were found.";
    return `Indexing finished. ${response.report.files_indexed} files are searchable.${imageText}`;
}

function renderWidgets(widgets) {
    if (!widgets.length) {
        elements.widgetsPanel.innerHTML = "";
        return;
    }

    elements.widgetsPanel.innerHTML = widgets
        .map(
            (widget) => `
                <article class="widget-card">
                    <p class="widget-title">${escapeHtml(widget.title)}</p>
                    <p class="widget-description">${escapeHtml(widget.description)}</p>
                </article>
            `
        )
        .join("");
}

function renderResults(query, scope, rankingStrategy, results) {
    elements.resultsSummary.textContent = `Query: "${query}" in ${humanizeScope(scope)}, ranked by ${humanizeRanking(rankingStrategy)}.`;

    if (!results.length) {
        elements.resultsList.innerHTML = [
            '<article class="empty-state">',
            "<h3>No matches found</h3>",
            "<p>Try a broader term, switch the search scope, or re-run indexing on the folder.</p>",
            "</article>",
        ].join("");
        return;
    }

    elements.resultsList.innerHTML = results
        .map(
            (result) => `
                <article class="result-card">
                    ${renderImagePreview(result)}
                    <div class="result-header">
                        <div>
                            <h3 class="result-title">${escapeHtml(result.filename)}</h3>
                        </div>
                        <div class="score-pill">score ${escapeHtml(formatScore(result.score))}</div>
                    </div>
                    <p class="result-path"><code>${escapeHtml(result.path)}</code></p>
                    <p class="result-meta"><code>${escapeHtml(result.metadata)}</code></p>
                    ${renderColorSwatch(result.dominant_color)}
                    ${
                        result.snippet
                            ? `<div class="result-snippet">${escapeHtml(result.snippet)}</div>`
                            : ""
                    }
                </article>
            `
        )
        .join("");
}

function renderImagePreview(result) {
    if (result.file_type !== "image") {
        return "";
    }
    const url = `/api/image?path=${encodeURIComponent(result.path)}&db_path=${encodeURIComponent(state.activeDbPath)}`;
    return `
        <div class="result-image-wrap">
            <img class="result-image" src="${url}" alt="${escapeHtml(result.filename)}" loading="lazy">
        </div>
    `;
}

function renderColorSwatch(color) {
    if (!color) {
        return "";
    }
    return `
        <div class="color-row">
            <span class="color-swatch color-${escapeHtml(color)}"></span>
            <span>Dominant color: ${escapeHtml(color)}</span>
        </div>
    `;
}

function humanizeScope(scope) {
    if (scope === "filename") {
        return "filename only";
    }
    if (scope === "content") {
        return "content only";
    }
    return "filename and content";
}

function humanizeRanking(strategy) {
    if (strategy === "path") {
        return "path priority";
    }
    if (strategy === "date") {
        return "newest first";
    }
    if (strategy === "popularity") {
        return "popularity";
    }
    return "best match";
}

function formatScore(score) {
    const numeric = Number(score);
    if (Number.isNaN(numeric)) {
        return "0.00";
    }
    return numeric.toFixed(2);
}

function setStatus(kind, message) {
    elements.statusBanner.className = `status-banner ${kind}`;
    elements.statusBanner.textContent = message;
}

function toggleBusy(isBusy, action) {
    if (action === "index") {
        elements.indexButton.disabled = isBusy;
        elements.indexButton.textContent = isBusy ? "Indexing..." : "Run Indexing";
        return;
    }

    elements.searchButton.disabled = isBusy;
    elements.searchButton.textContent = isBusy ? "Searching..." : "Search";
}

async function sendJson(url, options) {
    const response = await fetch(url, options);
    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};

    if (!response.ok) {
        throw new Error(payload.error || "The request failed.");
    }

    return payload;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
