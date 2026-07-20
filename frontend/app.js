// ============================================================================
// Helpers
// ============================================================================

const api = {
  get: (url) => fetch(url).then(r => r.json()),
  post: (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  put: (url, body) => fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  del: (url) => fetch(url, { method: "DELETE" }),
};

function fmt(n) {
  n = Number(n) || 0;
  return "L " + n.toLocaleString("es-HN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function esc(s) {
  return (s ?? "").toString().replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function uid() { return Math.random().toString(36).slice(2, 9); }

// ============================================================================
// Navigation
// ============================================================================

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById("view-" + view).classList.add("active");
    if (view === "catalogs") loadCatalog();
    if (view === "costcards") loadCostCardList();
    if (view === "quotes") loadQuoteList();
  });
});

function showModal(html) {
  const backdrop = document.getElementById("modal-backdrop");
  const box = document.getElementById("modal-box");
  box.innerHTML = html;
  backdrop.hidden = false;
}
function hideModal() {
  document.getElementById("modal-backdrop").hidden = true;
}
document.getElementById("modal-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "modal-backdrop") hideModal();
});

// ============================================================================
// CATALOGS
// ============================================================================

let currentCatalogCat = "material";
let catalogCache = { material: [], labor: [], tool: [] };
const CAT_LABELS = { material: "Materiales", labor: "Mano de Obra", tool: "Herramientas" };

document.querySelectorAll("#catalog-tabs .tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#catalog-tabs .tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentCatalogCat = tab.dataset.cat;
    loadCatalog();
  });
});

document.getElementById("catalog-search").addEventListener("input", (e) => {
  renderCatalogTable(e.target.value.trim().toLowerCase());
});

document.getElementById("btn-new-catalog-item").addEventListener("click", () => openCatalogForm(null));

async function loadCatalog() {
  const items = await api.get(`/api/catalog/${currentCatalogCat}`);
  catalogCache[currentCatalogCat] = items;
  renderCatalogTable("");
}

function renderCatalogTable(filter) {
  const items = catalogCache[currentCatalogCat].filter(i =>
    !filter || i.code.toLowerCase().includes(filter) || i.description.toLowerCase().includes(filter));
  const tbody = document.getElementById("catalog-tbody");
  document.getElementById("catalog-empty").hidden = items.length > 0;
  tbody.innerHTML = items.map(i => `
    <tr>
      <td class="mono">${esc(i.code)}</td>
      <td>${esc(i.description)}</td>
      <td>${esc(i.unit)}</td>
      <td class="num">${fmt(i.unit_price)}</td>
      <td>${esc(i.updated_at || "—")}</td>
      <td class="col-actions">
        <button class="btn btn-sm btn-ghost" data-edit="${i.id}">Editar</button>
        <button class="btn btn-sm btn-danger" data-del="${i.id}">×</button>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => {
    const item = catalogCache[currentCatalogCat].find(x => x.id == b.dataset.edit);
    openCatalogForm(item);
  }));
  tbody.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("¿Eliminar este artículo del catálogo?")) return;
    await api.del(`/api/catalog/${currentCatalogCat}/${b.dataset.del}`);
    loadCatalog();
  }));
}

function openCatalogForm(item) {
  const isNew = !item;
  showModal(`
    <h2>${isNew ? "Nuevo" : "Editar"} — ${CAT_LABELS[currentCatalogCat]}</h2>
    <div class="field"><label>Código</label><input id="mf-code" value="${esc(item?.code || "")}" placeholder="Ej. A-I-2"></div>
    <div class="field"><label>Descripción</label><input id="mf-desc" value="${esc(item?.description || "")}" placeholder="Descripción del artículo"></div>
    <div class="field"><label>Unidad</label><input id="mf-unit" value="${esc(item?.unit || "")}" placeholder="Unidad, Metros, Hora…"></div>
    <div class="field"><label>Precio unitario (L)</label><input id="mf-price" type="number" step="0.01" value="${item?.unit_price ?? ""}"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="mf-cancel">Cancelar</button>
      <button class="btn btn-primary" id="mf-save">Guardar</button>
    </div>
  `);
  document.getElementById("mf-cancel").addEventListener("click", hideModal);
  document.getElementById("mf-save").addEventListener("click", async () => {
    const body = {
      code: document.getElementById("mf-code").value,
      description: document.getElementById("mf-desc").value,
      unit: document.getElementById("mf-unit").value,
      unit_price: document.getElementById("mf-price").value,
    };
    if (!body.code || !body.description) { alert("Código y descripción son requeridos."); return; }
    if (isNew) await api.post(`/api/catalog/${currentCatalogCat}`, body);
    else await api.put(`/api/catalog/${currentCatalogCat}/${item.id}`, body);
    hideModal();
    loadCatalog();
  });
}

// ============================================================================
// COST CARDS (Fichas de Costo)
// ============================================================================

let costCardsCache = [];
let editingCard = null; // holds working copy while editing

document.getElementById("costcard-search").addEventListener("input", (e) => {
  renderCostCardGrid(e.target.value.trim().toLowerCase());
});
document.getElementById("btn-new-costcard").addEventListener("click", () => openFichaEditor(null));

async function loadCostCardList() {
  costCardsCache = await api.get("/api/costcards");
  document.getElementById("costcard-editor-panel").classList.add("hidden");
  document.getElementById("costcards-list-panel").classList.remove("hidden");
  renderCostCardGrid("");
}

function renderCostCardGrid(filter) {
  const items = costCardsCache.filter(c =>
    !filter || c.code.toLowerCase().includes(filter) || c.name.toLowerCase().includes(filter));
  const grid = document.getElementById("costcard-grid");
  document.getElementById("costcard-empty").hidden = items.length > 0;
  grid.innerHTML = items.map(c => `
    <div class="stamp-card" data-open="${c.id}">
      <div class="stamp-badge">${esc(c.code)}</div>
      <h3>${esc(c.name)}</h3>
      <div class="stamp-meta">${esc(c.unit || "—")} · ${c.materials.length + c.labor.length + c.tools.length} insumos</div>
      <div class="stamp-total"><span class="lbl">Costo total unitario</span>${fmt(c.total_cost)}</div>
    </div>
  `).join("");
  grid.querySelectorAll("[data-open]").forEach(el => el.addEventListener("click", async () => {
    const card = await api.get(`/api/costcards/${el.dataset.open}`);
    openFichaEditor(card);
  }));
}

function blankItem(category) {
  return { _key: uid(), category, code: "", description: "", unit: "", rendimiento: 0, desperdicio_pct: 0, unit_price: 0 };
}

function openFichaEditor(card) {
  editingCard = card ? JSON.parse(JSON.stringify(card)) : {
    id: null, code: "", name: "", unit: "",
    admin_pct: 10, utilidad_pct: 15,
    materials: [], labor: [], tools: [],
  };
  editingCard.materials.forEach(i => i._key = uid());
  editingCard.labor.forEach(i => i._key = uid());
  editingCard.tools.forEach(i => i._key = uid());

  document.getElementById("costcards-list-panel").classList.add("hidden");
  document.getElementById("costcard-editor-panel").classList.remove("hidden");
  renderFichaEditor();
}

function fichaSectionHtml(category, label, items) {
  const rows = items.map(it => fichaRowHtml(category, it)).join("");
  return `
    <div class="section-title">${label}</div>
    <table class="line-table" data-section="${category}">
      <thead><tr>
        <th style="width:22%">Del catálogo</th>
        <th>Código</th><th>Descripción</th><th style="width:70px">Unidad</th>
        <th style="width:90px">Rendim.</th><th style="width:90px">Desp. %</th>
        <th style="width:100px">P.Unit</th><th style="width:100px">Subtotal</th><th style="width:100px">Total</th><th style="width:36px"></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <button class="add-row-btn" data-add="${category}">+ Agregar línea de ${label.toLowerCase()}</button>
  `;
}

function catalogOptionsHtml(category, selectedCode) {
  const list = catalogCache[category] || [];
  const opts = list.map(i => `<option value="${i.id}" ${i.code === selectedCode ? "selected" : ""}>${esc(i.code)} — ${esc(i.description)}</option>`).join("");
  return `<option value="">— manual —</option>${opts}`;
}

function fichaRowHtml(category, it) {
  const subtotal = (it.rendimiento || 0) * (it.unit_price || 0);
  const total = subtotal * (1 + (it.desperdicio_pct || 0) / 100);
  return `
    <tr data-row="${it._key}">
      <td><select class="picker">${catalogOptionsHtml(category, it.code)}</select></td>
      <td><input class="f-code" value="${esc(it.code)}"></td>
      <td><input class="f-desc" value="${esc(it.description)}"></td>
      <td><input class="f-unit" value="${esc(it.unit)}"></td>
      <td><input class="f-rend" type="number" step="0.0001" value="${it.rendimiento}"></td>
      <td><input class="f-desp" type="number" step="0.01" value="${it.desperdicio_pct}"></td>
      <td><input class="f-price" type="number" step="0.01" value="${it.unit_price}"></td>
      <td class="num-cell f-subtotal">${fmt(subtotal)}</td>
      <td class="num-cell f-total">${fmt(total)}</td>
      <td><button class="btn btn-sm btn-danger remove-row">×</button></td>
    </tr>
  `;
}

async function ensureCatalogsLoaded() {
  for (const cat of ["material", "labor", "tool"]) {
    if (!catalogCache[cat] || catalogCache[cat].length === 0) {
      catalogCache[cat] = await api.get(`/api/catalog/${cat}`);
    }
  }
}

async function renderFichaEditor() {
  await ensureCatalogsLoaded();
  const c = editingCard;
  const el = document.getElementById("ficha-editor");
  el.innerHTML = `
    <div class="editor-head">
      <div class="editor-fields">
        <div class="field narrow"><label>Código</label><input id="fc-code" value="${esc(c.code)}" placeholder="001"></div>
        <div class="field"><label>Actividad</label><input id="fc-name" value="${esc(c.name)}" placeholder="Nombre de la actividad" style="min-width:260px"></div>
        <div class="field"><label>Unidad de medida</label><input id="fc-unit" value="${esc(c.unit)}" placeholder="Unidad, Metro…"></div>
        <div class="field narrow"><label>Gastos admin. %</label><input id="fc-admin" type="number" step="0.01" value="${c.admin_pct}"></div>
        <div class="field narrow"><label>Utilidad %</label><input id="fc-util" type="number" step="0.01" value="${c.utilidad_pct}"></div>
      </div>
    </div>

    ${fichaSectionHtml("material", "Materiales", c.materials)}
    ${fichaSectionHtml("labor", "Mano de Obra", c.labor)}
    ${fichaSectionHtml("tool", "Herramientas", c.tools)}

    <div class="totals-box" id="ficha-totals"></div>

    <div class="editor-actions">
      <button class="btn btn-primary" id="fc-save">Guardar Ficha</button>
      <button class="btn btn-ghost" id="fc-cancel">Volver a la lista</button>
      ${c.id ? '<button class="btn btn-danger" id="fc-delete">Eliminar Ficha</button>' : ""}
    </div>
  `;

  bindFichaEvents();
  updateFichaTotals();
}

function bindFichaEvents() {
  const el = document.getElementById("ficha-editor");

  el.querySelectorAll(".add-row-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const cat = btn.dataset.add;
      const key = cat === "material" ? "materials" : cat === "labor" ? "labor" : "tools";
      editingCard[key].push(blankItem(cat));
      renderFichaEditor();
    });
  });

  el.querySelectorAll("table[data-section]").forEach(table => {
    const cat = table.dataset.section;
    const key = cat === "material" ? "materials" : cat === "labor" ? "labor" : "tools";

    table.querySelectorAll(".remove-row").forEach(btn => {
      btn.addEventListener("click", () => {
        const rowKey = btn.closest("tr").dataset.row;
        editingCard[key] = editingCard[key].filter(i => i._key !== rowKey);
        renderFichaEditor();
      });
    });

    table.querySelectorAll(".picker").forEach(sel => {
      sel.addEventListener("change", () => {
        const rowKey = sel.closest("tr").dataset.row;
        const item = editingCard[key].find(i => i._key === rowKey);
        const catItem = (catalogCache[cat] || []).find(x => x.id == sel.value);
        if (catItem) {
          item.code = catItem.code;
          item.description = catItem.description;
          item.unit = catItem.unit;
          item.unit_price = catItem.unit_price;
        }
        renderFichaEditor();
      });
    });

    table.querySelectorAll("tbody tr").forEach(tr => {
      const rowKey = tr.dataset.row;
      const item = editingCard[key].find(i => i._key === rowKey);
      const bind = (cls, field, isNum) => {
        const input = tr.querySelector(cls);
        input.addEventListener("input", () => {
          item[field] = isNum ? (parseFloat(input.value) || 0) : input.value;
          updateRowCalc(tr, item);
          updateFichaTotals();
        });
      };
      bind(".f-code", "code", false);
      bind(".f-desc", "description", false);
      bind(".f-unit", "unit", false);
      bind(".f-rend", "rendimiento", true);
      bind(".f-desp", "desperdicio_pct", true);
      bind(".f-price", "unit_price", true);
    });
  });

  document.getElementById("fc-cancel").addEventListener("click", loadCostCardList);
  document.getElementById("fc-save").addEventListener("click", saveFicha);
  const delBtn = document.getElementById("fc-delete");
  if (delBtn) delBtn.addEventListener("click", async () => {
    if (!confirm("¿Eliminar esta ficha de costo? También se quitará de cotizaciones que la usen.")) return;
    await api.del(`/api/costcards/${editingCard.id}`);
    loadCostCardList();
  });
}

function updateRowCalc(tr, item) {
  const subtotal = (item.rendimiento || 0) * (item.unit_price || 0);
  const total = subtotal * (1 + (item.desperdicio_pct || 0) / 100);
  tr.querySelector(".f-subtotal").textContent = fmt(subtotal);
  tr.querySelector(".f-total").textContent = fmt(total);
}

function computeFichaTotalsLocal() {
  const c = editingCard;
  const sum = (arr) => arr.reduce((s, it) => {
    const subtotal = (it.rendimiento || 0) * (it.unit_price || 0);
    const total = subtotal * (1 + (it.desperdicio_pct || 0) / 100);
    return s + total;
  }, 0);
  const totalMaterials = sum(c.materials);
  const totalLabor = sum(c.labor);
  const totalTools = sum(c.tools);
  const direct = totalMaterials + totalLabor + totalTools;
  const adminAmt = direct * ((parseFloat(document.getElementById("fc-admin")?.value) || 0) / 100);
  const utilAmt = direct * ((parseFloat(document.getElementById("fc-util")?.value) || 0) / 100);
  return { totalMaterials, totalLabor, totalTools, direct, adminAmt, utilAmt, grand: direct + adminAmt + utilAmt };
}

function updateFichaTotals() {
  const t = computeFichaTotalsLocal();
  document.getElementById("ficha-totals").innerHTML = `
    <div class="totals-row"><span>Total Materiales</span><span>${fmt(t.totalMaterials)}</span></div>
    <div class="totals-row"><span>Total Mano de Obra</span><span>${fmt(t.totalLabor)}</span></div>
    <div class="totals-row"><span>Total Herramientas</span><span>${fmt(t.totalTools)}</span></div>
    <div class="totals-row"><strong>Costo Directo</strong><strong>${fmt(t.direct)}</strong></div>
    <div class="totals-row"><span>Gastos Administrativos</span><span>${fmt(t.adminAmt)}</span></div>
    <div class="totals-row"><span>Utilidad</span><span>${fmt(t.utilAmt)}</span></div>
    <div class="totals-row grand"><span>Costo Total</span><span>${fmt(t.grand)}</span></div>
  `;
  ["fc-admin", "fc-util"].forEach(id => {
    const input = document.getElementById(id);
    if (input && !input._bound) {
      input.addEventListener("input", updateFichaTotals);
      input._bound = true;
    }
  });
}

async function saveFicha() {
  const c = editingCard;
  const body = {
    code: document.getElementById("fc-code").value,
    name: document.getElementById("fc-name").value,
    unit: document.getElementById("fc-unit").value,
    admin_pct: document.getElementById("fc-admin").value,
    utilidad_pct: document.getElementById("fc-util").value,
    items: [
      ...c.materials.map(i => ({ ...i, category: "material" })),
      ...c.labor.map(i => ({ ...i, category: "labor" })),
      ...c.tools.map(i => ({ ...i, category: "tool" })),
    ],
  };
  if (!body.code || !body.name) { alert("Código y nombre de actividad son requeridos."); return; }
  if (c.id) await api.put(`/api/costcards/${c.id}`, body);
  else await api.post("/api/costcards", body);
  loadCostCardList();
}

// ============================================================================
// QUOTES (Cotizaciones)
// ============================================================================

let quotesCache = [];
let editingQuote = null;

document.getElementById("btn-new-quote").addEventListener("click", () => openQuoteEditor(null));

async function loadQuoteList() {
  quotesCache = await api.get("/api/quotes");
  document.getElementById("quote-editor-panel").classList.add("hidden");
  document.getElementById("quotes-list-panel").classList.remove("hidden");
  const grid = document.getElementById("quote-grid");
  document.getElementById("quote-empty").hidden = quotesCache.length > 0;
  grid.innerHTML = quotesCache.map(q => `
    <div class="stamp-card" data-open="${q.id}">
      <div class="stamp-badge">${esc(q.date || "")}</div>
      <h3>${esc(q.name)}</h3>
      <div class="stamp-meta">${esc(q.client || "Sin cliente")} · ${q.lines.length} partidas</div>
      <div class="stamp-total"><span class="lbl">Costo total del proyecto</span>${fmt(q.grand_total)}</div>
    </div>
  `).join("");
  grid.querySelectorAll("[data-open]").forEach(el => el.addEventListener("click", async () => {
    const q = await api.get(`/api/quotes/${el.dataset.open}`);
    openQuoteEditor(q);
  }));
}

function openQuoteEditor(quote) {
  editingQuote = quote ? JSON.parse(JSON.stringify(quote)) : {
    id: null, name: "", client: "", date: new Date().toISOString().slice(0, 10),
    lines: [], transportation: [], other_fees: [],
  };
  editingQuote.lines.forEach(l => l._key = uid());
  editingQuote.transportation.forEach(f => f._key = uid());
  editingQuote.other_fees.forEach(f => f._key = uid());

  document.getElementById("quotes-list-panel").classList.add("hidden");
  document.getElementById("quote-editor-panel").classList.remove("hidden");
  renderQuoteEditor();
}

async function renderQuoteEditor() {
  if (costCardsCache.length === 0) costCardsCache = await api.get("/api/costcards");
  const q = editingQuote;
  const el = document.getElementById("quote-editor");

  const cardOptions = costCardsCache.map(c => `<option value="${c.id}">${esc(c.code)} — ${esc(c.name)} (${fmt(c.total_cost)})</option>`).join("");

  const lineRows = q.lines.map(l => {
    const card = costCardsCache.find(c => c.id == l.cost_card_id);
    const unitCost = card ? card.total_cost : (l.unit_cost || 0);
    const lineTotal = unitCost * (l.quantity || 0);
    return `
      <tr data-row="${l._key}">
        <td class="mono">${esc(card ? card.code : l.code || "")}</td>
        <td>${esc(card ? card.name : l.name || "")}</td>
        <td>${esc(card ? card.unit : l.unit || "")}</td>
        <td class="num-cell">${fmt(unitCost)}</td>
        <td><input class="f-qty" type="number" step="0.01" value="${l.quantity}" style="width:90px"></td>
        <td class="num-cell f-line-total">${fmt(lineTotal)}</td>
        <td><button class="btn btn-sm btn-danger remove-line">×</button></td>
      </tr>`;
  }).join("");

  const feeRows = (arr, cls) => arr.map(f => `
    <tr data-row="${f._key}">
      <td><input class="f-fee-desc" value="${esc(f.description)}" placeholder="Descripción"></td>
      <td><input class="f-fee-amt" type="number" step="0.01" value="${f.amount}" style="width:120px"></td>
      <td><button class="btn btn-sm btn-danger remove-fee" data-cls="${cls}">×</button></td>
    </tr>`).join("");

  el.innerHTML = `
    <div class="editor-fields" style="margin-bottom:8px">
      <div class="field"><label>Nombre del proyecto</label><input id="q-name" value="${esc(q.name)}" style="min-width:260px"></div>
      <div class="field"><label>Cliente</label><input id="q-client" value="${esc(q.client)}"></div>
      <div class="field narrow"><label>Fecha</label><input id="q-date" type="date" value="${esc(q.date)}"></div>
    </div>

    <div class="section-title">Partidas (Fichas de Costo)</div>
    <div style="display:flex;gap:10px;margin:10px 0">
      <select id="q-add-card" style="flex:1;padding:8px;border:1px solid #c9c2ae">
        <option value="">— seleccionar ficha de costo para agregar —</option>
        ${cardOptions}
      </select>
      <button class="btn btn-primary btn-sm" id="q-add-card-btn">+ Agregar</button>
    </div>
    <table class="line-table">
      <thead><tr><th>Código</th><th>Actividad</th><th style="width:70px">Unidad</th><th style="width:110px">Costo Unit.</th><th style="width:100px">Cantidad</th><th style="width:120px">Total</th><th style="width:36px"></th></tr></thead>
      <tbody id="q-lines-body">${lineRows}</tbody>
    </table>

    <div class="section-title">Transporte</div>
    <table class="line-table"><tbody id="q-transport-body">${feeRows(q.transportation, "transportation")}</tbody></table>
    <button class="add-row-btn" id="q-add-transport">+ Agregar gasto de transporte</button>

    <div class="section-title">Otros Gastos</div>
    <table class="line-table"><tbody id="q-other-body">${feeRows(q.other_fees, "other")}</tbody></table>
    <button class="add-row-btn" id="q-add-other">+ Agregar otro gasto</button>

    <div class="totals-box" id="quote-totals"></div>

    <div class="editor-actions">
      <button class="btn btn-primary" id="q-save">Guardar Cotización</button>
      <button class="btn btn-ghost" id="q-cancel">Volver a la lista</button>
      ${q.id ? '<button class="btn btn-danger" id="q-delete">Eliminar Cotización</button>' : ""}
    </div>
  `;

  bindQuoteEvents();
  updateQuoteTotals();
}

function bindQuoteEvents() {
  const q = editingQuote;

  document.getElementById("q-add-card-btn").addEventListener("click", () => {
    const sel = document.getElementById("q-add-card");
    if (!sel.value) return;
    q.lines.push({ _key: uid(), cost_card_id: parseInt(sel.value), quantity: 1 });
    renderQuoteEditor();
  });

  document.querySelectorAll("#q-lines-body tr").forEach(tr => {
    const key = tr.dataset.row;
    const line = q.lines.find(l => l._key === key);
    tr.querySelector(".f-qty").addEventListener("input", (e) => {
      line.quantity = parseFloat(e.target.value) || 0;
      const card = costCardsCache.find(c => c.id == line.cost_card_id);
      tr.querySelector(".f-line-total").textContent = fmt((card ? card.total_cost : 0) * line.quantity);
      updateQuoteTotals();
    });
    tr.querySelector(".remove-line").addEventListener("click", () => {
      q.lines = q.lines.filter(l => l._key !== key);
      renderQuoteEditor();
    });
  });

  document.getElementById("q-add-transport").addEventListener("click", () => {
    q.transportation.push({ _key: uid(), description: "", amount: 0 });
    renderQuoteEditor();
  });
  document.getElementById("q-add-other").addEventListener("click", () => {
    q.other_fees.push({ _key: uid(), description: "", amount: 0 });
    renderQuoteEditor();
  });

  [["q-transport-body", q.transportation], ["q-other-body", q.other_fees]].forEach(([bodyId, arr]) => {
    document.querySelectorAll(`#${bodyId} tr`).forEach(tr => {
      const key = tr.dataset.row;
      const fee = arr.find(f => f._key === key);
      tr.querySelector(".f-fee-desc").addEventListener("input", (e) => { fee.description = e.target.value; });
      tr.querySelector(".f-fee-amt").addEventListener("input", (e) => { fee.amount = parseFloat(e.target.value) || 0; updateQuoteTotals(); });
      tr.querySelector(".remove-fee").addEventListener("click", () => {
        if (bodyId === "q-transport-body") q.transportation = q.transportation.filter(f => f._key !== key);
        else q.other_fees = q.other_fees.filter(f => f._key !== key);
        renderQuoteEditor();
      });
    });
  });

  document.getElementById("q-cancel").addEventListener("click", loadQuoteList);
  document.getElementById("q-save").addEventListener("click", saveQuote);
  const delBtn = document.getElementById("q-delete");
  if (delBtn) delBtn.addEventListener("click", async () => {
    if (!confirm("¿Eliminar esta cotización?")) return;
    await api.del(`/api/quotes/${editingQuote.id}`);
    loadQuoteList();
  });
}

function updateQuoteTotals() {
  const q = editingQuote;
  const linesTotal = q.lines.reduce((s, l) => {
    const card = costCardsCache.find(c => c.id == l.cost_card_id);
    return s + (card ? card.total_cost : 0) * (l.quantity || 0);
  }, 0);
  const transportTotal = q.transportation.reduce((s, f) => s + (f.amount || 0), 0);
  const otherTotal = q.other_fees.reduce((s, f) => s + (f.amount || 0), 0);
  const grand = linesTotal + transportTotal + otherTotal;

  document.getElementById("quote-totals").innerHTML = `
    <div class="totals-row"><span>Subtotal Fichas de Costo</span><span>${fmt(linesTotal)}</span></div>
    <div class="totals-row"><span>Transporte</span><span>${fmt(transportTotal)}</span></div>
    <div class="totals-row"><span>Otros Gastos</span><span>${fmt(otherTotal)}</span></div>
    <div class="totals-row grand"><span>Costo Total Proyecto</span><span>${fmt(grand)}</span></div>
  `;
}

async function saveQuote() {
  const q = editingQuote;
  const body = {
    name: document.getElementById("q-name").value,
    client: document.getElementById("q-client").value,
    date: document.getElementById("q-date").value,
    lines: q.lines.map(l => ({ cost_card_id: l.cost_card_id, quantity: l.quantity })),
    transportation: q.transportation.map(f => ({ description: f.description, amount: f.amount })),
    other_fees: q.other_fees.map(f => ({ description: f.description, amount: f.amount })),
  };
  if (!body.name) { alert("El proyecto necesita un nombre."); return; }
  if (q.id) await api.put(`/api/quotes/${q.id}`, body);
  else await api.post("/api/quotes", body);
  loadQuoteList();
}

// ============================================================================
// Init
// ============================================================================

loadCatalog();
