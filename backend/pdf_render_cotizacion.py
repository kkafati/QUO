"""
Server-side PDF generation for Cotización Clásica, using WeasyPrint.

This is a clone of pdf_render.py's Factura Clásica template, adapted for
quotes rather than tax invoices. Differences from the Factura Clásica
template:

1. "FACTURA" -> "COTIZACIÓN"
2. Invoice-style long SAR number -> a plain 6-digit Cotización number
3. "Total (en letras)" box -> "Nota" box: same width, ~20% taller baseline,
   and grows further for multi-line notes instead of being sized for a
   fixed one-or-two-line amount-in-words string
4. No. Correlativo (exempt-refs) table removed entirely - that section only
   applies to tax-exempt invoice line items, which don't exist on a quote
5. RTN / Fecha Límite de Emisión / Rango Autorizado / Original-Copia footer
   removed, along with the "La factura es beneficio..." tagline - both are
   invoice-specific SAR requirements that don't apply to a quote
6. The C.A.I. row is replaced with the company's own RTN, since a quote
   has no CAI (that's an invoice authorization number, not applicable
   until the quote becomes a real invoice)

Everything else (header, client/date, item table, Sub-Total breakdown)
mirrors the Factura Clásica template intentionally, since the request was
for a matching visual format.
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
    e.g. 1875.97 -> '1,875.97'."""
    try:
        return "{:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "0.00"


def _cotizacion_numero(value):
    """Cotización numbers are plain 6-digit, zero-padded - not the long
    SAR invoice format (000-001-01-00000452)."""
    try:
        return "{:06d}".format(int(value))
    except (TypeError, ValueError):
        # Already a pre-formatted string (or unexpected input) - fall back
        # to left-padding whatever digits we can find, so this never blows
        # up rendering a quote just because of an odd numero value.
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        return digits.zfill(6)[-6:] if digits else "000000"


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

COTIZACION_PDF_TEMPLATE = """
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
  .contact-icon { width: 16px; height: 16px; border-radius: 50%; background: #4e5152; color: #fff;
                   display: flex; align-items: center; justify-content: center; font-size: 8px; flex-shrink: 0; }
  .fhead-right { text-align: right; }
  .factura-title { font-family: 'Audiowide', sans-serif; font-size: 26pt; font-weight: 400; letter-spacing: 0.03em; color: #4e5152; margin: 0; }
  .factura-numero { font-family: 'Ubuntu', sans-serif; font-size: 12pt; margin-top: 4px; color: #000; }

  .info-labels-row { display: flex; justify-content: space-between; font-size: 8pt; font-weight: 300;
                      text-transform: uppercase; color: #6D7075; letter-spacing: 0.06em; }
  .info-rule { border: none; border-top: 2.5px solid #c9ced3; margin: 4px 0; }
  .info-values-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
  .cliente-nombre { font-size: 12pt; text-transform: uppercase; color: #000; }
  .cliente-rtn { font-size: 9pt; margin-top: 2px; color: #000; }
  .fecha-value { font-size: 12pt; text-align: right; color: #000; }

  .term-row { text-align: right; font-size: 8pt; margin-bottom: 4px; color: #4e5152; }
  .term-row .tp-label { color: #065dac; font-weight: 500; }
  .tp-check { display: inline-block; width: 15px; height: 15px; border: 1.5px solid #065dac; border-radius: 4px;
              text-align: center; line-height: 9px; font-size: 12px; font-weight: 600; color: #000; margin: 1px 3px 0 8px; vertical-align: middle; }

  .cai-row { text-align: right; font-size: 8pt; font-family: 'Ubuntu', sans-serif; font-weight: 200; }
  .term-cai-divider { border: none; border-top: 2px solid #065dac; width: 50%; margin: 4px 0 4px auto; }

  .items-wrapper { flex: 1; display: flex; flex-direction: column; margin-top: 6px; }
  table.items { width: 100%; border-collapse: collapse; font-size: 9pt; table-layout: fixed; }
  table.items thead th { background: #4e5152; color: #fff; font-size: 7pt; text-transform: uppercase;
                          padding: 8px 10px; text-align: center; white-space: nowrap; border-right: 1px solid rgba(255,255,255,0.25); }
  table.items thead th:last-child { border-right: none; }
  table.items td { padding: 6px 10px; border-right: 1px solid #e3e5e8; vertical-align: top; color: #000; }
  table.items td:first-child { border-left: 1px solid #e3e5e8; }
  table.items td:last-child { border-right: 1px solid #e3e5e8; }
  table.items td.num { text-align: right; white-space: nowrap; }
  .items-spacer { flex: 1; display: flex; }
  .items-spacer .sp-col { border-right: 1px solid #e3e5e8; }
  .items-spacer .sp-col:first-child { border-left: 1px solid #e3e5e8; }
  .items-spacer .sp-col:last-child { border-right: 1px solid #e3e5e8; }

  .pre-totals-rule { border: none; border-top: 4px solid #4e5152; margin: 2px 0 0; }
  .totals-section { display: flex; justify-content: space-between; margin-top: 14px; gap: 20px; }
  .totals-left-col { flex: 1; min-width: 0; }

  /* Nota box: same width as before (letras-box), ~20% taller baseline via
     min-height, and grows further for genuinely long multi-line notes
     since there's no max-height capping it. */
  .nota-box { display: flex; border: 1px solid #dde1e5; overflow: hidden; margin-bottom: 12px; min-height: 60px; }
  .nota-label { background: #065dac; color: #fff; font-size: 8pt; text-align: center; padding: 10px; width: 80px;
                flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
  .nota-value { padding: 8px 10px; font-size: 8pt; color: #000; white-space: pre-wrap; align-self: center; }

  .totals-table { width: 220px; flex-shrink: 0; font-size: 10pt; }
  .trow { display: flex; justify-content: flex-end; align-items: baseline; padding: 5px 0; gap: 6px; }
  .trow .tlabel { color: #6D7075; font-size: 7pt; text-align: right; flex: 1; }
  .trow .tvalue-wrap { display: flex; justify-content: flex-end; align-items: baseline; gap: 3px; min-width: 78px; color: #000; }
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
      <div class="factura-title">COTIZACIÓN</div>
      <div class="factura-numero">{{ cotizacion.numero_display }}</div>
    </div>
  </div>

  <div class="info-labels-row"><div>CLIENTE</div><div>FECHA</div></div>
  <hr class="info-rule">
  <div class="info-values-row">
    <div>
      <div class="cliente-nombre">{{ cotizacion.cliente_nombre }}</div>
      <div class="cliente-rtn">RTN: {{ cotizacion.cliente_rtn or "" }}</div>
    </div>
    <div class="fecha-value">{{ cotizacion.fecha }}</div>
  </div>

  <div class="term-row">
    <span class="tp-label">Término de Pago</span>
    <span class="tp-check">{{ "X" if cotizacion.termino_pago == "credito" else "" }}</span>Crédito
    <span class="tp-check">{{ "X" if cotizacion.termino_pago == "contado" else "" }}</span>Contado
  </div>

  <hr class="term-cai-divider">
  <div class="cai-row">RTN {{ account.tax_id or "—" }}</div>

  <div class="items-wrapper">
    <table class="items">
      <thead><tr>
        <th style="width:55px">Cantidad</th><th>Descripción</th>
        <th class="num" style="width:125px">Precio Unitario</th><th class="num" style="width:115px">Total</th>
      </tr></thead>
      <tbody>
        {% for line in cotizacion.lines %}
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
      <div class="sp-col" style="width:55px"></div>
      <div class="sp-col" style="flex:1"></div>
      <div class="sp-col" style="width:125px"></div>
      <div class="sp-col" style="width:115px"></div>
    </div>
  </div>

  <hr class="pre-totals-rule">

  <div class="totals-section">
    <div class="totals-left-col">
      <div class="nota-box">
        <div class="nota-label">Nota</div>
        <div class="nota-value">{{ cotizacion.nota or "" }}</div>
      </div>
    </div>
    <div class="totals-table">
      <div class="trow"><span class="tlabel">Sub-Total</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.subtotal) }}</span></span></div>
      <div class="trow"><span class="tlabel">Descuentos y Rebajas</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.descuentos) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exonerado</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.importe_exonerado) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exento</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.importe_exento) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.importe_gravado_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.importe_gravado_18) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.isv_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.isv_18) }}</span></span></div>
      <div class="trow grand"><span class="tlabel">Total a Pagar</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(cotizacion.total_a_pagar) }}</span></span></div>
    </div>
  </div>

</body>
</html>
"""


def render_cotizacion_pdf(cotizacion_dict, account):
    """cotizacion_dict: same shape as compute_invoice_totals()'s output, plus
    a 'nota' field instead of 'total_en_letras' / exempt-refs fields.
    account: Account model instance."""
    display_cot = dict(cotizacion_dict)
    raw_fecha = display_cot.get("fecha") or ""
    try:
        y, m, d = raw_fecha.split("-")
        display_cot["fecha"] = f"{d}/{m}/{y}"
    except (ValueError, AttributeError):
        pass  # leave as-is if it's not in the expected YYYY-MM-DD shape

    display_cot["numero_display"] = _cotizacion_numero(display_cot.get("numero"))

    html_string = render_template_string(
        COTIZACION_PDF_TEMPLATE,
        cotizacion=display_cot,
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
