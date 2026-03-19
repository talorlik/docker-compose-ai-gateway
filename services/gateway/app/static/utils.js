/**
 * Shared utilities for the AI Router Gateway frontend.
 */

/* exported escapeHtml, buildMetricsDOM */
/* eslint-disable no-unused-vars */

function escapeHtml(s) {
  if (typeof s !== "string") return "";
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
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
