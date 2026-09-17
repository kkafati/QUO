# Cómo restaurar la base de datos de QUO

Guía de emergencia. Si estás leyendo esto porque algo salió mal con la base
de datos real, sigue los pasos en orden, sin saltarte nada.

## 1. Dónde están los respaldos

Hay dos copias posibles del respaldo:

- **Respaldo local** (en esta misma computadora):
  `C:\Users\kamel\Desktop\QUO\backend\backups\local\`
  Ahí vas a ver archivos como `quoting_2026-09-16_0300.db` — uno por día
  (más antiguos que 30 días se guardan solo uno por semana).

- **Respaldo en USB** (la unidad externa designada como respaldo):
  Conecta la unidad USB de respaldo. Si tiene un archivo llamado
  `QUO_BACKUP_DRIVE.txt` en la raíz, es la unidad correcta. Dentro de esa
  unidad, busca la carpeta `backups\` — ahí están los mismos archivos que en
  el respaldo local, copiados desde ahí.

Usa el respaldo en USB si la computadora se dañó, se perdió, o el disco
local también se vio afectado. Si solo la base de datos se corrompió pero la
computadora está bien, el respaldo local normalmente basta y es más rápido.

## 2. Cómo saber cuál respaldo usar (el más reciente que esté BIEN, no solo el más reciente)

**No asumas que el archivo con la fecha más nueva está bueno.** Cada vez que
corre el respaldo, se anota una línea en:

`C:\Users\kamel\Desktop\QUO\backend\backups\backup_log.txt`

Abre ese archivo con el Bloc de Notas. Cada línea es un respaldo, con el
formato `timestamp=... | local_status=ok|error | local_integrity=ok|... | ...`.

- Busca la línea con la fecha/hora más reciente que tenga `local_status=ok`
  **y** `local_integrity=ok`.
- El nombre del archivo que corresponde a esa línea es
  `quoting_<fecha>_<hora>.db` (la fecha/hora está en el mismo timestamp de
  la línea, con el formato `AAAA-MM-DD_HHMM`).
- Si la línea más reciente dice `local_status=error` o
  `local_integrity` es cualquier cosa distinta de `ok` — **no uses ese
  archivo**. Sigue subiendo por el log hasta encontrar la última línea buena,
  y usa el archivo que corresponde a esa.

Ejemplo: si el log dice...
```
timestamp=2026-09-14T03:00:05|local_status=ok|local_integrity=ok|...
timestamp=2026-09-15T03:00:04|local_status=ok|local_integrity=ok|...
timestamp=2026-09-16T03:00:07|local_status=ok|local_integrity=*** in database main ***...
```
...el respaldo del 16 salió corrupto. Usa el del **15 de septiembre**, no el
del 16, aunque el del 16 sea el más nuevo.

Si vas a restaurar desde la unidad USB en vez del disco local, el
razonamiento es el mismo, pero el archivo puede no ser el más reciente que
aparece en `backup_log.txt` — la unidad USB solo tiene lo que se alcanzó a
copiar la última vez que estuvo conectada. Revisa qué archivos existen
realmente dentro de la carpeta `backups\` de la unidad USB y elige el más
reciente de ESOS que además tenga `local_integrity=ok` en el log (el log
sigue siendo la referencia de cuáles archivos pasaron la prueba de
integridad, sin importar si terminaron en el disco local o en el USB — son
copias idénticas del mismo archivo).

## 3. Pasos para restaurar

1. **Detén la aplicación.** Si está corriendo como una ventana de consola,
   ciérrala (o presiona Ctrl+C en esa ventana). Si corre como tarea
   programada/servicio de Waitress, deténlo desde el Administrador de
   Tareas o el Programador de Tareas antes de continuar. Es importante que
   nadie esté usando el sistema mientras restauras.

2. **No borres la base de datos actual — muévela a un lado.** En
   `C:\Users\kamel\Desktop\QUO\backend\`, busca el archivo `quoting.db`.
   Renómbralo (por ejemplo, a `quoting_antes_de_restaurar.db`) o muévelo a
   otra carpeta. Esto es tu red de seguridad: si algo sale mal en el paso
   siguiente, todavía tienes el archivo original con el que empezaste, sin
   importar qué tan dañado esté.

3. **Copia el respaldo elegido a su lugar, con el nombre correcto.** Copia
   el archivo `.db` que identificaste en el paso 2 de esta guía hacia
   `C:\Users\kamel\Desktop\QUO\backend\`, y **renómbralo exactamente a
   `quoting.db`** (sin la fecha en el nombre). La aplicación solo reconoce
   ese nombre de archivo — si lo dejas con el nombre del respaldo
   (`quoting_2026-09-15_0300.db`), la aplicación no lo va a usar.

4. **Reinicia la aplicación.** Vuelve a iniciarla de la forma normal
   (doble clic al acceso directo, o volviendo a correr `app.py` con
   Waitress, según cómo se inicie normalmente en esta computadora).

5. **Verifica que todo se ve bien.** Inicia sesión y revisa que las
   facturas, clientes, y demás datos recientes estén ahí y se vean
   correctos. Si el respaldo que usaste es de hace más de un día, es normal
   que falte lo capturado ese último día — anticipa volver a ingresar
   manualmente cualquier factura, gasto, o movimiento de inventario hecho
   entre la fecha del respaldo y el momento del problema.

## 4. Si algo en esta guía no funcionó como está escrito

Si seguiste un paso y no funcionó tal como se describe aquí, es un error en
esta guía, no en tu forma de seguirla — corrige este archivo para la
próxima persona (o la próxima vez que lo necesites tú mismo bajo presión).

## Referencia rápida: cómo se generan los respaldos

(Para quien quiera entender el sistema completo, no es necesario para
restaurar.)

- Todos los días a las 3:00 AM corre automáticamente una tarea programada
  de Windows llamada **"QUO - Respaldo Diario de Base de Datos"**, que
  ejecuta `backend/scripts/backup_db.py`. Esto crea el respaldo local y,
  si la unidad USB de respaldo está conectada en ese momento, también la
  actualiza.
- Si conectas la unidad USB de respaldo en otro momento del día y quieres
  actualizarla de inmediato sin esperar a las 3:00 AM del día siguiente,
  abre una terminal en `backend\scripts\` y corre:
  `python backup_db.py --usb-now`
- Los respaldos locales se conservan: todos los diarios de los últimos 30
  días, luego uno por semana hasta los 3 meses, y se eliminan después de
  eso.
