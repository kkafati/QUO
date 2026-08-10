const params = new URLSearchParams(window.location.search);
const cotizacionId = params.get("id");
let lines = [];
let account = null;
let selectedClienteId = null;

function esc(s) { return (s ?? "").toString().replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c])); }
function fmt(n) { return "L. " + (Number(n) || 0).toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function uid() { return Math.random().toString(36).slice(2, 9); }

function blankLine() { return { _key: uid(), cantidad: 1, descripcion: "", precio_unitario: 0 }; }

async function loadAccount() {
  account = await fetch("/api/account").then(r => r.json());
  if (account.logo_data_url) {
    document.getElementById("fheadLogo").src = account.logo_data_url;
    document.getElementById("fheadLogo").style.display = "block";
  }
  document.getElementById("contactList").innerHTML = `
    <div class="contact-row"><span class="contact-icon">☎</span> ${esc(account.phone || "—")}</div>
    <div class="contact-row"><span class="contact-icon">✉</span> ${esc(account.email || "—")}</div>
    <div class="contact-row"><span class="contact-icon" style="font-size:13px">⌂</span> ${esc(account.address || "—")}</div>
    <div class="contact-row"><span class="contact-icon">🌐</span> ${esc(account.website || "—")}</div>
  `;
  // The globe emoji above renders as a fixed-color glyph on most systems and
  // ignores CSS `color`. Templates can opt into a real SVG globe icon via
  // window.GLOBE_ICON_SVG; otherwise fall back to plain "WWW" text (which
  // does respect color: white, unlike the emoji).
  document.querySelectorAll(".contact-icon").forEach(el => {
    if (el.textContent.trim() === "🌐") {
      el.innerHTML = window.GLOBE_ICON_SVG || '<span style="font-size:0.55em;letter-spacing:-0.05em">WWW</span>';
    }
  });
  document.getElementById("companyRtnValue").textContent = account.tax_id || "— sin configurar —";
}

function renderLines() {
  document.getElementById("linesBody").innerHTML = lines.map(ln => `
    <tr data-row="${ln._key}">
      <td><input class="cantidad" type="number" step="1" value="${ln.cantidad}"></td>
      <td style="position:relative">
        <textarea class="descripcion" rows="1" placeholder="Descripción del artículo/servicio">${esc(ln.descripcion)}</textarea>
        <div class="line-suggest no-print" hidden></div>
      </td>
      <td class="num"><input class="precio" type="number" step="0.01" value="${ln.precio_unitario}"></td>
      <td class="num total-cell">${fmt((ln.cantidad || 0) * (ln.precio_unitario || 0))}</td>
      <td class="no-print"><button type="button" class="remove-line-btn">×</button></td>
    </tr>
  `).join("");

  document.querySelectorAll("#linesBody [data-row]").forEach(row => {
    const key = row.dataset.row;
    const line = lines.find(l => l._key === key);
    const descEl = row.querySelector(".descripcion");

    autoGrowTextarea(descEl);

    row.querySelector(".cantidad").addEventListener("input", (e) => {
      line.cantidad = parseFloat(e.target.value) || 0;
      row.querySelector(".total-cell").textContent = fmt((line.cantidad || 0) * (line.precio_unitario || 0));
      updateTotals();
    });

    descEl.addEventListener("input", (e) => {
      line.descripcion = e.target.value;
      autoGrowTextarea(e.target);
      clearTimeout(clientSearchTimer);
      const query = e.target.value.trim();
      clientSearchTimer = setTimeout(() => searchFichasForLine(query, row, key), 200);
    });
    descEl.addEventListener("blur", () => {
      setTimeout(() => hideSuggestBox(row.querySelector(".line-suggest"), true), 150);
    });

    row.querySelector(".precio").addEventListener("input", (e) => {
      line.precio_unitario = parseFloat(e.target.value) || 0;
      row.querySelector(".total-cell").textContent = fmt((line.cantidad || 0) * (line.precio_unitario || 0));
      updateTotals();
    });
    row.querySelector(".remove-line-btn").addEventListener("click", () => {
      lines = lines.filter(l => l._key !== key);
      renderLines(); updateTotals();
    });
  });
}

function setMoneyDisplay(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.parentElement && el.parentElement.classList.contains("tvalue-wrap")) {
    el.textContent = (Number(value) || 0).toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } else {
    el.textContent = fmt(value);
  }
}

function updateTotals() {
  const subtotal = lines.reduce((s, l) => s + (l.cantidad || 0) * (l.precio_unitario || 0), 0);
  const descuentos = parseFloat(document.getElementById("descuentos").value) || 0;
  const exonerado = parseFloat(document.getElementById("importe_exonerado").value) || 0;
  const exento = parseFloat(document.getElementById("importe_exento").value) || 0;
  const gravado18 = document.getElementById("gravado_18_pct").checked;

  const base = Math.max(0, subtotal - descuentos - exonerado - exento);
  const gravado15amt = gravado18 ? 0 : base;
  const gravado18amt = gravado18 ? base : 0;
  const isv15 = gravado18 ? 0 : round2(base * 0.15);
  const isv18 = gravado18 ? round2(base * 0.18) : 0;
  const total = round2(subtotal - descuentos + isv15 + isv18);

  setMoneyDisplay("t_subtotal", subtotal);
  setMoneyDisplay("t_gravado15", gravado15amt);
  setMoneyDisplay("t_gravado18", gravado18amt);
  setMoneyDisplay("t_isv15", isv15);
  setMoneyDisplay("t_isv18", isv18);
  setMoneyDisplay("t_total", total);
}

function round2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }

function formatNumero(n) { return String(n || 0).padStart(6, "0"); }

async function loadCotizacion() {
  if (!cotizacionId) {
    lines = [blankLine()];
    document.getElementById("term-contado").checked = true;
    document.getElementById("fecha").value = new Date().toISOString().slice(0, 10);
    renderLines();
    updateTotals();
    return;
  }
  const cot = await fetch(`/api/cotizaciones-clasica/${cotizacionId}`).then(r => r.json());
  document.getElementById("facturaNumero").textContent = formatNumero(cot.numero);
  document.getElementById("cliente_nombre").value = cot.cliente_nombre || "";
  document.getElementById("cliente_rtn").value = cot.cliente_rtn || "";
  selectedClienteId = cot.cliente_id || null;
  document.getElementById("fecha").value = cot.fecha || "";
  document.getElementById(cot.termino_pago === "credito" ? "term-credito" : "term-contado").checked = true;
  document.getElementById("descuentos").value = cot.descuentos || 0;
  document.getElementById("importe_exonerado").value = cot.importe_exonerado || 0;
  document.getElementById("importe_exento").value = cot.importe_exento || 0;
  document.getElementById("gravado_18_pct").checked = (cot.importe_gravado_18 || 0) > 0;
  const notaEl = document.getElementById("nota");
  notaEl.value = cot.nota || "";
  autoGrowTextarea(notaEl);
  lines = cot.lines.map(l => ({ _key: uid(), cantidad: l.cantidad, descripcion: l.descripcion, precio_unitario: l.precio_unitario }));
  if (lines.length === 0) lines = [blankLine()];
  renderLines();
  updateTotals();
  document.getElementById("btnEliminar").style.display = "inline-block";
  document.getElementById("btnConvertir").style.display = "inline-block";
}

// ---- Cliente search/autocomplete (both name and RTN fields search the same client list) ----
let clientSearchTimer = null;

function selectClient(c) {
  document.getElementById("cliente_nombre").value = c.nombre;
  document.getElementById("cliente_rtn").value = c.rtn || "";
  selectedClienteId = c.id;
  hideSuggestBox("clienteSuggestBox");
  hideSuggestBox("rtnSuggestBox");
}

function hideSuggestBox(boxOrId) {
  const box = typeof boxOrId === "string" ? document.getElementById(boxOrId) : boxOrId;
  if (box) { box.hidden = true; box.innerHTML = ""; }
}

function renderSuggestBox(boxId, results, query) {
  const box = document.getElementById(boxId);
  if (!box) return;
  if (!query) { box.hidden = true; return; }
  if (results.length === 0) {
    box.innerHTML = '<div class="cs-empty">Sin coincidencias — se creará un cliente nuevo al guardar.</div>';
  } else {
    box.innerHTML = results.map(c => `
      <div class="cs-item" data-id="${c.id}">
        ${esc(c.nombre)}<br><span class="cs-sub">${esc(c.rtn || "Sin RTN")}</span>
      </div>
    `).join("");
    box.querySelectorAll(".cs-item").forEach(el => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault(); // fire before the input's blur hides the box
        const c = results.find(r => r.id == el.dataset.id);
        if (c) selectClient(c);
      });
    });
  }
  box.hidden = false;
}

function autoGrowTextarea(el) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
}

function renderFichaSuggestBox(box, results, query) {
  if (!box) return;
  if (!query) { box.hidden = true; return; }
  if (results.length === 0) {
    box.innerHTML = '<div class="cs-empty">Sin coincidencias — se guardará como texto libre.</div>';
  } else {
    box.innerHTML = results.map(f => `
      <div class="cs-item" data-id="${f.id}">
        ${esc(f.code)} — ${esc(f.description || f.name)}<br>
        <span class="cs-sub">${esc(f.name)} · ${fmt(f.total_cost)}</span>
      </div>
    `).join("");
    box.querySelectorAll(".cs-item").forEach(el => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const f = results.find(r => r.id == el.dataset.id);
        if (f) selectFichaForLine(f, box);
      });
    });
  }
  box.hidden = false;
}

function selectFichaForLine(ficha, box) {
  const row = box.closest("[data-row]");
  if (!row) return;
  const key = row.dataset.row;
  const line = lines.find(l => l._key === key);
  const descEl = row.querySelector(".descripcion");
  const precioEl = row.querySelector(".precio");
  line.descripcion = ficha.description || ficha.name || "";
  line.precio_unitario = ficha.total_cost || 0;
  descEl.value = line.descripcion;
  precioEl.value = line.precio_unitario;
  autoGrowTextarea(descEl);
  row.querySelector(".total-cell").textContent = fmt((line.cantidad || 0) * (line.precio_unitario || 0));
  updateTotals();
  hideSuggestBox(box);
}

async function searchFichasForLine(query, row, key) {
  const box = row.querySelector(".line-suggest");
  if (!query) { hideSuggestBox(box); return; }
  const results = await fetch(`/api/costcards?q=${encodeURIComponent(query)}`).then(r => r.json()).catch(() => []);
  renderFichaSuggestBox(box, results, query);
}

async function searchClients(query, boxId) {
  if (!query) { hideSuggestBox(boxId); return; }
  const results = await fetch(`/api/clientes?q=${encodeURIComponent(query)}`).then(r => r.json()).catch(() => []);
  renderSuggestBox(boxId, results, query);
}

function wireClientSearchInput(inputId, boxId) {
  const input = document.getElementById(inputId);
  if (!input) return;
  input.addEventListener("input", () => {
    selectedClienteId = null; // typing again after a selection means it may no longer match
    clearTimeout(clientSearchTimer);
    const query = input.value.trim();
    clientSearchTimer = setTimeout(() => searchClients(query, boxId), 200);
  });
  input.addEventListener("blur", () => {
    setTimeout(() => hideSuggestBox(boxId), 150); // delay so a click on a suggestion still registers
  });
  input.addEventListener("focus", () => {
    if (input.value.trim()) searchClients(input.value.trim(), boxId);
  });
}

wireClientSearchInput("cliente_nombre", "clienteSuggestBox");
wireClientSearchInput("cliente_rtn", "rtnSuggestBox");

document.getElementById("btnAddLine").addEventListener("click", () => { lines.push(blankLine()); renderLines(); });
["descuentos","importe_exonerado","importe_exento","gravado_18_pct"].forEach(id => {
  document.getElementById(id).addEventListener("input", updateTotals);
  document.getElementById(id).addEventListener("change", updateTotals);
});

const notaField = document.getElementById("nota");
notaField.addEventListener("input", () => autoGrowTextarea(notaField));

document.getElementById("btnGuardar").addEventListener("click", async () => {
  const statusMsg = document.getElementById("statusMsg");
  statusMsg.textContent = "Guardando..."; statusMsg.className = "status";

  const body = {
    cliente_nombre: document.getElementById("cliente_nombre").value,
    cliente_rtn: document.getElementById("cliente_rtn").value,
    cliente_id: selectedClienteId,
    fecha: document.getElementById("fecha").value,
    termino_pago: document.getElementById("term-credito").checked ? "credito" : "contado",
    nota: document.getElementById("nota").value,
    descuentos: document.getElementById("descuentos").value,
    importe_exonerado: document.getElementById("importe_exonerado").value,
    importe_exento: document.getElementById("importe_exento").value,
    gravado_18_pct: document.getElementById("gravado_18_pct").checked,
    lines: lines.map(l => ({ cantidad: l.cantidad, descripcion: l.descripcion, precio_unitario: l.precio_unitario })),
  };

  try {
    const url = cotizacionId ? `/api/cotizaciones-clasica/${cotizacionId}` : "/api/cotizaciones-clasica";
    const method = cotizacionId ? "PUT" : "POST";
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) {
      statusMsg.textContent = data.error || "Error al guardar.";
      statusMsg.className = "status error";
      return;
    }
    statusMsg.textContent = "Guardado ✓"; statusMsg.className = "status ok";
    if (!cotizacionId) {
      window.location.href = `/cotizacion-clasica/ver/?id=${data.id}`;
    } else {
      document.getElementById("facturaNumero").textContent = formatNumero(data.numero);
      setMoneyDisplay("t_subtotal", data.subtotal);
      setMoneyDisplay("t_gravado15", data.importe_gravado_15);
      setMoneyDisplay("t_gravado18", data.importe_gravado_18);
      setMoneyDisplay("t_isv15", data.isv_15);
      setMoneyDisplay("t_isv18", data.isv_18);
      setMoneyDisplay("t_total", data.total_a_pagar);
    }
  } catch (err) {
    statusMsg.textContent = "Error de conexión."; statusMsg.className = "status error";
  }
});

document.getElementById("btnImprimir").addEventListener("click", () => {
  if (cotizacionId) {
    window.open(`/api/cotizaciones-clasica/${cotizacionId}/pdf`, "_blank");
  } else {
    alert("Guarda la cotización primero para generar el PDF.");
  }
});

document.getElementById("btnEliminar").addEventListener("click", async () => {
  const numero = document.getElementById("facturaNumero").textContent;
  if (!confirm(`¿Mover la cotización "${numero}" a la papelera?`)) return;
  await fetch(`/api/cotizaciones-clasica/${cotizacionId}`, { method: "DELETE" });
  window.location.href = "/cotizaciones/";
});

document.getElementById("btnConvertir").addEventListener("click", async () => {
  if (!cotizacionId) return;
  if (!confirm("¿Convertir esta cotización en una factura? Se creará una nueva factura con estos mismos datos.")) return;
  const statusMsg = document.getElementById("statusMsg");
  try {
    const res = await fetch(`/api/cotizaciones-clasica/${cotizacionId}/convertir-a-factura`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      statusMsg.textContent = data.error || "No se pudo convertir a factura.";
      statusMsg.className = "status error";
      return;
    }
    window.location.href = `/facturacion/ver/?id=${data.id}`;
  } catch (err) {
    statusMsg.textContent = "Error de conexión."; statusMsg.className = "status error";
  }
});

(async () => {
  await loadAccount();
  await loadCotizacion();
})();
