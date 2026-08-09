const params = new URLSearchParams(window.location.search);
const invoiceId = params.get("id");
let lines = [];
let account = null;
let selectedClienteId = null;
let currentInvoiceTemplate = null;

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
  document.getElementById("caiValue").textContent = account.cai || "— sin configurar —";
  document.getElementById("footRtn").textContent = account.tax_id || "—";
  document.getElementById("footFechaLimite").textContent = account.cai_fecha_limite || "—";
  document.getElementById("footRango").textContent =
    (account.rango_autorizado_desde && account.rango_autorizado_hasta)
      ? `${account.rango_autorizado_desde} al ${account.rango_autorizado_hasta}`
      : "—";
}

function renderLines() {
  const compact = window.LINE_ROW_TEMPLATE === "compact";

  document.getElementById("linesBody").innerHTML = lines.map(ln => compact ? `
    <div class="line-row" data-row="${ln._key}">
      <div class="line-desc-row" style="position:relative">
        <textarea class="descripcion" rows="1" placeholder="Descripción">${esc(ln.descripcion)}</textarea>
        <div class="line-suggest no-print" hidden></div>
        <button type="button" class="remove-line-btn no-print">×</button>
      </div>
      <div class="line-meta-row">
        <input class="cantidad" type="number" step="1" value="${ln.cantidad}"> x
        <input class="precio" type="number" step="0.01" value="${ln.precio_unitario}">
        <span class="total-cell">${fmt((ln.cantidad || 0) * (ln.precio_unitario || 0))}</span>
      </div>
    </div>
  ` : `
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
  document.getElementById("totalEnLetras").textContent = numeroALetrasLocal(total);
}

function round2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }

// Lightweight client-side mirror just for live preview; the server computes the authoritative version on save.
const UNI = ["", "UNO","DOS","TRES","CUATRO","CINCO","SEIS","SIETE","OCHO","NUEVE"];
const DIEZ = ["DIEZ","ONCE","DOCE","TRECE","CATORCE","QUINCE","DIECISEIS","DIECISIETE","DIECIOCHO","DIECINUEVE"];
const DEC = ["","","VEINTE","TREINTA","CUARENTA","CINCUENTA","SESENTA","SETENTA","OCHENTA","NOVENTA"];
const CEN = ["","CIENTO","DOSCIENTOS","TRESCIENTOS","CUATROCIENTOS","QUINIENTOS","SEISCIENTOS","SETECIENTOS","OCHOCIENTOS","NOVECIENTOS"];
function tresDigitos(n) {
  if (n === 0) return "";
  if (n === 100) return "CIEN";
  const c = Math.floor(n / 100), resto = n % 100;
  let partes = [];
  if (c) partes.push(CEN[c]);
  if (resto) {
    if (resto < 10) partes.push(UNI[resto]);
    else if (resto < 20) partes.push(DIEZ[resto - 10]);
    else {
      const d = Math.floor(resto / 10), u = resto % 10;
      if (d === 2 && u > 0) partes.push("VEINTI" + UNI[u]);
      else partes.push(u ? DEC[d] + " Y " + UNI[u] : DEC[d]);
    }
  }
  return partes.join(" ");
}
function enteroALetras(n) {
  if (n === 0) return "CERO";
  const millones = Math.floor(n / 1000000), resto = n % 1000000;
  const miles = Math.floor(resto / 1000), cientos = resto % 1000;
  let partes = [];
  if (millones) partes.push(millones === 1 ? "UN MILLON" : tresDigitos(millones) + " MILLONES");
  if (miles) partes.push(miles === 1 ? "MIL" : tresDigitos(miles) + " MIL");
  if (cientos) partes.push(tresDigitos(cientos));
  return partes.join(" ");
}
function numeroALetrasLocal(monto) {
  monto = round2(monto);
  const entero = Math.floor(monto);
  const centavos = Math.round((monto - entero) * 100);
  return `${enteroALetras(entero)} LEMPIRAS CON ${String(centavos).padStart(2,"0")}/100`;
}

async function loadInvoice() {
  if (!invoiceId) {
    currentInvoiceTemplate = (account && account.default_invoice_template) || "clasica";
    lines = [blankLine()];
    document.getElementById("term-contado").checked = true;
    document.getElementById("fecha").value = new Date().toISOString().slice(0, 10);
    renderLines();
    updateTotals();
    return;
  }
  const inv = await fetch(`/api/invoices/${invoiceId}`).then(r => r.json());
  currentInvoiceTemplate = inv.template || "clasica";
  document.getElementById("facturaNumero").textContent = inv.numero;
  document.getElementById("cliente_nombre").value = inv.cliente_nombre || "";
  document.getElementById("cliente_rtn").value = inv.cliente_rtn || "";
  selectedClienteId = inv.cliente_id || null;
  document.getElementById("fecha").value = inv.fecha || "";
  document.getElementById(inv.termino_pago === "credito" ? "term-credito" : "term-contado").checked = true;
  document.getElementById("descuentos").value = inv.descuentos || 0;
  document.getElementById("importe_exonerado").value = inv.importe_exonerado || 0;
  document.getElementById("importe_exento").value = inv.importe_exento || 0;
  document.getElementById("gravado_18_pct").checked = (inv.importe_gravado_18 || 0) > 0;
  document.getElementById("orden_compra_exenta").value = inv.orden_compra_exenta || "";
  document.getElementById("constancia_registro_exonerado").value = inv.constancia_registro_exonerado || "";
  document.getElementById("registro_sag").value = inv.registro_sag || "";
  const estadoEl = document.getElementById("estadoSwitcher");
  if (estadoEl) { estadoEl.value = inv.estado || "Falta Pago"; estadoEl.disabled = false; }
  lines = inv.lines.map(l => ({ _key: uid(), cantidad: l.cantidad, descripcion: l.descripcion, precio_unitario: l.precio_unitario }));
  if (lines.length === 0) lines = [blankLine()];
  renderLines();
  updateTotals();
  document.getElementById("btnEliminar").style.display = "inline-block";
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

document.getElementById("btnGuardar").addEventListener("click", async () => {
  const statusMsg = document.getElementById("statusMsg");
  statusMsg.textContent = "Guardando..."; statusMsg.className = "status";

  const body = {
    cliente_nombre: document.getElementById("cliente_nombre").value,
    cliente_rtn: document.getElementById("cliente_rtn").value,
    cliente_id: selectedClienteId,
    fecha: document.getElementById("fecha").value,
    termino_pago: document.getElementById("term-credito").checked ? "credito" : "contado",
    estado: document.getElementById("estadoSwitcher") ? document.getElementById("estadoSwitcher").value : undefined,
    descuentos: document.getElementById("descuentos").value,
    importe_exonerado: document.getElementById("importe_exonerado").value,
    importe_exento: document.getElementById("importe_exento").value,
    gravado_18_pct: document.getElementById("gravado_18_pct").checked,
    orden_compra_exenta: document.getElementById("orden_compra_exenta").value,
    constancia_registro_exonerado: document.getElementById("constancia_registro_exonerado").value,
    registro_sag: document.getElementById("registro_sag").value,
    lines: lines.map(l => ({ cantidad: l.cantidad, descripcion: l.descripcion, precio_unitario: l.precio_unitario })),
  };

  try {
    const url = invoiceId ? `/api/invoices/${invoiceId}` : "/api/invoices";
    const method = invoiceId ? "PUT" : "POST";
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) {
      statusMsg.textContent = data.error || "Error al guardar.";
      statusMsg.className = "status error";
      return;
    }
    statusMsg.textContent = "Guardado ✓"; statusMsg.className = "status ok";
    if (!invoiceId) {
      window.location.href = `/facturacion/ver/?id=${data.id}`;
    } else {
      document.getElementById("facturaNumero").textContent = data.numero;
      setMoneyDisplay("t_subtotal", data.subtotal);
      setMoneyDisplay("t_gravado15", data.importe_gravado_15);
      setMoneyDisplay("t_gravado18", data.importe_gravado_18);
      setMoneyDisplay("t_isv15", data.isv_15);
      setMoneyDisplay("t_isv18", data.isv_18);
      setMoneyDisplay("t_total", data.total_a_pagar);
      document.getElementById("totalEnLetras").textContent = data.total_en_letras;
    }
  } catch (err) {
    statusMsg.textContent = "Error de conexión."; statusMsg.className = "status error";
  }
});

document.getElementById("btnImprimir").addEventListener("click", () => {
  if (currentInvoiceTemplate === "clasica" && invoiceId) {
    window.open(`/api/invoices/${invoiceId}/pdf`, "_blank");
  } else if (currentInvoiceTemplate === "clasica" && !invoiceId) {
    alert("Guarda la factura primero para generar el PDF.");
  } else {
    window.print();
  }
});

document.getElementById("btnEliminar").addEventListener("click", async () => {
  const numero = document.getElementById("facturaNumero").textContent;
  if (!confirm(`¿Mover la factura "${numero}" a la papelera?`)) return;
  await fetch(`/api/invoices/${invoiceId}`, { method: "DELETE" });
  window.location.href = "/facturacion/";
});

(async () => {
  await loadAccount();
  await loadInvoice();
})();

// ---- Estado (payment status) switcher ----
const estadoSwitcher = document.getElementById("estadoSwitcher");
if (estadoSwitcher) {
  if (!invoiceId) estadoSwitcher.disabled = true; // nothing to set yet on an unsaved invoice
  estadoSwitcher.addEventListener("change", async () => {
    if (!invoiceId) return;
    await fetch(`/api/invoices/${invoiceId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estado: estadoSwitcher.value }),
    });
  });
}
