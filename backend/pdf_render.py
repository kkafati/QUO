"""
Server-side PDF generation for Facturación, using WeasyPrint.

This renders a STATIC snapshot of an invoice from its already-saved data -
no JavaScript, no editing. It deliberately does not reuse the interactive
ver.html template (which depends on client-side search, auto-grow textareas,
and live totals calculation that have no meaning at PDF-render time).

Fonts are self-hosted (facturacion/fonts/) rather than pulled from Google
Fonts at render time - WeasyPrint has no browser cache to rely on, and the
live server may not even have outbound internet access at the moment someone
generates a PDF, so a CDN dependency here would be fragile in production.

Phase 1 scope: Clásica only, proving the pipeline works end-to-end.
"""
import os
from flask import render_template_string
from weasyprint import HTML

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "facturacion", "fonts")


def _font_url(filename):
    """Absolute file:// URL so WeasyPrint can resolve the font regardless of
    the process's current working directory (matters across Windows/Linux,
    and across dev vs. the live deployment)."""
    path = os.path.join(FONTS_DIR, filename).replace("\\", "/")
    return f"file:///{path.lstrip('/')}" if not path.startswith("/") else f"file://{path}"


def _money(value):
    """Format like the web page's fmt(): thousand separators + 2 decimals,
    e.g. 1875.97 -> '1,875.97'. Jinja's %-style format filter doesn't do
    this, so this is passed into the template as a callable instead."""
    try:
        return "{:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "0.00"


GLOBE_ICON_SVG = """<svg viewBox="0 0 100 100" width="11" height="11" style="display:block">
  <g fill="none" stroke="#fff" stroke-width="7">
    <circle cx="50" cy="50" r="45"/>
    <line x1="6" y1="38" x2="94" y2="38"/>
    <line x1="6" y1="66" x2="94" y2="66"/>
    <path d="M50,5 C25,25 25,75 50,95" />
    <path d="M50,5 C75,25 75,75 50,95" />
  </g>
  <text x="50" y="58" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="800" fill="#fff">WWW</text>
</svg>"""

INVOICE_PDF_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<style>
  @font-face { font-family: 'Ubuntu'; src: url('{{ font_ubuntu_300 }}') format('woff2'); font-weight: 300; }
  @font-face { font-family: 'Ubuntu'; src: url('{{ font_ubuntu_400 }}') format('woff2'); font-weight: 400; }
  @font-face { font-family: 'Ubuntu'; src: url('{{ font_ubuntu_700 }}') format('woff2'); font-weight: 700; }
  @font-face { font-family: 'Audiowide'; src: url('{{ font_audiowide }}') format('woff2'); font-weight: 400; }
  @font-face { font-family: 'PT Sans'; src: url('{{ font_ptsans }}') format('woff2'); font-weight: 400; }

  @page { size: letter; margin: 0.5in; }
  * { box-sizing: border-box; }
  body { font-family: 'Ubuntu', sans-serif; color: #16232f; margin: 0; font-size: 10pt;
         display: flex; flex-direction: column; min-height: 10in; }

  .fhead { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
  .fhead-left { display: flex; align-items: flex-start; gap: 14px; }
  .fhead-logo { width: 100px; }
  .contact-list { margin-top: 4px; }
  .contact-row { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; font-family: 'PT Sans', sans-serif; font-size: 6pt; color: #333; }
  .contact-icon { width: 16px; height: 16px; border-radius: 50%; background: #39454A; color: #fff;
                   display: flex; align-items: center; justify-content: center; font-size: 8px; flex-shrink: 0; }
  .fhead-right { text-align: right; }
  .factura-title { font-family: 'Audiowide', sans-serif; font-size: 26pt; font-weight: 400; letter-spacing: 0.03em; color: #39454A; margin: 0; }
  .factura-numero { font-family: 'Ubuntu', sans-serif; font-size: 12pt; margin-top: 4px; color: #000; }

  .info-labels-row { display: flex; justify-content: space-between; font-size: 8pt; font-weight: 300;
                      text-transform: uppercase; color: #6D7075; letter-spacing: 0.06em; }
  .info-rule { border: none; border-top: 2.5px solid #c9ced3; margin: 4px 0; }
  .info-values-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
  .cliente-nombre { font-size: 12pt; text-transform: uppercase; color: #000; }
  .cliente-rtn { font-size: 9pt; margin-top: 2px; color: #000; }
  .fecha-value { font-size: 12pt; text-align: right; color: #000; }

  .term-row { text-align: right; font-size: 8pt; margin-bottom: 4px; color: #39454A; }
  .term-row .tp-label { color: #065dac; font-weight: 700; }
  .tp-check { display: inline-block; width: 11px; height: 11px; border: 1.5px solid #065dac; border-radius: 3px;
              text-align: center; line-height: 9px; font-size: 8px; font-weight: 800; color: #000; margin: 0 3px 0 8px; vertical-align: middle; }

  .cai-row { text-align: right; font-size: 8pt; font-family: 'Ubuntu', sans-serif; font-weight: 300; }
  .term-cai-divider { border: none; border-top: 2px solid #065dac; width: 50%; margin: 4px 0 0 auto; }

  .items-wrapper { flex: 1; display: flex; flex-direction: column; margin-top: 6px;
                    border-left: 1px solid #e3e5e8; border-right: 1px solid #e3e5e8; }
  table.items { width: 100%; border-collapse: collapse; font-size: 9pt; table-layout: fixed; }
  table.items thead th { background: #555859; color: #fff; font-size: 7pt; text-transform: uppercase;
                          padding: 8px 10px; text-align: center; white-space: nowrap; border-right: 1px solid rgba(255,255,255,0.25); }
  table.items thead th:last-child { border-right: none; }
  table.items td { padding: 6px 10px; border-right: 1px solid #e3e5e8; vertical-align: top; color: #000; }
  table.items td:last-child { border-right: none; }
  table.items td.num { text-align: right; }
  .items-spacer { flex: 1; display: flex; }
  .items-spacer .sp-col { border-right: 1px solid #e3e5e8; }
  .items-spacer .sp-col:last-child { border-right: none; }

  .pre-totals-rule { border: none; border-top: 2.5px solid #6b7480; margin: 4px 0 0; }
  .totals-section { display: flex; justify-content: space-between; margin-top: 14px; gap: 20px; }
  .totals-left-col { flex: 1; }
  .letras-box { display: flex; border: 1px solid #dde1e5; border-radius: 0 4px 4px 0; overflow: hidden; margin-bottom: 12px; }
  .letras-label { background: #065dac; color: #fff; font-size: 8pt; text-align: center; padding: 10px; width: 80px; flex-shrink: 0; }
  .letras-value { padding: 8px 10px; font-size: 8pt; color: #000; }

  .exempt-refs { display: grid; grid-template-columns: max-content 1fr; align-items: center; font-size: 6.5pt; border: 1px solid #dde1e5; margin-bottom: 12px; line-height: 1.5; }
  .exempt-refs .elabel { padding: 5px 8px; border-bottom: 1px solid #dde1e5; text-align: center; white-space: nowrap; }
  .exempt-refs .evalue { padding: 5px 8px; border-left: 1px solid #dde1e5; border-bottom: 1px solid #dde1e5; }
  .exempt-refs .erow-last .elabel, .exempt-refs .erow-last .evalue { border-bottom: none; }

  .foot-lines { font-size: 9pt; font-weight: 300; line-height: 1.7; }
  .foot-lines .bold { font-weight: 700; }
  .foot-tagline { text-align: center; font-size: 9pt; margin-top: 10px; }

  .totals-table { width: 220px; flex-shrink: 0; font-size: 10pt; }
  .trow { display: flex; justify-content: flex-end; align-items: baseline; padding: 5px 0; gap: 10px; }
  .trow .tlabel { color: #6D7075; font-size: 7pt; text-align: right; flex: 1; }
  .trow .tvalue-wrap { display: flex; justify-content: space-between; width: 76px; color: #000; }
  .trow.grand { border-bottom: 2px solid #065dac; margin-top: 6px; padding-bottom: 8px; font-weight: 700; }
</style>
</head>
<body>

  <div class="fhead">
    <div class="fhead-left">
      {% if account.logo_data_url %}<img class="fhead-logo" src="{{ account.logo_data_url }}">{% endif %}
      <div class="contact-list">
        <div class="contact-row"><span class="contact-icon">&#9742;</span> {{ account.phone or "—" }}</div>
        <div class="contact-row"><span class="contact-icon" style="font-size:10px">&#9993;</span> {{ account.email or "—" }}</div>
        <div class="contact-row"><span class="contact-icon" style="font-size:13px">&#8962;</span> {{ account.address or "—" }}</div>
        <div class="contact-row"><span class="contact-icon">{{ globe_svg | safe }}</span> {{ account.website or "—" }}</div>
      </div>
    </div>
    <div class="fhead-right">
      <div class="factura-title">FACTURA</div>
      <div class="factura-numero">{{ invoice.numero }}</div>
    </div>
  </div>

  <div class="info-labels-row"><div>CLIENTE</div><div>FECHA</div></div>
  <hr class="info-rule">
  <div class="info-values-row">
    <div>
      <div class="cliente-nombre">{{ invoice.cliente_nombre }}</div>
      <div class="cliente-rtn">RTN: {{ invoice.cliente_rtn or "" }}</div>
    </div>
    <div class="fecha-value">{{ invoice.fecha }}</div>
  </div>

  <div class="term-row">
    <span class="tp-label">Término de Pago</span>
    <span class="tp-check">{{ "X" if invoice.termino_pago == "credito" else "" }}</span>Crédito
    <span class="tp-check">{{ "X" if invoice.termino_pago == "contado" else "" }}</span>Contado
  </div>

  <hr class="term-cai-divider">
  <div class="cai-row">C.A.I. {{ account.cai or "—" }}</div>

  <div class="items-wrapper">
    <table class="items">
      <thead><tr>
        <th style="width:60px">Cantidad</th><th>Descripción</th>
        <th class="num" style="width:100px">Precio Unitario</th><th class="num" style="width:90px">Total</th>
      </tr></thead>
      <tbody>
        {% for line in invoice.lines %}
        <tr>
          <td>{{ "%g"|format(line.cantidad) }}</td>
          <td style="white-space: pre-wrap;">{{ line.descripcion }}</td>
          <td class="num">L. {{ money(line.precio_unitario) }}</td>
          <td class="num">L. {{ money(line.total) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <div class="items-spacer">
      <div class="sp-col" style="width:60px"></div>
      <div class="sp-col" style="flex:1"></div>
      <div class="sp-col" style="width:100px"></div>
      <div class="sp-col" style="width:90px"></div>
    </div>
  </div>

  <hr class="pre-totals-rule">

  <div class="totals-section">
    <div class="totals-left-col">
      <div class="letras-box">
        <div class="letras-label">Total<br>(en letras)</div>
        <div class="letras-value">{{ invoice.total_en_letras }}</div>
      </div>
      <div class="exempt-refs">
        <div class="elabel">No. Correlativo de Orden de Compra Exenta</div><div class="evalue">{{ invoice.orden_compra_exenta or "" }}</div>
        <div class="elabel">No. Correlativo de Constancia de Registro Exonerado</div><div class="evalue">{{ invoice.constancia_registro_exonerado or "" }}</div>
        <div class="elabel erow-last">No. de Registro de la SAG</div><div class="evalue erow-last">{{ invoice.registro_sag or "" }}</div>
      </div>
      <div class="foot-lines">
        <div><span class="bold">RTN</span> {{ account.tax_id or "—" }}</div>
        <div><span class="bold">Fecha Límite de Emisión:</span> {{ account.cai_fecha_limite or "—" }}</div>
        <div><span class="bold">Rango Autorizado:</span> {{ account.rango_autorizado_desde or "—" }} al {{ account.rango_autorizado_hasta or "—" }}</div>
        <div><span class="bold">Original Blanca:</span> Cliente &nbsp;<span class="bold">Copia Amarilla:</span> Administración &nbsp;<span class="bold">Copia Azul:</span> Contabilidad</div>
      </div>
    </div>
    <div class="totals-table">
      <div class="trow"><span class="tlabel">Sub-Total</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.subtotal) }}</span></span></div>
      <div class="trow"><span class="tlabel">Descuentos y Rebajas</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.descuentos) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exonerado</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.importe_exonerado) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exento</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.importe_exento) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.importe_gravado_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.importe_gravado_18) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.isv_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.isv_18) }}</span></span></div>
      <div class="trow grand"><span class="tlabel">Total a Pagar</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(invoice.total_a_pagar) }}</span></span></div>
    </div>
  </div>

  <div class="foot-tagline">La factura es beneficio de todos "Exíjala"</div>

</body>
</html>
"""


def render_invoice_pdf(invoice_dict, account):
    """invoice_dict: output of compute_invoice_totals(). account: Account model instance."""
    display_invoice = dict(invoice_dict)
    raw_fecha = display_invoice.get("fecha") or ""
    try:
        y, m, d = raw_fecha.split("-")
        display_invoice["fecha"] = f"{d}/{m}/{y}"
    except (ValueError, AttributeError):
        pass  # leave as-is if it's not in the expected YYYY-MM-DD shape

    html_string = render_template_string(
        INVOICE_PDF_TEMPLATE,
        invoice=display_invoice,
        account=account,
        globe_svg=GLOBE_ICON_SVG,
        money=_money,
        font_ubuntu_300=_font_url("ubuntu-300.woff2"),
        font_ubuntu_400=_font_url("ubuntu-400.woff2"),
        font_ubuntu_700=_font_url("ubuntu-700.woff2"),
        font_audiowide=_font_url("audiowide-400.woff2"),
        font_ptsans=_font_url("pt-sans-400.woff2"),
    )
    return HTML(string=html_string).write_pdf()
