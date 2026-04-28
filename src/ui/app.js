const state = {
    lastReport: null,
    lastResults: [],
};

const elements = {
    workingDirectory: document.getElementById("working-directory"),
    statusBanner: document.getElementById("status-banner"),
    reportGrid: document.getElementById("report-grid"),
    resultsSummary: document.getElementById("results-summary"),
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
        renderReport(state.lastReport);
        setStatus(
            "success",
            `Indexing finished for ${response.root}. ${response.report.files_indexed} files are searchable.`
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
        };
        const response = await sendJson("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        state.lastResults = response.results || [];
        renderResults(response.query, response.scope, state.lastResults);
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

function renderResults(query, scope, results) {
    elements.resultsSummary.textContent = `Query: "${query}" in ${humanizeScope(scope)}.`;

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
                    <div class="result-header">
                        <div>
                            <h3 class="result-title">${escapeHtml(result.filename)}</h3>
                        </div>
                        <div class="score-pill">score ${escapeHtml(formatScore(result.score))}</div>
                    </div>
                    <p class="result-path"><code>${escapeHtml(result.path)}</code></p>
                    <p class="result-meta"><code>${escapeHtml(result.metadata)}</code></p>
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

function humanizeScope(scope) {
    if (scope === "filename") {
        return "filename only";
    }
    if (scope === "content") {
        return "content only";
    }
    return "filename and content";
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
