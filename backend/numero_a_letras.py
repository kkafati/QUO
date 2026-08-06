"""Converts a monetary amount into Spanish words, Honduras invoice format:
'DOCE MIL TRESCIENTOS CUARENTA Y CINCO LEMPIRAS CON 67/100'
"""

UNIDADES = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
DIEZ_DIECINUEVE = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS",
                    "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
DECENAS = ["", "", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
            "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _tres_digitos(n):
    """Convert a 0-999 integer to Spanish words."""
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    c, resto = divmod(n, 100)
    partes = []
    if c:
        partes.append(CENTENAS[c])
    if resto:
        if resto < 10:
            partes.append(UNIDADES[resto])
        elif resto < 20:
            partes.append(DIEZ_DIECINUEVE[resto - 10])
        else:
            d, u = divmod(resto, 10)
            if d == 2 and u > 0:
                partes.append("VEINTI" + UNIDADES[u])
            else:
                if u:
                    partes.append(DECENAS[d] + " Y " + UNIDADES[u])
                else:
                    partes.append(DECENAS[d])
    return " ".join(partes)


def _entero_a_letras(n):
    if n == 0:
        return "CERO"
    millones, resto = divmod(n, 1_000_000)
    miles, cientos = divmod(resto, 1000)
    partes = []
    if millones:
        if millones == 1:
            partes.append("UN MILLON")
        else:
            partes.append(_tres_digitos(millones) + " MILLONES")
    if miles:
        if miles == 1:
            partes.append("MIL")
        else:
            partes.append(_tres_digitos(miles) + " MIL")
    if cientos:
        partes.append(_tres_digitos(cientos))
    return " ".join(partes)


def numero_a_letras(monto, moneda="LEMPIRAS"):
    monto = round(float(monto) + 1e-9, 2)
    entero = int(monto)
    centavos = round((monto - entero) * 100)
    if centavos == 100:
        entero += 1
        centavos = 0
    letras = _entero_a_letras(entero)
    return f"{letras} {moneda} CON {centavos:02d}/100"
