// ============================================================================
// Helpers
// ============================================================================

function handleAuthFailure(res) {
  if (res.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    throw new Error("not authenticated");
  }
  return res;
}

async function parseApiResponse(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || "Ocurrió un error inesperado.");
  }
  return data;
}

const api = {
  get: (url) => fetch(url).then(handleAuthFailure).then(r => r.json()),
  post: (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(handleAuthFailure).then(parseApiResponse),
  put: (url, body) => fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(handleAuthFailure).then(parseApiResponse),
  del: (url) => fetch(url, { method: "DELETE" }).then(handleAuthFailure),
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

function showModal(html, wide) {
  const backdrop = document.getElementById("modal-backdrop");
  const box = document.getElementById("modal-box");
  box.classList.toggle("modal-wide", !!wide);
  box.innerHTML = html;
  backdrop.hidden = false;
}
function hideModal() {
  document.getElementById("modal-backdrop").hidden = true;
}
let backdropMouseDownWasSelf = false;
document.getElementById("modal-backdrop").addEventListener("mousedown", (e) => {
  backdropMouseDownWasSelf = e.target.id === "modal-backdrop";
});
document.getElementById("modal-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "modal-backdrop" && backdropMouseDownWasSelf) hideModal();
  backdropMouseDownWasSelf = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("modal-backdrop").hidden) hideModal();
});

// ============================================================================
// CATALOGS
// ============================================================================

let currentCatalogCat = "material";
let catalogCache = { material: [], labor: [], tool: [], transport: [], gasto: [] };
const CAT_LABELS = { material: "Materiales", labor: "Mano de Obra", tool: "Herramientas", transport: "Transporte", gasto: "Gastos" };
const CODE_PLACEHOLDERS = { material: "Ej. X00", labor: "Ej. M00", tool: "Ej. H00", transport: "Ej. T00", gasto: "Ej. G00" };

document.querySelectorAll("#catalog-tabs .tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#catalog-tabs .tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentCatalogCat = tab.dataset.cat;
    if (currentCatalogCat === "supplier") loadSupplierQuotesTab();
    else loadCatalog();
  });
});

document.getElementById("catalog-search").addEventListener("input", (e) => {
  const val = e.target.value.trim().toLowerCase();
  if (currentCatalogCat === "supplier") renderSupplierQuotesTable(val);
  else renderCatalogTable(val);
});

// ----- Papelera (trash / soft-delete recovery) -----

async function openTrashModal(kind) {
  let items, title, label, apiBase;
  if (kind === "catalog") {
    apiBase = `/api/catalog/${currentCatalogCat}`;
    items = await api.get(`${apiBase}/trash`);
    title = `Papelera — ${CAT_LABELS[currentCatalogCat]}`;
    label = (item) => `${item.code} — ${item.description}`;
  } else if (kind === "costcard") {
    apiBase = "/api/costcards";
    items = await api.get(`${apiBase}/trash`);
    title = "Papelera — Fichas de Costo";
    label = (item) => `${item.code} — ${item.name}`;
  } else {
    apiBase = "/api/quotes";
    items = await api.get(`${apiBase}/trash`);
    title = "Papelera — Cotizaciones";
    label = (item) => item.name;
  }

  const rows = items.map(item => `
    <tr data-id="${item.id}">
      <td>${esc(label(item))}</td>
      <td class="stamp-meta">Eliminado: ${esc(item.deleted_at || "—")}</td>
      <td class="col-actions">
        <button class="btn btn-sm btn-primary trash-restore">Restaurar</button>
        <button class="btn btn-sm btn-danger trash-permanent">Eliminar permanentemente</button>
      </td>
    </tr>`).join("");

  showModal(`
    <h2>${title}</h2>
    ${items.length === 0
      ? '<p class="stamp-meta">La papelera está vacía.</p>'
      : `<table class="line-table"><tbody>${rows}</tbody></table>`}
    <div class="modal-actions"><button class="btn btn-ghost" id="trash-close">Cerrar</button></div>
  `, true);

  document.getElementById("trash-close").addEventListener("click", () => {
    hideModal();
    if (kind === "catalog") loadCatalog();
    else if (kind === "costcard") loadCostCardList();
    else loadQuoteList();
  });

  document.querySelectorAll(".trash-restore").forEach(btn => btn.addEventListener("click", async () => {
    const id = btn.closest("tr").dataset.id;
    try {
      await api.post(`${apiBase}/${id}/restore`, {});
    } catch (err) {
      alert(err.message);
      return;
    }
    openTrashModal(kind);
  }));

  document.querySelectorAll(".trash-permanent").forEach(btn => btn.addEventListener("click", async () => {
    if (!confirm("¿Eliminar PERMANENTEMENTE? Esta acción no se puede deshacer y no se podrá recuperar después.")) return;
    const id = btn.closest("tr").dataset.id;
    await api.del(`${apiBase}/${id}/permanent`);
    openTrashModal(kind);
  }));
}

document.getElementById("btn-catalog-trash").addEventListener("click", () => openTrashModal("catalog"));
document.getElementById("btn-new-catalog-item").addEventListener("click", () => {
  if (currentCatalogCat === "supplier") openSupplierQuoteForm(null);
  else openCatalogForm(null);
});

async function loadCatalog() {
  const items = await api.get(`/api/catalog/${currentCatalogCat}`);
  catalogCache[currentCatalogCat] = items;
  renderCatalogTable("");
}

function catalogTheadHtml() {
  if (currentCatalogCat === "material") {
    return `<tr>
      <th class="col-code">Código</th>
      <th class="col-date">Fecha Agregado</th>
      <th class="col-date">Fecha Modificación</th>
      <th>Descripción</th>
      <th class="col-unit">Unidad</th>
      <th class="col-num">Precio Unit.</th>
      <th class="col-num">Precio Mín.</th>
      <th class="col-num">Precio Máx.</th>
      <th class="col-date">Últ. Proveedor</th>
      <th class="col-actions"></th>
    </tr>`;
  }
  return `<tr>
    <th class="col-code">Código</th>
    <th>Descripción</th>
    <th class="col-unit">Unidad</th>
    <th class="col-num">Precio Unit.</th>
    <th class="col-date">Fecha Modificación</th>
    <th class="col-actions"></th>
  </tr>`;
}

function renderCatalogTable(filter) {
  const items = catalogCache[currentCatalogCat].filter(i =>
    !filter || i.code.toLowerCase().includes(filter) || i.description.toLowerCase().includes(filter));
  const tbody = document.getElementById("catalog-tbody");
  document.getElementById("catalog-thead").innerHTML = catalogTheadHtml();
  document.getElementById("catalog-empty").hidden = items.length > 0;

  const isMaterial = currentCatalogCat === "material";

  tbody.innerHTML = items.map(i => {
    if (isMaterial) {
      const minCell = i.price_min != null ? `${fmt(i.price_min)} <span class="stamp-meta">— ${esc(i.price_min_proveedor)}</span>` : "—";
      const maxCell = i.price_max != null ? `${fmt(i.price_max)} <span class="stamp-meta">— ${esc(i.price_max_proveedor)}</span>` : "—";
      return `
        <tr>
          <td class="mono">${esc(i.code)}</td>
          <td>${esc(i.created_at || "—")}</td>
          <td>${esc(i.updated_at || "—")}</td>
          <td>${esc(i.description)}</td>
          <td>${esc(i.unit)}</td>
          <td class="num">${fmt(i.unit_price)}</td>
          <td class="num">${minCell}</td>
          <td class="num">${maxCell}</td>
          <td>${esc(i.latest_date || "—")}</td>
          <td class="col-actions">
            <button class="btn btn-sm btn-ghost" data-suppliers="${i.id}">Proveedores${i.supplier_count ? ` (${i.supplier_count})` : ""}</button>
            <button class="btn btn-sm btn-ghost" data-edit="${i.id}">Editar</button>
            <button class="btn btn-sm btn-danger" data-del="${i.id}">×</button>
          </td>
        </tr>`;
    }
    return `
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
      </tr>`;
  }).join("");

  tbody.querySelectorAll("[data-edit]").forEach(b => b.addEventListener("click", () => {
    const item = catalogCache[currentCatalogCat].find(x => x.id == b.dataset.edit);
    openCatalogForm(item);
  }));
  tbody.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
    const item = catalogCache[currentCatalogCat].find(x => x.id == b.dataset.del);
    const label = item ? `${item.code} — ${item.description}` : "este artículo";
    if (!confirm(`¿Mover "${label}" a la papelera? Podrás restaurarlo después desde 🗑 Papelera.`)) return;
    await api.del(`/api/catalog/${currentCatalogCat}/${b.dataset.del}`);
    loadCatalog();
  }));
  tbody.querySelectorAll("[data-suppliers]").forEach(b => b.addEventListener("click", () => {
    const item = catalogCache[currentCatalogCat].find(x => x.id == b.dataset.suppliers);
    openSupplierModal(item);
  }));
}

// ----- Supplier prices (Proveedores) per material -----

function openSupplierModal(material) {
  showModal(`
    <h2>Proveedores — ${esc(material.code)} · ${esc(material.description)}</h2>
    <p class="stamp-meta" style="margin-top:-8px">El precio unitario del material no cambia automáticamente; esto es solo referencia para comparar proveedores.</p>
    <div id="supplier-table-wrap">Cargando…</div>
    <div class="modal-actions">
      <button class="btn btn-primary" id="sup-close">Cerrar</button>
    </div>
  `, true);
  document.getElementById("sup-close").addEventListener("click", () => { hideModal(); loadCatalog(); });
  loadSuppliers(material.id);
}

async function loadSuppliers(materialId) {
  const suppliers = await api.get(`/api/materials/${materialId}/suppliers`);
  renderSupplierTable(materialId, suppliers);
}

function renderSupplierTable(materialId, suppliers) {
  const wrap = document.getElementById("supplier-table-wrap");
  if (!wrap) return; // modal was closed before this resolved
  const sorted = [...suppliers].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  const rows = sorted.map(s => `
    <tr data-id="${s.id}">
      <td><input class="s-proveedor" value="${esc(s.proveedor)}" placeholder="Nombre del proveedor"></td>
      <td><input class="s-code" value="${esc(s.code || "")}" placeholder="Su código"></td>
      <td><input class="s-desc" value="${esc(s.description || "")}" placeholder="Su descripción"></td>
      <td><input class="s-unit" value="${esc(s.unit || "")}" placeholder="Unidad"></td>
      <td><input class="s-price" type="number" step="0.01" value="${s.price}" style="width:100px"></td>
      <td><input class="s-date" type="date" value="${esc(s.date || "")}"></td>
      <td><button class="btn btn-sm btn-danger sup-del">×</button></td>
    </tr>`).join("");

  wrap.innerHTML = `
    <table class="line-table">
      <thead><tr>
        <th>Proveedor</th><th style="width:100px">Código</th><th>Descripción</th>
        <th style="width:80px">Unidad</th><th style="width:110px">Precio</th><th style="width:130px">Fecha</th><th style="width:36px"></th>
      </tr></thead>
      <tbody id="sup-tbody">${rows}</tbody>
    </table>
    <button class="add-row-btn" id="sup-add">+ Agregar</button>
  `;

  wrap.querySelectorAll("#sup-tbody tr").forEach(tr => {
    const id = tr.dataset.id;
    const save = async () => {
      await api.put(`/api/suppliers/${id}`, {
        proveedor: tr.querySelector(".s-proveedor").value,
        code: tr.querySelector(".s-code").value,
        description: tr.querySelector(".s-desc").value,
        unit: tr.querySelector(".s-unit").value,
        price: tr.querySelector(".s-price").value,
        date: tr.querySelector(".s-date").value,
      });
      loadSuppliers(materialId);
    };
    tr.querySelectorAll("input").forEach(inp => inp.addEventListener("change", save));
    tr.querySelector(".sup-del").addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta cotización de proveedor?")) return;
      await api.del(`/api/suppliers/${id}`);
      loadSuppliers(materialId);
    });
  });

  document.getElementById("sup-add").addEventListener("click", () => {
    const tbody = wrap.querySelector("#sup-tbody");
    tbody.insertAdjacentHTML("beforeend", `
      <tr data-new="1">
        <td><input class="s-proveedor" placeholder="Nombre del proveedor"></td>
        <td><input class="s-code" placeholder="Su código"></td>
        <td><input class="s-desc" placeholder="Su descripción"></td>
        <td><input class="s-unit" placeholder="Unidad"></td>
        <td><input class="s-price" type="number" step="0.01" value="0" style="width:100px"></td>
        <td><input class="s-date" type="date" value="${new Date().toISOString().slice(0, 10)}"></td>
        <td><button class="btn btn-sm btn-primary sup-save-new">Guardar</button></td>
      </tr>
    `);
    const tr = tbody.querySelector('tr[data-new="1"]');
    tr.querySelector(".sup-save-new").addEventListener("click", async () => {
      const proveedor = tr.querySelector(".s-proveedor").value.trim();
      if (!proveedor) { alert("El nombre del proveedor es requerido."); return; }
      await api.post(`/api/materials/${materialId}/suppliers`, {
        proveedor,
        code: tr.querySelector(".s-code").value,
        description: tr.querySelector(".s-desc").value,
        unit: tr.querySelector(".s-unit").value,
        price: tr.querySelector(".s-price").value,
        date: tr.querySelector(".s-date").value,
      });
      loadSuppliers(materialId);
    });
  });
}

// ----- Flat "Cotizaciones de Proveedores" tab (all suppliers, linked by dropdown) -----

let allSupplierQuotes = [];

async function loadSupplierQuotesTab() {
  allSupplierQuotes = await api.get("/api/suppliers");
  renderSupplierQuotesTable("");
}

function renderSupplierQuotesTable(filter) {
  const items = allSupplierQuotes.filter(s => !filter
    || (s.proveedor || "").toLowerCase().includes(filter)
    || (s.code || "").toLowerCase().includes(filter)
    || (s.material_code || "").toLowerCase().includes(filter)
    || (s.material_description || "").toLowerCase().includes(filter));

  document.getElementById("catalog-thead").innerHTML = `<tr>
    <th style="width:150px">Material</th>
    <th class="col-code">Cód. Proveedor</th>
    <th>Descripción Proveedor</th>
    <th class="col-unit">Unidad</th>
    <th class="col-num">Precio</th>
    <th class="col-date">Fecha</th>
    <th class="col-actions"></th>
  </tr>`;

  const tbody = document.getElementById("catalog-tbody");
  document.getElementById("catalog-empty").hidden = items.length > 0;
  tbody.innerHTML = items.map(s => `
    <tr>
      <td class="mono">${esc(s.material_code || "—")}<div class="stamp-meta">${esc(s.material_description || "")}</div></td>
      <td class="mono">${esc(s.code || "—")}</td>
      <td>${esc(s.description || "—")}<div class="stamp-meta">${esc(s.proveedor)}</div></td>
      <td>${esc(s.unit || "—")}</td>
      <td class="num">${fmt(s.price)}</td>
      <td>${esc(s.date || "—")}</td>
      <td class="col-actions">
        <button class="btn btn-sm btn-ghost" data-edit-sq="${s.id}">Editar</button>
        <button class="btn btn-sm btn-danger" data-del-sq="${s.id}">×</button>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll("[data-edit-sq]").forEach(b => b.addEventListener("click", () => {
    const item = allSupplierQuotes.find(x => x.id == b.dataset.editSq);
    openSupplierQuoteForm(item);
  }));
  tbody.querySelectorAll("[data-del-sq]").forEach(b => b.addEventListener("click", async () => {
    if (!confirm("¿Eliminar esta cotización de proveedor?")) return;
    await api.del(`/api/suppliers/${b.dataset.delSq}`);
    loadSupplierQuotesTab();
  }));
}

async function openSupplierQuoteForm(item) {
  const isNew = !item;
  const materials = await api.get("/api/catalog/material");
  const options = materials.map(m => `<option value="${m.id}" ${item && item.material_id == m.id ? "selected" : ""}>${esc(m.code)} — ${esc(m.description)}</option>`).join("");

  showModal(`
    <h2>${isNew ? "Nueva" : "Editar"} Cotización de Proveedor</h2>
    <div class="field"><label>Material</label>
      <select id="sq-material">${isNew ? '<option value="">— seleccionar material —</option>' : ""}${options}</select>
    </div>
    <div class="field"><label>Nombre del Proveedor</label><input id="sq-proveedor" value="${esc(item?.proveedor || "")}" placeholder="Ej. Ferretería Central"></div>
    <div class="field"><label>Código Proveedor</label><input id="sq-code" value="${esc(item?.code || "")}"></div>
    <div class="field"><label>Descripción Proveedor</label><input id="sq-desc" value="${esc(item?.description || "")}"></div>
    <div class="field"><label>Unidad</label><input id="sq-unit" value="${esc(item?.unit || "")}"></div>
    <div class="field"><label>Precio (L)</label><input id="sq-price" type="number" step="0.01" value="${item?.price ?? ""}"></div>
    <div class="field"><label>Fecha</label><input id="sq-date" type="date" value="${esc(item?.date || new Date().toISOString().slice(0, 10))}"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost" id="sq-cancel">Cancelar</button>
      <button class="btn btn-primary" id="sq-save">Guardar</button>
    </div>
  `);

  document.getElementById("sq-cancel").addEventListener("click", hideModal);
  document.getElementById("sq-save").addEventListener("click", async () => {
    const materialId = isNew ? document.getElementById("sq-material").value : item.material_id;
    if (!materialId) { alert("Selecciona un material para vincular esta cotización."); return; }
    const proveedor = document.getElementById("sq-proveedor").value.trim();
    if (!proveedor) { alert("El nombre del proveedor es requerido."); return; }
    const body = {
      proveedor,
      code: document.getElementById("sq-code").value,
      description: document.getElementById("sq-desc").value,
      unit: document.getElementById("sq-unit").value,
      price: document.getElementById("sq-price").value,
      date: document.getElementById("sq-date").value,
    };
    if (isNew) await api.post(`/api/materials/${materialId}/suppliers`, body);
    else await api.put(`/api/suppliers/${item.id}`, body);
    hideModal();
    loadSupplierQuotesTab();
  });
}

function openCatalogForm(item) {
  const isNew = !item;
  const isMaterial = currentCatalogCat === "material";
  showModal(`
    <h2>${isNew ? "Nuevo" : "Editar"} — ${CAT_LABELS[currentCatalogCat]}</h2>
    <div class="field"><label>Código</label><input id="mf-code" value="${esc(item?.code || "")}" placeholder="${CODE_PLACEHOLDERS[currentCatalogCat] || ""}"></div>
    <div class="field"><label>Descripción</label><input id="mf-desc" value="${esc(item?.description || "")}" placeholder="Descripción del artículo"></div>
    <div class="field"><label>Unidad</label><input id="mf-unit" value="${esc(item?.unit || "")}" placeholder="Unidad, Metros, Hora…"></div>
    ${isMaterial
      ? '<p class="stamp-meta" style="margin:0 0 8px">El precio se calcula automáticamente: el más alto entre las cotizaciones de proveedor más recientes (pestaña Cotizaciones de Proveedores).</p>'
      : `<div class="field"><label>Precio unitario (L)</label><input id="mf-price" type="number" step="0.01" value="${item?.unit_price ?? ""}"></div>`}
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
    };
    if (!isMaterial) body.unit_price = document.getElementById("mf-price").value;
    if (!body.code || !body.description) { alert("Código y descripción son requeridos."); return; }
    try {
      if (isNew) await api.post(`/api/catalog/${currentCatalogCat}`, body);
      else await api.put(`/api/catalog/${currentCatalogCat}/${item.id}`, body);
    } catch (err) {
      alert(err.message);
      return;
    }
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
document.getElementById("btn-costcard-trash").addEventListener("click", () => openTrashModal("costcard"));

async function loadCostCardList() {
  costCardsCache = await api.get("/api/costcards");
  document.getElementById("costcard-editor-panel").classList.add("hidden");
  document.getElementById("costcards-list-panel").classList.remove("hidden");
  renderCostCardGrid("");
}

const FICHA_SECTION_KEY = { material: "materials", labor: "labor", tool: "tools", transport: "transport", gasto: "gastos" };

function renderCostCardGrid(filter) {
  const items = costCardsCache.filter(c =>
    !filter || c.code.toLowerCase().includes(filter) || c.name.toLowerCase().includes(filter));
  const tbody = document.getElementById("costcard-tbody");
  document.getElementById("costcard-empty").hidden = items.length > 0;
  tbody.innerHTML = items.map(c => `
    <tr>
      <td class="mono">${esc(c.code)}</td>
      <td>${esc(c.name)}</td>
      <td class="desc-cell" title="${esc(c.description || "")}">${esc(c.description || "—")}</td>
      <td>${esc(c.unit || "—")}</td>
      <td class="num">${fmt(c.total_cost)}</td>
      <td title="Creado: ${esc(c.created_at || "—")}">${esc(c.updated_at || "—")}</td>
      <td class="col-actions">
        <button class="btn btn-sm btn-ghost" data-open="${c.id}">Abrir</button>
        <button class="btn btn-sm btn-danger" data-del-card="${c.id}">×</button>
      </td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-open]").forEach(el => el.addEventListener("click", async () => {
    const card = await api.get(`/api/costcards/${el.dataset.open}`);
    openFichaEditor(card);
  }));
  tbody.querySelectorAll("[data-del-card]").forEach(btn => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const card = costCardsCache.find(x => x.id == btn.dataset.delCard);
    const label = card ? `${card.code} — ${card.name}` : "esta ficha";
    if (!confirm(`¿Mover la ficha "${label}" a la papelera? Podrás restaurarla después desde 🗑 Papelera.`)) return;
    await api.del(`/api/costcards/${btn.dataset.delCard}`);
    loadCostCardList();
  }));
}

async function refreshFichaPricesFromCatalog() {
  syncTopFieldsToCard();
  // Force a fresh pull from the catalogs (not just "load if empty")
  catalogCache.material = await api.get("/api/catalog/material");
  catalogCache.labor = await api.get("/api/catalog/labor");
  catalogCache.tool = await api.get("/api/catalog/tool");
  catalogCache.transport = await api.get("/api/catalog/transport");
  catalogCache.gasto = await api.get("/api/catalog/gasto");

  const refreshGroup = (items, cat) => {
    items.forEach(it => {
      if (!it.code) return;
      const match = catalogCache[cat].find(x => x.code === it.code);
      if (match) {
        it.description = match.description;
        it.unit = match.unit;
        it.unit_price = match.unit_price;
      }
    });
  };
  refreshGroup(editingCard.materials, "material");
  refreshGroup(editingCard.labor, "labor");
  refreshGroup(editingCard.tools, "tool");
  refreshGroup(editingCard.transport, "transport");
  refreshGroup(editingCard.gastos, "gasto");
  renderFichaEditor();
}

function blankItem(category) {
  return { _key: uid(), category, code: "", description: "", unit: "", rendimiento: 0, desperdicio_pct: 0, unit_price: 0 };
}

function openFichaEditor(card) {
  editingCard = card ? JSON.parse(JSON.stringify(card)) : {
    id: null, code: "", name: "", unit: "",
    admin_pct: 10, utilidad_pct: 15,
    materials: [], labor: [], tools: [], transport: [], gastos: [],
  };
  editingCard.materials.forEach(i => i._key = uid());
  editingCard.labor.forEach(i => i._key = uid());
  editingCard.tools.forEach(i => i._key = uid());
  editingCard.transport.forEach(i => i._key = uid());
  editingCard.gastos.forEach(i => i._key = uid());

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
        <th class="no-print" style="width:22%">Del catálogo</th>
        <th>Código</th><th>Descripción</th><th style="width:70px">Unidad</th>
        <th style="width:90px">Rendim.</th><th style="width:90px">Desp. %</th>
        <th style="width:100px">P.Unit</th><th style="width:100px">Subtotal</th><th style="width:100px">Total</th><th class="no-print" style="width:36px"></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <button class="add-row-btn" data-add="${category}">+ Agregar</button>
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
      <td class="no-print"><select class="picker">${catalogOptionsHtml(category, it.code)}</select></td>
      <td><input class="f-code" value="${esc(it.code)}"></td>
      <td><input class="f-desc" value="${esc(it.description)}"></td>
      <td><input class="f-unit" value="${esc(it.unit)}"></td>
      <td><input class="f-rend" type="number" step="0.0001" value="${it.rendimiento}"></td>
      <td><input class="f-desp" type="number" step="0.01" value="${it.desperdicio_pct}"></td>
      <td><input class="f-price" type="number" step="0.01" value="${it.unit_price}"></td>
      <td class="num-cell f-subtotal">${fmt(subtotal)}</td>
      <td class="num-cell f-total">${fmt(total)}</td>
      <td class="no-print"><button class="btn btn-sm btn-danger remove-row">×</button></td>
    </tr>
  `;
}

async function ensureCatalogsLoaded() {
  for (const cat of ["material", "labor", "tool", "transport", "gasto"]) {
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
    <div class="print-head">
      <div class="print-title">Ficha de Costo ${esc(c.code)} — ${esc(c.name)}</div>
      <div class="print-meta">Unidad: ${esc(c.unit || "—")} · Generado el ${new Date().toLocaleDateString("es-HN")}</div>
      ${c.description ? `<div class="print-meta" style="margin-top:4px">${esc(c.description)}</div>` : ""}
    </div>

    <div class="editor-head">
      <div class="editor-fields">
        <div class="field narrow"><label>Código</label><input id="fc-code" value="${esc(c.code)}" placeholder="001"></div>
        <div class="field"><label>Actividad</label><input id="fc-name" value="${esc(c.name)}" placeholder="Nombre de la actividad" style="min-width:260px"></div>
        <div class="field"><label>Unidad de medida</label><input id="fc-unit" value="${esc(c.unit)}" placeholder="Unidad, Metro…"></div>
        <div class="field narrow"><label>Gastos admin. %</label><input id="fc-admin" type="number" step="0.01" value="${c.admin_pct}"></div>
        <div class="field narrow"><label>Utilidad %</label><input id="fc-util" type="number" step="0.01" value="${c.utilidad_pct}"></div>
      </div>
      <div class="field" style="width:100%; margin-top:10px;">
        <label>Descripción</label>
        <textarea id="fc-description" placeholder="Detalle de la actividad, alcance, notas…" style="width:100%; min-height:70px; padding:8px 10px; border:1px solid #c9c2ae; font-size:13px; font-family:inherit; background:var(--paper); resize:vertical;">${esc(c.description || "")}</textarea>
      </div>
    </div>

    ${fichaSectionHtml("material", "Materiales", c.materials)}
    ${fichaSectionHtml("labor", "Mano de Obra", c.labor)}
    ${fichaSectionHtml("tool", "Herramientas", c.tools)}
    ${fichaSectionHtml("transport", "Transporte", c.transport)}
    ${fichaSectionHtml("gasto", "Otros Gastos", c.gastos)}

    <div class="totals-box" id="ficha-totals"></div>

    <div class="editor-actions">
      <button class="btn btn-primary" id="fc-save">Guardar Ficha</button>
      <button class="btn btn-amber" id="fc-refresh">🔄 Actualizar precios</button>
      <button class="btn btn-print" id="fc-print">🖨 Imprimir / Guardar PDF</button>
      <button class="btn btn-ghost" id="fc-cancel">Volver a la lista</button>
      ${c.id ? '<button class="btn btn-danger" id="fc-delete">Eliminar Ficha</button>' : ""}
    </div>
  `;

  bindFichaEvents();
  updateFichaTotals();
}

function syncTopFieldsToCard() {
  const get = (id) => { const el = document.getElementById(id); return el ? el.value : undefined; };
  if (document.getElementById("fc-code")) editingCard.code = get("fc-code");
  if (document.getElementById("fc-name")) editingCard.name = get("fc-name");
  if (document.getElementById("fc-unit")) editingCard.unit = get("fc-unit");
  if (document.getElementById("fc-description")) editingCard.description = get("fc-description");
  if (document.getElementById("fc-admin")) editingCard.admin_pct = get("fc-admin");
  if (document.getElementById("fc-util")) editingCard.utilidad_pct = get("fc-util");
}

function bindFichaEvents() {
  const el = document.getElementById("ficha-editor");

  el.querySelectorAll(".add-row-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      syncTopFieldsToCard();
      const cat = btn.dataset.add;
      const key = FICHA_SECTION_KEY[cat];
      editingCard[key].push(blankItem(cat));
      renderFichaEditor();
    });
  });

  el.querySelectorAll("table[data-section]").forEach(table => {
    const cat = table.dataset.section;
    const key = FICHA_SECTION_KEY[cat];

    table.querySelectorAll(".remove-row").forEach(btn => {
      btn.addEventListener("click", () => {
        syncTopFieldsToCard();
        const rowKey = btn.closest("tr").dataset.row;
        editingCard[key] = editingCard[key].filter(i => i._key !== rowKey);
        renderFichaEditor();
      });
    });

    table.querySelectorAll(".picker").forEach(sel => {
      sel.addEventListener("change", () => {
        syncTopFieldsToCard();
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
  document.getElementById("fc-print").addEventListener("click", () => window.print());
  document.getElementById("fc-refresh").addEventListener("click", refreshFichaPricesFromCatalog);
  const delBtn = document.getElementById("fc-delete");
  if (delBtn) delBtn.addEventListener("click", async () => {
    if (!confirm(`¿Mover la ficha "${editingCard.code} — ${editingCard.name}" a la papelera? Dejará de aparecer para agregarla a nuevas cotizaciones, pero las cotizaciones que ya la usan no se ven afectadas. Podrás restaurarla después desde 🗑 Papelera.`)) return;
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
  const totalTransport = sum(c.transport);
  const totalGastos = sum(c.gastos);
  const direct = totalMaterials + totalLabor + totalTools + totalTransport + totalGastos;
  const adminAmt = direct * ((parseFloat(document.getElementById("fc-admin")?.value) || 0) / 100);
  const utilAmt = direct * ((parseFloat(document.getElementById("fc-util")?.value) || 0) / 100);
  return { totalMaterials, totalLabor, totalTools, totalTransport, totalGastos, direct, adminAmt, utilAmt, grand: direct + adminAmt + utilAmt };
}

function updateFichaTotals() {
  const t = computeFichaTotalsLocal();
  document.getElementById("ficha-totals").innerHTML = `
    <div class="totals-row"><span>Total Materiales</span><span>${fmt(t.totalMaterials)}</span></div>
    <div class="totals-row"><span>Total Mano de Obra</span><span>${fmt(t.totalLabor)}</span></div>
    <div class="totals-row"><span>Total Herramientas</span><span>${fmt(t.totalTools)}</span></div>
    <div class="totals-row"><span>Total Transporte</span><span>${fmt(t.totalTransport)}</span></div>
    <div class="totals-row"><span>Total Otros Gastos</span><span>${fmt(t.totalGastos)}</span></div>
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
    description: document.getElementById("fc-description").value,
    unit: document.getElementById("fc-unit").value,
    admin_pct: document.getElementById("fc-admin").value,
    utilidad_pct: document.getElementById("fc-util").value,
    items: [
      ...c.materials.map(i => ({ ...i, category: "material" })),
      ...c.labor.map(i => ({ ...i, category: "labor" })),
      ...c.tools.map(i => ({ ...i, category: "tool" })),
      ...c.transport.map(i => ({ ...i, category: "transport" })),
      ...c.gastos.map(i => ({ ...i, category: "gasto" })),
    ],
  };
  if (!body.code || !body.name) { alert("Código y nombre de actividad son requeridos."); return; }
  try {
    if (c.id) await api.put(`/api/costcards/${c.id}`, body);
    else await api.post("/api/costcards", body);
  } catch (err) {
    alert(err.message);
    return;
  }
  loadCostCardList();
}

// ============================================================================
// QUOTES (Cotizaciones)
// ============================================================================

let quotesCache = [];
let editingQuote = null;

document.getElementById("btn-new-quote").addEventListener("click", () => openQuoteEditor(null));
document.getElementById("btn-quote-trash").addEventListener("click", () => openTrashModal("quote"));

async function loadQuoteList() {
  quotesCache = await api.get("/api/quotes");
  document.getElementById("quote-editor-panel").classList.add("hidden");
  document.getElementById("quotes-list-panel").classList.remove("hidden");
  const tbody = document.getElementById("quote-tbody");
  document.getElementById("quote-empty").hidden = quotesCache.length > 0;
  tbody.innerHTML = quotesCache.map(q => `
    <tr>
      <td>${esc(q.name)}</td>
      <td>${esc(q.client || "—")}</td>
      <td>${esc(q.date || "—")}</td>
      <td class="num">${fmt(q.grand_total)}</td>
      <td class="col-actions">
        <button class="btn btn-sm btn-ghost" data-open="${q.id}">Abrir</button>
        <button class="btn btn-sm btn-danger" data-del-quote="${q.id}">×</button>
      </td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-open]").forEach(el => el.addEventListener("click", async () => {
    const q = await api.get(`/api/quotes/${el.dataset.open}`);
    openQuoteEditor(q);
  }));
  tbody.querySelectorAll("[data-del-quote]").forEach(btn => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const quote = quotesCache.find(x => x.id == btn.dataset.delQuote);
    const label = quote ? quote.name : "esta cotización";
    if (!confirm(`¿Mover la cotización "${label}" a la papelera? Podrás restaurarla después desde 🗑 Papelera.`)) return;
    await api.del(`/api/quotes/${btn.dataset.delQuote}`);
    loadQuoteList();
  }));
}

function openQuoteEditor(quote) {
  editingQuote = quote ? JSON.parse(JSON.stringify(quote)) : {
    id: null, name: "", client: "", date: new Date().toISOString().slice(0, 10),
    exento: false, lines: [],
  };
  editingQuote.lines.forEach(l => l._key = uid());

  document.getElementById("quotes-list-panel").classList.add("hidden");
  document.getElementById("quote-editor-panel").classList.remove("hidden");
  renderQuoteEditor();
}

function syncTopFieldsToQuote() {
  const get = (id) => { const el = document.getElementById(id); return el ? el.value : undefined; };
  const getChecked = (id) => { const el = document.getElementById(id); return el ? el.checked : undefined; };
  if (document.getElementById("q-name")) editingQuote.name = get("q-name");
  if (document.getElementById("q-client")) editingQuote.client = get("q-client");
  if (document.getElementById("q-date")) editingQuote.date = get("q-date");
  if (document.getElementById("q-exento")) editingQuote.exento = getChecked("q-exento");
}

async function refreshQuoteFromCatalog() {
  syncTopFieldsToQuote();
  costCardsCache = await api.get("/api/costcards");
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
        <td class="no-print"><button class="btn btn-sm btn-danger remove-line">×</button></td>
      </tr>`;
  }).join("");

  el.innerHTML = `
    <div class="print-head">
      <div class="print-title">Cotización — ${esc(q.name)}</div>
      <div class="print-meta">${q.client ? "Cliente: " + esc(q.client) + " · " : ""}Fecha: ${esc(q.date || "")}</div>
    </div>

    <div class="editor-fields" style="margin-bottom:8px">
      <div class="field"><label>Nombre del proyecto</label><input id="q-name" value="${esc(q.name)}" style="min-width:260px"></div>
      <div class="field"><label>Cliente</label><input id="q-client" value="${esc(q.client)}"></div>
      <div class="field"><label>Fecha</label><input id="q-date" type="date" value="${esc(q.date)}" style="min-width:160px;width:160px"></div>
    </div>

    <div class="section-title">Items</div>
    <div class="no-print" style="display:flex;gap:10px;margin:10px 0">
      <select id="q-add-card" style="flex:1;padding:8px;border:1px solid #c9c2ae">
        <option value="">— seleccionar ficha de costo para agregar —</option>
        ${cardOptions}
      </select>
      <input id="q-add-qty" type="number" step="0.01" value="1" placeholder="Cantidad" style="width:110px;padding:8px;border:1px solid #c9c2ae">
      <button class="btn btn-primary btn-sm" id="q-add-card-btn">+ Agregar</button>
    </div>
    <table class="line-table">
      <thead><tr><th>Código</th><th>Actividad</th><th style="width:70px">Unidad</th><th style="width:110px">Costo Unit.</th><th style="width:100px">Cantidad</th><th style="width:120px">Total</th><th class="no-print" style="width:36px"></th></tr></thead>
      <tbody id="q-lines-body">${lineRows}</tbody>
    </table>

    <label style="display:flex;align-items:center;gap:8px;font-size:13px;margin:18px 0 4px;justify-content:flex-end;color:#8a8478">
      <input type="checkbox" id="q-exento" style="accent-color:#8a8478" ${q.exento ? "checked" : ""}> Exento/Exonerado
    </label>
    <div class="totals-box" id="quote-totals"></div>

    <div class="editor-actions">
      <button class="btn btn-primary" id="q-save">Guardar Cotización</button>
      <button class="btn btn-amber" id="q-refresh">🔄 Actualizar precios</button>
      <button class="btn btn-print" id="q-print">🖨 Imprimir / Guardar PDF</button>
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
    syncTopFieldsToQuote();
    const qty = parseFloat(document.getElementById("q-add-qty").value) || 1;
    q.lines.push({ _key: uid(), cost_card_id: parseInt(sel.value), quantity: qty });
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
      syncTopFieldsToQuote();
      q.lines = q.lines.filter(l => l._key !== key);
      renderQuoteEditor();
    });
  });

  document.getElementById("q-cancel").addEventListener("click", loadQuoteList);
  document.getElementById("q-save").addEventListener("click", saveQuote);
  document.getElementById("q-print").addEventListener("click", () => window.print());
  document.getElementById("q-refresh").addEventListener("click", refreshQuoteFromCatalog);
  document.getElementById("q-exento").addEventListener("change", updateQuoteTotals);
  const delBtn = document.getElementById("q-delete");
  if (delBtn) delBtn.addEventListener("click", async () => {
    if (!confirm(`¿Mover la cotización "${editingQuote.name}" a la papelera? Podrás restaurarla después desde 🗑 Papelera.`)) return;
    await api.del(`/api/quotes/${editingQuote.id}`);
    loadQuoteList();
  });
}

function updateQuoteTotals() {
  const q = editingQuote;
  const subtotal = q.lines.reduce((s, l) => {
    const card = costCardsCache.find(c => c.id == l.cost_card_id);
    return s + (card ? card.total_cost : 0) * (l.quantity || 0);
  }, 0);
  const exento = document.getElementById("q-exento")?.checked || false;
  const isvAmount = exento ? 0 : subtotal * 0.15;
  const grand = subtotal + isvAmount;

  document.getElementById("quote-totals").innerHTML = `
    <div class="totals-row"><strong>Subtotal</strong><strong>${fmt(subtotal)}</strong></div>
    <div class="totals-row"><span>ISV (15%)</span><span>${exento ? "Exento" : fmt(isvAmount)}</span></div>
    <div class="totals-row grand"><span>Total</span><span>${fmt(grand)}</span></div>
  `;
}

async function saveQuote() {
  const q = editingQuote;
  const body = {
    name: document.getElementById("q-name").value,
    client: document.getElementById("q-client").value,
    date: document.getElementById("q-date").value,
    exento: document.getElementById("q-exento").checked,
    lines: q.lines.map(l => ({ cost_card_id: l.cost_card_id, quantity: l.quantity })),
  };
  if (!body.name) { alert("El proyecto necesita un nombre."); return; }
  if (q.id) await api.put(`/api/quotes/${q.id}`, body);
  else await api.post("/api/quotes", body);
  loadQuoteList();
}

async function loadAccountInfo() {
  try {
    const res = await fetch("/api/me");
    const me = await res.json();
    const el = document.getElementById("topbarClient");
    if (el) el.textContent = me.authenticated ? (me.company_name || "—") : "—";
  } catch (e) {
    // non-fatal — leave the placeholder
  }
}

// ============================================================================
// Init
// ============================================================================

loadAccountInfo();
loadQuoteList();
