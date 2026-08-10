"""
Server-side PDF generation for Factura Proforma, using WeasyPrint.

This is a clone of pdf_render.py's Factura Clásica template. Differences:

1. No invoice numbering - a Proforma isn't a real, SAR-numbered tax
   document. "PROFORMA" is shown below the "FACTURA" title instead
   (right-justified, Audiowide 16pt, same color as the title).
2. Total (en letras) box - kept, same as Factura Clásica.
3. No. Correlativo table - kept, same as Factura Clásica.
4. RTN / Fecha Límite de Emisión / Rango Autorizado / Original-Copia footer,
   and the "La factura es beneficio..." tagline - both removed (those are
   specifically about a real invoice's issuance, not applicable to a
   proforma that hasn't been formally issued yet).
5. C.A.I. row - kept, same as Factura Clásica.
"""
import os
from flask import render_template_string
from weasyprint import HTML

FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "facturacion", "fonts")


def _font_url(filename):
    path = os.path.join(FONTS_DIR, filename).replace("\\", "/")
    return f"file:///{path.lstrip('/')}" if not path.startswith("/") else f"file://{path}"


def _money(value):
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

PROFORMA_PDF_TEMPLATE = """
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
  .proforma-label { font-family: 'Audiowide', sans-serif; font-size: 16pt; font-weight: 400; letter-spacing: 0.03em; color: #4e5152; margin-top: 4px; text-align: right; }

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
  .letras-box { display: flex; border: 1px solid #dde1e5; overflow: hidden; margin-bottom: 12px; }
  .letras-label { background: #065dac; color: #fff; font-size: 8pt; text-align: center; padding: 10px; width: 80px; flex-shrink: 0; }
  .letras-value { padding: 8px 10px; font-size: 8pt; color: #000; }

  .exempt-refs { display: grid; grid-template-columns: max-content 1fr; align-items: center; font-size: 6.5pt; border: 1px solid #dde1e5; margin-bottom: 12px; line-height: 1.5; overflow: hidden; }
  .exempt-refs .elabel { padding: 5px 8px; border-bottom: 1px solid #dde1e5; text-align: center; white-space: nowrap; }
  .exempt-refs .evalue { padding: 5px 8px; min-height: 1.5em; border-left: 1px solid #dde1e5; border-bottom: 1px solid #dde1e5; }
  .exempt-refs .erow-last .elabel, .exempt-refs .erow-last .evalue { border-bottom: none; }

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
      <div class="factura-title">FACTURA</div>
      <div class="proforma-label">PROFORMA</div>
    </div>
  </div>

  <div class="info-labels-row"><div>CLIENTE</div><div>FECHA</div></div>
  <hr class="info-rule">
  <div class="info-values-row">
    <div>
      <div class="cliente-nombre">{{ proforma.cliente_nombre }}</div>
      <div class="cliente-rtn">RTN: {{ proforma.cliente_rtn or "" }}</div>
    </div>
    <div class="fecha-value">{{ proforma.fecha }}</div>
  </div>

  <div class="term-row">
    <span class="tp-label">Término de Pago</span>
    <span class="tp-check">{{ "X" if proforma.termino_pago == "credito" else "" }}</span>Crédito
    <span class="tp-check">{{ "X" if proforma.termino_pago == "contado" else "" }}</span>Contado
  </div>

  <hr class="term-cai-divider">
  <div class="cai-row">C.A.I. {{ account.cai or "—" }}</div>

  <div class="items-wrapper">
    <table class="items">
      <thead><tr>
        <th style="width:55px">Cantidad</th><th>Descripción</th>
        <th class="num" style="width:125px">Precio Unitario</th><th class="num" style="width:115px">Total</th>
      </tr></thead>
      <tbody>
        {% for line in proforma.lines %}
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
      <div class="letras-box">
        <div class="letras-label">Total<br>(en letras)</div>
        <div class="letras-value">{{ proforma.total_en_letras }}</div>
      </div>
      <div class="exempt-refs">
        <div class="elabel">No. Correlativo de Orden de Compra Exenta</div><div class="evalue">{{ proforma.orden_compra_exenta or "&nbsp;" | safe }}</div>
        <div class="elabel">No. Correlativo de Constancia de Registro Exonerado</div><div class="evalue">{{ proforma.constancia_registro_exonerado or "&nbsp;" | safe }}</div>
        <div class="elabel erow-last">No. de Registro de la SAG</div><div class="evalue erow-last">{{ proforma.registro_sag or "&nbsp;" | safe }}</div>
      </div>
    </div>
    <div class="totals-table">
      <div class="trow"><span class="tlabel">Sub-Total</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.subtotal) }}</span></span></div>
      <div class="trow"><span class="tlabel">Descuentos y Rebajas</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.descuentos) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exonerado</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.importe_exonerado) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Exento</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.importe_exento) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.importe_gravado_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">Importe Gravado 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.importe_gravado_18) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 15%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.isv_15) }}</span></span></div>
      <div class="trow"><span class="tlabel">I.S.V. 18%</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.isv_18) }}</span></span></div>
      <div class="trow grand"><span class="tlabel">Total a Pagar</span><span class="tvalue-wrap"><span>L.</span><span>{{ money(proforma.total_a_pagar) }}</span></span></div>
    </div>
  </div>

</body>
</html>
"""


def render_proforma_pdf(proforma_dict, account):
    """proforma_dict: same shape as compute_invoice_totals()'s output.
    account: Account model instance."""
    display_pf = dict(proforma_dict)
    raw_fecha = display_pf.get("fecha") or ""
    try:
        y, m, d = raw_fecha.split("-")
        display_pf["fecha"] = f"{d}/{m}/{y}"
    except (ValueError, AttributeError):
        pass

    html_string = render_template_string(
        PROFORMA_PDF_TEMPLATE,
        proforma=display_pf,
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
