# Edición pública anonimizada

Se conservaron los dos documentos Markdown y se excluyeron las **18 capturas PNG originales**. Cada captura tiene una nota nueva en `capturas/`; los enlaces de los documentos apuntan a estas notas. No se incluyen imágenes, metadatos de imágenes ni mapas de valores originales.

## Qué se reemplazó

| Categoría | Valores originales distintos | Apariciones sustituidas |
|---|---:|---:|
| Endpoints de recursos | 3 | 4 |
| IDs de recursos (incluida AMI) | 4 | 7 |
| Nombres de recursos y reglas propias | 11 | 34 |
| Fragmentos de JWT | 1 | 4 |
| Direcciones IP de recursos o clientes | 3 | 5 |
| Región y zonas completas | 3 | 9 |
| Ruta de recurso de aplicación | 1 | 1 |

Los recuentos corresponden a sustituciones exactas en texto, después de separar las referencias a imágenes. Las abreviaturas de zonas y las indicaciones sobre evidencias se ajustaron adicionalmente. Se mantuvieron los nombres públicos de servicios, reglas administradas, imágenes de contenedor y enlaces públicos de documentación; no identifican la cuenta del laboratorio. `0.0.0.0/0` se conserva porque es una regla de red genérica, no una dirección del titular.

## Uso

- Sustituya los placeholders (por ejemplo, `<AWS_REGION>`) solo en una copia local antes de usar ejemplos. No son valores AWS válidos.
- El grupo de logs elegido debe conservar el prefijo obligatorio `aws-waf-logs-`.
- No hay proyecto ejecutable, archivos de entorno ni configuración Terraform/CloudFormation en el ZIP recibido: solo Markdown y capturas. No corresponde crear `.env.example`.
- Se añadió `.gitignore` preventivo. No elimina secretos de archivos ya rastreados ni reemplaza una revisión antes de publicar.

## Verificación y límites

Se revisó íntegramente el texto de los dos Markdown y se hizo una segunda búsqueda automática en todos los archivos finales y sus rutas: cuentas de 12 dígitos, ARN, IDs de claves y recursos, secretos/tokens, correos, JWT y endpoints vinculados al despliegue. También se contrastó la ausencia de los valores originales identificados. **Cero coincidencias sensibles en esa segunda pasada.** Los nombres y bytes del ZIP coinciden con la carpeta entregada.

No se encontraron en los Markdown cuentas de 12 dígitos, ARN, access keys, secret access keys ni session tokens AWS completos. Los fragmentos JWT sí se sustituyeron. No se inventarió el contenido visual de las capturas: se excluyeron todas de forma conservadora, incluida cualquier información no detectada visualmente. Por ello se pierde la evidencia visual original.

El contenido técnico, resultados, costos y afirmaciones históricas del laboratorio se conservaron; esta tarea no los valida ni ejecuta recursos AWS. No puede garantizarse detectar cualquier secreto arbitrario mediante patrones. Si alguna credencial estuvo expuesta antes, elimine su exposición y rótela en AWS; anonimizar esta copia no la revoca ni limpia un historial Git anterior.
