(function () {
  "use strict";

  const form = document.getElementById("query-form");
  const input = document.getElementById("query-input");
  const submitBtn = document.getElementById("submit-btn");
  const resultSection = document.getElementById("result-section");
  const errorSection = document.getElementById("error-section");

  function showError(msg) {
    errorSection.classList.remove("hidden");
    document.getElementById("error-text").textContent = msg;
  }

  function renderRouteCard(data, isUnknown) {
    const routeName = document.getElementById("route-name");
    const confidenceFill = document.getElementById("confidence-fill");
    const confidenceLabel = document.getElementById("confidence-label");
    const explanation = document.getElementById("explanation");

    routeName.textContent = data.route || "unknown";
    routeName.className = "route-name " + (isUnknown ? "unknown" : "known");

    const confidence = data.confidence ?? 0;
    confidenceFill.style.width = (confidence * 100) + "%";
    confidenceLabel.textContent = (confidence * 100).toFixed(1) + "%";

    const expl = data.explanation || data.top_tokens?.join(", ") || "";
    explanation.textContent = expl ? "Explanation: " + expl : "";
    explanation.classList.toggle("hidden", !expl);
  }

  function renderHopDiagram(trace) {
    const chain = document.getElementById("hop-chain");
    chain.innerHTML = "";

    const services = trace.map((t) => t.service);
    const unique = [];
    let prev = null;
    for (const s of services) {
      if (s !== prev) {
        unique.push(s);
        prev = s;
      }
    }

    if (unique.length === 0) {
      chain.textContent = "No trace data";
      return;
    }

    unique.forEach((service, i) => {
      const span = document.createElement("span");
      span.className = "hop-node";
      span.textContent = service;
      chain.appendChild(span);
      if (i < unique.length - 1) {
        const arrow = document.createElement("span");
        arrow.className = "hop-arrow";
        arrow.textContent = " -> ";
        chain.appendChild(arrow);
      }
    });
  }

  function renderTraceTimeline(trace) {
    const list = document.getElementById("trace-list");
    list.innerHTML = "";

    trace.forEach((entry) => {
      const li = document.createElement("li");
      li.className = "trace-entry";
      const meta = entry.meta
        ? " | " + escapeHtml(JSON.stringify(entry.meta))
        : "";
      li.innerHTML =
        "<strong>" +
        escapeHtml(entry.service) +
        "</strong> " +
        escapeHtml(entry.event) +
        " @ " +
        escapeHtml(entry.ts) +
        meta;
      list.appendChild(li);
    });
  }

  function renderTimings(timings) {
    const content = document.getElementById("timings-content");
    if (!timings) {
      content.textContent = "No timing data";
      return;
    }

    content.textContent =
      "Classify: " +
      (timings.classify ?? "-") +
      " ms | Proxy: " +
      (timings.proxy ?? "-") +
      " ms | Total: " +
      (timings.total ?? "-") +
      " ms";
  }

  function renderBackendResponse(backendResponse, isUnknown) {
    const container = document.getElementById("backend-response");
    const pre = document.getElementById("backend-json");

    if (isUnknown || !backendResponse) {
      container.classList.add("hidden");
      return;
    }

    container.classList.remove("hidden");
    pre.textContent = JSON.stringify(backendResponse, null, 2);
  }

  function renderUnknownMessage(data, isUnknown) {
    const container = document.getElementById("unknown-message");
    const text = document.getElementById("unknown-text");

    if (!isUnknown) {
      container.classList.add("hidden");
      return;
    }

    container.classList.remove("hidden");
    text.textContent =
      data.message || "Unable to determine a suitable backend.";
  }

  function renderServiceError(data, isServiceError) {
    const container = document.getElementById("service-error");
    const text = document.getElementById("service-error-text");

    if (!isServiceError) {
      container.classList.add("hidden");
      return;
    }

    container.classList.remove("hidden");
    text.textContent =
      data.message || "Service temporarily unavailable.";
  }

  function renderResult(data, status) {
    resultSection.classList.remove("hidden");

    const isUnknown = status === 404 || data.route === "unknown";
    const isServiceError = status === 502 || status === 503;

    renderRouteCard(data, isUnknown);
    renderHopDiagram(data.trace || []);
    renderTraceTimeline(data.trace || []);
    renderTimings(data.timings_ms);
    renderBackendResponse(data.backend_response, isUnknown);
    renderUnknownMessage(data, isUnknown);
    renderServiceError(data, isServiceError);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    submitBtn.disabled = true;
    resultSection.classList.add("hidden");
    errorSection.classList.add("hidden");

    const requestId = crypto.randomUUID();
    const body = {
      request_id: requestId,
      text: text,
      trace: [
        {
          service: "web",
          event: "submit",
          ts: new Date().toISOString(),
        },
      ],
    };

    try {
      const resp = await fetch("/api/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await resp.json();
      renderResult(data, resp.status);
    } catch (err) {
      showError(err.message || "Network error");
    } finally {
      submitBtn.disabled = false;
    }
  });
})();
