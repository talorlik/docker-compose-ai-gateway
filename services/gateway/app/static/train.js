(function () {
  "use strict";

  const trainRunBtn = document.getElementById("train-run-btn");
  const trainLastBtn = document.getElementById("train-last-btn");
  const trainProgress = document.getElementById("train-progress");
  const trainMessage = document.getElementById("train-message");
  const trainMetrics = document.getElementById("train-metrics");
  const trainMetricsContent = document.getElementById("train-metrics-content");
  const trainMisclassified = document.getElementById("train-misclassified");
  const trainMisclassifiedContent = document.getElementById("train-misclassified-content");
  const probsModalOverlay = document.getElementById("probs-modal-overlay");
  const probsModal = document.getElementById("probs-modal");
  const probsModalClose = document.getElementById("probs-modal-close");
  const probsModalBody = document.getElementById("probs-modal-body");
  const probsModalResize = document.getElementById("probs-modal-resize");

  function setTrainRunning(running) {
    trainRunBtn.disabled = running;
    if (running) {
      trainProgress.classList.remove("hidden");
      trainMessage.classList.add("hidden");
      trainMetrics.classList.add("hidden");
      trainMisclassified.classList.add("hidden");
    } else {
      trainProgress.classList.add("hidden");
    }
  }

  function showTrainError(msg) {
    trainMessage.classList.remove("hidden");
    trainMessage.textContent = msg;
    trainMessage.setAttribute("data-type", "error");
  }

  function showTrainMessage(msg, type) {
    trainMessage.classList.remove("hidden");
    trainMessage.textContent = msg;
    trainMessage.setAttribute("data-type", type || "info");
  }

  function renderTrainMetrics(data) {
    trainMetrics.classList.remove("hidden");
    trainMetricsContent.innerHTML = "";
    trainMetricsContent.appendChild(buildMetricsDOM(data));
  }

  function formatProbsJson(raw) {
    if (raw == null || raw === "") return "";
    const str = typeof raw === "string" ? raw : String(raw);
    try {
      const parsed = JSON.parse(str);
      return JSON.stringify(parsed, null, 2);
    } catch (_) {
      return str;
    }
  }

  function showProbsModal(probsJson) {
    if (!probsModalOverlay || !probsModalBody) return;
    probsModalBody.textContent = formatProbsJson(probsJson);
    probsModalOverlay.classList.remove("hidden");
    probsModalOverlay.setAttribute("aria-hidden", "false");
  }

  function closeProbsModal() {
    if (!probsModalOverlay) return;
    probsModalOverlay.classList.add("hidden");
    probsModalOverlay.setAttribute("aria-hidden", "true");
  }

  function renderTrainMisclassified(rows) {
    if (!rows || rows.length === 0) {
      trainMisclassified.classList.add("hidden");
      return;
    }
    trainMisclassified.classList.remove("hidden");
    trainMisclassifiedContent.innerHTML = "";
    const table = document.createElement("table");
    table.className = "data-table";
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Text</th><th>True</th><th>Pred</th><th>Confidence</th><th>Probs</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const text = row.text != null ? String(row.text) : "";
      const probs = row.probs_json != null ? String(row.probs_json) : "";
      const probsShort = probs.length > 80 ? probs.slice(0, 77) + "..." : probs;
      tr.innerHTML =
        "<td>" +
        escapeHtml(text.slice(0, 200)) +
        (text.length > 200 ? "..." : "") +
        "</td><td>" +
        escapeHtml(String(row.true_label ?? "")) +
        "</td><td>" +
        escapeHtml(String(row.pred_label ?? "")) +
        "</td><td>" +
        (row.pred_confidence != null ? Number(row.pred_confidence).toFixed(4) : "-") +
        "</td><td></td>";
      const probsTd = tr.querySelector("td:last-child");
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "probs-cell-trigger";
      trigger.textContent = probsShort || "(empty)";
      trigger.title = "Click to view full JSON";
      trigger.addEventListener("click", () => showProbsModal(probs));
      probsTd.appendChild(trigger);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    trainMisclassifiedContent.appendChild(table);
  }

  function renderTrainResult(result) {
    trainMessage.classList.add("hidden");
    renderTrainMetrics(result);
    renderTrainMisclassified(result.misclassified);
  }

  if (probsModalClose) {
    probsModalClose.addEventListener("click", closeProbsModal);
  }
  if (probsModalOverlay) {
    probsModalOverlay.addEventListener("click", (e) => {
      if (e.target === probsModalOverlay) closeProbsModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeProbsModal();
  });

  if (probsModalResize && probsModal) {
    let startX = 0;
    let startY = 0;
    let startW = 0;
    let startH = 0;
    const onMove = (e) => {
      const dw = e.clientX - startX;
      const dh = e.clientY - startY;
      const w = Math.max(320, Math.min(window.innerWidth - 40, startW + dw));
      const h = Math.max(200, Math.min(window.innerHeight - 40, startH + dh));
      probsModal.style.width = w + "px";
      probsModal.style.height = h + "px";
      startX = e.clientX;
      startY = e.clientY;
      startW = w;
      startH = h;
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    probsModalResize.addEventListener("mousedown", (e) => {
      e.preventDefault();
      startX = e.clientX;
      startY = e.clientY;
      startW = probsModal.offsetWidth;
      startH = probsModal.offsetHeight;
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  trainRunBtn.addEventListener("click", async () => {
    if (trainRunBtn.disabled) return;
    setTrainRunning(true);
    try {
      const resp = await fetch("/api/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await resp.json();
      if (!resp.ok) {
        setTrainRunning(false);
        showTrainError(data.message || data.detail || "Start training failed");
        return;
      }
      const jobId = data.job_id;
      if (!jobId) {
        setTrainRunning(false);
        showTrainError("No job_id in response");
        return;
      }
      const eventUrl =
        window.location.origin + "/api/train/events/" + encodeURIComponent(jobId);
      const es = new EventSource(eventUrl);
      es.onmessage = (ev) => {
        es.close();
        setTrainRunning(false);
        try {
          const payload = JSON.parse(ev.data);
          if (payload.status === "completed" && payload.result) {
            renderTrainResult(payload.result);
          } else if (payload.status === "failed") {
            showTrainError(payload.error || "Training failed");
          } else {
            showTrainError("Unexpected event: " + (payload.status || "unknown"));
          }
        } catch (err) {
          showTrainError(err.message || "Invalid event data");
        }
      };
      es.onerror = () => {
        es.close();
        setTrainRunning(false);
        showTrainError("Connection to events stream failed");
      };
    } catch (err) {
      setTrainRunning(false);
      showTrainError(err.message || "Network error");
    }
  });

  trainLastBtn.addEventListener("click", async () => {
    if (trainLastBtn.disabled) return;
    trainLastBtn.disabled = true;
    trainMessage.classList.add("hidden");
    try {
      const resp = await fetch("/api/train/last");
      if (resp.status === 404) {
        showTrainMessage("No previous run found.", "info");
        trainMetrics.classList.add("hidden");
        trainMisclassified.classList.add("hidden");
        return;
      }
      if (!resp.ok) {
        showTrainError("Load last run failed: " + resp.status);
        return;
      }
      const result = await resp.json();
      renderTrainResult(result);
    } catch (err) {
      showTrainError(err.message || "Network error");
    } finally {
      trainLastBtn.disabled = false;
    }
  });
})();
