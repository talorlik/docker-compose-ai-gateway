(function () {
  "use strict";

  const refineRunBtn = document.getElementById("refine-run-btn");
  const refineLastBtn = document.getElementById("refine-last-btn");
  const refinePromoteBtn = document.getElementById("refine-promote-btn");
  const refinePromoteActions = document.getElementById("refine-promote-actions");
  const refineProgress = document.getElementById("refine-progress");
  const refineMessage = document.getElementById("refine-message");
  const refineReport = document.getElementById("refine-report");
  const refineReportContent = document.getElementById("refine-report-content");
  const refineComparison = document.getElementById("refine-comparison");
  const refineComparisonContent = document.getElementById("refine-comparison-content");
  const refineTables = document.getElementById("refine-tables");
  const refineTablesContent = document.getElementById("refine-tables-content");

  function escapeHtml(s) {
    if (typeof s !== "string") return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function setRefineRunning(running) {
    refineRunBtn.disabled = running;
    refinePromoteBtn.disabled = running;
    if (refineLastBtn) refineLastBtn.disabled = running;
    if (running) {
      refineProgress.classList.remove("hidden");
      refineMessage.classList.add("hidden");
      refineReport.classList.add("hidden");
      refineComparison.classList.add("hidden");
      refineTables.classList.add("hidden");
      if (refinePromoteActions) refinePromoteActions.classList.add("hidden");
    } else {
      refineProgress.classList.add("hidden");
    }
  }

  function setRefinePromoting(promoting) {
    refinePromoteBtn.disabled = promoting;
    refineRunBtn.disabled = promoting;
    if (refineLastBtn) refineLastBtn.disabled = promoting;
    if (promoting) {
      refineProgress.classList.remove("hidden");
      refineProgress.querySelector(".progress-label").textContent = "Promoting...";
    } else {
      refineProgress.classList.add("hidden");
      refineProgress.querySelector(".progress-label").textContent = "Running...";
    }
  }

  function showRefineError(msg, fullDetail) {
    refineMessage.classList.remove("hidden");
    refineMessage.textContent = msg;
    refineMessage.setAttribute("data-type", "error");
    if (refinePromoteActions) refinePromoteActions.classList.add("hidden");
    if (fullDetail) console.error("Refinement error (full):", fullDetail);
  }

  function showRefineMessage(msg, type) {
    refineMessage.classList.remove("hidden");
    refineMessage.textContent = msg;
    refineMessage.setAttribute("data-type", type || "info");
  }

  function buildMetricsDOM(data) {
    const frag = document.createDocumentFragment();
    const acc = data.accuracy;
    const report = data.classification_report || {};
    const matrix = data.confusion_matrix || [];
    const labelKeys = Object.keys(report).filter(
      (k) =>
        typeof report[k] === "object" &&
        report[k] !== null &&
        "precision" in report[k]
    );

    const accEl = document.createElement("p");
    accEl.className = "metrics-accuracy";
    accEl.textContent = "Accuracy: " + (acc != null ? (Number(acc) * 100).toFixed(2) + "%" : "-");
    frag.appendChild(accEl);

    if (labelKeys.length > 0) {
      const table = document.createElement("table");
      table.className = "data-table";
      const thead = document.createElement("thead");
      thead.innerHTML =
        "<tr><th>Label</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      labelKeys.forEach((label) => {
        const row = report[label];
        const tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" +
          escapeHtml(label) +
          "</td><td>" +
          (row.precision != null ? Number(row.precision).toFixed(4) : "-") +
          "</td><td>" +
          (row.recall != null ? Number(row.recall).toFixed(4) : "-") +
          "</td><td>" +
          (row["f1-score"] != null ? Number(row["f1-score"]).toFixed(4) : "-") +
          "</td><td>" +
          (row.support != null ? String(row.support) : "-") +
          "</td>";
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      frag.appendChild(table);
    }

    if (matrix.length > 0 && labelKeys.length > 0) {
      const sortedLabels = labelKeys.slice().sort();
      const numCols = sortedLabels.length;
      const h4 = document.createElement("h4");
      h4.textContent = "Confusion matrix";
      h4.style.marginTop = "1rem";
      frag.appendChild(h4);
      const cmTable = document.createElement("table");
      cmTable.className = "data-table";
      const cmThead = document.createElement("thead");
      let headerRow = "<tr><th></th>";
      sortedLabels.forEach((l) => {
        headerRow += "<th>" + escapeHtml(l) + "</th>";
      });
      headerRow += "</tr>";
      cmThead.innerHTML = headerRow;
      cmTable.appendChild(cmThead);
      const cmTbody = document.createElement("tbody");
      const numRows = Math.max(matrix.length, numCols);
      for (let i = 0; i < numRows; i++) {
        const tr = document.createElement("tr");
        const rowLabel = sortedLabels[i] != null ? sortedLabels[i] : "";
        let labelCell = "<td><strong>" + escapeHtml(rowLabel) + "</strong></td>";
        const row = matrix[i] || [];
        for (let j = 0; j < numCols; j++) {
          const val = row[j];
          const display =
            val !== undefined && val !== null && val !== ""
              ? String(val)
              : "0";
          labelCell += "<td>" + escapeHtml(display) + "</td>";
        }
        tr.innerHTML = labelCell;
        cmTbody.appendChild(tr);
      }
      cmTable.appendChild(cmTbody);
      frag.appendChild(cmTable);
    }
    return frag;
  }

  function renderRefineReport(report) {
    if (!report || typeof report !== "object") {
      refineReport.classList.add("hidden");
      return;
    }
    refineReport.classList.remove("hidden");
    refineReportContent.innerHTML = "";
    const dl = document.createElement("dl");
    const fields = [
      ["rows_processed", "Rows processed"],
      ["relabels_proposed", "Relabels proposed"],
      ["examples_proposed", "Examples proposed"],
      ["rows_skipped", "Rows skipped"],
      ["errors", "Errors"],
    ];
    fields.forEach(([key, label]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = report[key] != null ? String(report[key]) : "-";
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    refineReportContent.appendChild(dl);
  }

  function renderRefineComparison(metricsBefore, metricsAfter) {
    refineComparison.classList.remove("hidden");
    refineComparisonContent.innerHTML = "";
    const beforeDiv = document.createElement("div");
    beforeDiv.className = "comparison-block";
    const beforeTitle = document.createElement("h4");
    beforeTitle.textContent = "Before";
    beforeDiv.appendChild(beforeTitle);
    beforeDiv.appendChild(buildMetricsDOM(metricsBefore || {}));
    const afterDiv = document.createElement("div");
    afterDiv.className = "comparison-block";
    const afterTitle = document.createElement("h4");
    afterTitle.textContent = "After";
    afterDiv.appendChild(afterTitle);
    afterDiv.appendChild(buildMetricsDOM(metricsAfter || {}));
    refineComparisonContent.appendChild(beforeDiv);
    refineComparisonContent.appendChild(afterDiv);
  }

  function renderRefineDataTable(rows, title) {
    if (!rows || rows.length === 0) return null;
    const wrap = document.createElement("div");
    const h4 = document.createElement("h4");
    h4.textContent = title;
    wrap.appendChild(h4);
    const table = document.createElement("table");
    table.className = "data-table";
    const keys = Object.keys(rows[0]);
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr>" + keys.map((k) => "<th>" + escapeHtml(k) + "</th>").join("") + "</tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const cells = keys.map((k) => {
        const v = row[k];
        const text = v != null ? String(v) : "";
        const short = text.length > 120 ? text.slice(0, 117) + "..." : text;
        return "<td>" + escapeHtml(short) + "</td>";
      });
      tr.innerHTML = cells.join("");
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderRefineTables(proposedRelabels, proposedExamples, trainCandidateSample) {
    refineTables.classList.remove("hidden");
    refineTablesContent.innerHTML = "";
    const tables = [
      [proposedRelabels, "Proposed relabels"],
      [proposedExamples, "Proposed examples"],
      [trainCandidateSample, "Train candidate (sample)"],
    ];
    tables.forEach(([rows, title]) => {
      const block = renderRefineDataTable(rows || [], title);
      if (block) refineTablesContent.appendChild(block);
    });
  }

  function renderRefineResult(result) {
    refineMessage.classList.add("hidden");
    renderRefineReport(result.report);
    renderRefineComparison(result.metrics_before, result.metrics_after);
    renderRefineTables(
      result.proposed_relabels,
      result.proposed_examples,
      result.train_candidate_sample
    );
    if (refinePromoteActions) refinePromoteActions.classList.remove("hidden");
  }

  refineRunBtn.addEventListener("click", async () => {
    if (refineRunBtn.disabled) return;
    setRefineRunning(true);
    try {
      const resp = await fetch("/api/refine", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await resp.json();
      if (!resp.ok) {
        setRefineRunning(false);
        showRefineError(data.detail || data.message || "Start refinement failed");
        return;
      }
      const jobId = data.job_id;
      if (!jobId) {
        setRefineRunning(false);
        showRefineError("No job_id in response");
        return;
      }
      const eventUrl =
        window.location.origin + "/api/refine/events/" + encodeURIComponent(jobId);
      const es = new EventSource(eventUrl);
      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          if (payload.status === "progress") {
            var label = refineProgress.querySelector(".progress-label");
            if (label) label.textContent = payload.detail || "Running...";
            return;
          }
          es.close();
          setRefineRunning(false);
          if (payload.status === "completed" && payload.result) {
            renderRefineResult(payload.result);
          } else if (payload.status === "failed") {
            showRefineError(
              payload.error || "Refinement failed",
              payload.error_detail
            );
          } else {
            showRefineError("Unexpected event: " + (payload.status || "unknown"));
          }
        } catch (err) {
          es.close();
          setRefineRunning(false);
          showRefineError(err.message || "Invalid event data");
        }
      };
      es.onerror = () => {
        es.close();
        setRefineRunning(false);
        showRefineError("Connection to events stream failed");
      };
    } catch (err) {
      setRefineRunning(false);
      showRefineError(err.message || "Network error");
    }
  });

  refinePromoteBtn.addEventListener("click", async () => {
    if (refinePromoteBtn.disabled) return;
    setRefinePromoting(true);
    refineMessage.classList.add("hidden");
    try {
      const resp = await fetch("/api/refine/promote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await resp.json();
      setRefinePromoting(false);
      if (!resp.ok) {
        const errMsg = Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg || d.loc).join("; ")
          : (data.detail || data.message || "Promote failed");
        showRefineError(typeof errMsg === "string" ? errMsg : "Promote failed");
        return;
      }
      if (data.promoted) {
        showRefineMessage(
          data.message +
            " (acc: " +
            (data.acc_before != null ? (data.acc_before * 100).toFixed(2) : "-") +
            "% -> " +
            (data.acc_after != null ? (data.acc_after * 100).toFixed(2) : "-") +
            "%). You may need to restart ai_router to use the new model.",
          "info"
        );
      } else {
        showRefineMessage(data.message || "Metrics did not improve; candidate discarded.", "info");
      }
    } catch (err) {
      setRefinePromoting(false);
      showRefineError(err.message || "Network error");
    }
  });

  if (refineLastBtn) {
    refineLastBtn.addEventListener("click", async () => {
      if (refineLastBtn.disabled) return;
      refineLastBtn.disabled = true;
      refineMessage.classList.add("hidden");
      try {
        const resp = await fetch("/api/refine/last");
        if (resp.status === 404) {
          showRefineMessage("No previous refinement run found.", "info");
          refineReport.classList.add("hidden");
          refineComparison.classList.add("hidden");
          refineTables.classList.add("hidden");
          return;
        }
        if (!resp.ok) {
          showRefineError("Load last run failed: " + resp.status);
          return;
        }
        const result = await resp.json();
        renderRefineResult(result);
      } catch (err) {
        showRefineError(err.message || "Network error");
      } finally {
        refineLastBtn.disabled = false;
      }
    });
  }
})();
