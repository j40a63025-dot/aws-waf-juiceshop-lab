# Bitácora — Laboratorio AWS WAF + OWASP Juice Shop

> **Edición anonimizada.** Los identificadores son placeholders y las capturas originales se excluyeron. Consulte [SANITIZACION.md](SANITIZACION.md) antes de reutilizar los ejemplos.


Registro crudo de la ejecución. Las conclusiones limpias van al `README.md`;
esto es el cuaderno de campo, con lo que salió bien y lo que no.

- **Fecha:** 13 de septiembre de 2026
- **Región de cómputo:** `<AWS_REGION>` (región anonimizada)
- **Alcance de la Web ACL:** CloudFront (global)
- **Cuenta:** información anonimizada; capturas originales excluidas

---

## Arquitectura

**Arquitectura final (la que funciona):**

```
Internet → ALB <AWS_ALB_NAME> (<AWS_REGION>, 3 AZ)
             └─ Web ACL regional <AWS_REGIONAL_WEB_ACL_NAME> (5 reglas)
                  ↓
           EC2 t3.micro <AWS_AVAILABILITY_ZONE_3> (Docker → Juice Shop :3000 → :80)
```

**Arquitectura inicial (descartada, ver Hallazgo 4):**

```
Internet → CloudFront (<AWS_CLOUDFRONT_DOMAIN>)
             └─ Web ACL impuesta por el plan Free (no reemplazable)
```

El laboratorio empezó sobre CloudFront y hubo que migrarlo a ALB. El motivo está
documentado abajo: el plan gratuito de CloudFront impide asociar una Web ACL propia y
restringe los tipos de inspección disponibles.

---

## Parte 1 — Origen en EC2

| Dato | Valor |
|---|---|
| Instancia | `<AWS_INSTANCE_ID>` |
| AMI | Amazon Linux 2023 (`<AWS_AMI_ID>`) |
| Tipo | t3.micro, crédito **standard** |
| DNS público | `<AWS_EC2_PUBLIC_DNS>` |
| IP pública | `<AWS_EC2_PUBLIC_IP>` |
| Par de claves | ninguno |
| IMDSv2 | obligatorio |
| Lanzamiento | 15:38:39 GMT-5 |

Despliegue vía **user data** (sin SSH):

```bash
#!/bin/bash
dnf install -y docker
systemctl enable --now docker
docker run -d --restart always -p 80:3000 bkimminich/juice-shop
```

[Captura omitida por seguridad: Juice Shop respondiendo por HTTP directo](capturas/01-juiceshop-http-directo.md)

**Notas de ejecución**

- El script pegado con indentación **no se ejecuta**: cloud-init exige `#!` en la
  posición 1 de la línea 1. Corregido antes de lanzar.
- El enlace "dirección abierta" de la consola apunta a `https://`, que siempre falla
  contra un origen que solo escucha en el 80. Hay que escribir `http://` a mano.
- Se dejó el puerto 80 abierto a `0.0.0.0/0` a propósito, para poder medir el origen
  sin protección. **Mejora pendiente:** restringirlo a la prefix list
  `com.amazonaws.global.cloudfront.origin-facing`, de forma que nadie pueda saltarse
  el WAF pegándole directo a la EC2.

---

## Parte 2 — CloudFront

| Parámetro | Valor |
|---|---|
| ID | `<AWS_CLOUDFRONT_DISTRIBUTION_ID>` |
| Dominio | `<AWS_CLOUDFRONT_DOMAIN>` |
| Origen | custom, la EC2 anterior |
| Protocolo al origen | HTTP only, puerto 80 |
| Viewer protocol | Redirect HTTP to HTTPS |
| Métodos | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| Cache policy | CachingDisabled |
| Origin request policy | **AllViewer** |
| Plan | Free |

[Captura omitida por seguridad: Revisión previa a la creación](capturas/03-cloudfront-review-create.md)

**Decisiones**

- `AllViewer` no venía en la guía original y es imprescindible: con `CachingDisabled`
  a secas, CloudFront no reenvía cookies ni encabezados al origen, así que el login de
  Juice Shop se rompe y el `User-Agent` no llega a las reglas del WAF.
- `CachingDisabled` evita que las respuestas cacheadas falseen los resultados de los
  ataques.

---

## Hallazgo 1 — CloudFront impone su propio WAF

El asistente de creación incluye un paso **"Enable security"**. Con todos los toggles
de reglas apagados, el resumen seguía marcando `Security protections: Enabled`.

[Captura omitida por seguridad: Paso de seguridad del asistente](capturas/02-cloudfront-enable-security.md)

Al entrar a editarlo después, **no existe ninguna opción para desactivarlo**: las
protecciones van atadas al plan y solo se pueden ampliar, nunca apagar.

[Captura omitida por seguridad: Sin opción de desactivar](capturas/04-security-sin-opcion-desactivar.md)

Consecuencia: antes de crear nada propio, la distribución ya tenía asociada una Web ACL
llamada `<AWS_MANAGED_WEB_ACL_NAME>` con 3 reglas.

[Captura omitida por seguridad: Web ACL heredada](capturas/06-acl-heredada-createdbycloudfront.md)

> **Lectura defensiva.** Un entorno "sin WAF" ya no existe por defecto en CloudFront.
> Cualquier medición de línea base tiene que declarar qué protecciones base estaban
> activas, o las conclusiones no son reproducibles.

---

## Parte 3 — Línea base (antes de la ACL propia)

Ejecutado desde CloudShell contra la distribución, con los payloads codificados en URL
para que bash no los altere antes de enviarlos.

[Captura omitida por seguridad: Medición de línea base](capturas/07-linea-base-cloudshell.md)

| # | Ataque | Código | Lectura |
|---|---|---|---|
| 1 | Control `/` | **200** | La app responde a través de CloudFront |
| 2 | SQLi `' OR 1=1--` | **500** | **Llegó al origen y rompió el backend** |
| 3 | XSS `<script>alert(1)</script>` | 403 | Bloqueado por las reglas heredadas |
| 4 | Path traversal | 403 | Bloqueado por las reglas heredadas |
| 5 | User-Agent `sqlmap/1.7` | 403 | Bloqueado por las reglas heredadas |

**Hallazgo 2 — el 500 es el dato importante.** No es un fallo del laboratorio: significa
que la inyección atravesó CloudFront y las tres reglas heredadas, llegó a Juice Shop y la
consulta falló al ejecutarse. Un 500 ante un payload SQL es la firma de una inyección que
el backend sí está procesando. La vulnerabilidad queda confirmada y demostrado que las
protecciones base no la cubren.

**Hallazgo 3 — la regla propia hubo que rediseñarla.** La guía proponía bloquear el
User-Agent `sqlmap`, pero la prueba 5 ya devolvía 403 **antes** de crear ninguna regla
propia. Bloquearlo no habría demostrado nada, porque el resultado sería idéntico sin la
regla. Se cambió la firma a `nikto`, verificando primero que no estuviera cubierta.

> Medir la línea base antes de configurar no es burocracia: es lo que evita atribuirse
> un bloqueo ajeno.

---

## Parte 4 — Web ACL propia `<AWS_GLOBAL_WEB_ACL_NAME>`

| Dato | Valor |
|---|---|
| Nombre | `<AWS_GLOBAL_WEB_ACL_NAME>` |
| Alcance | CloudFront (global) |
| ID | `<AWS_GLOBAL_WEB_ACL_ID>` |
| Acción por defecto | Allow |
| Capacidad usada | 1122 / 1500 WCU |

### Selección del paquete

La consola ofrece tres paquetes prearmados. Se descartaron los dos primeros.

[Captura omitida por seguridad: Comparativa de paquetes y costos](capturas/09-comparativa-costos-paquetes.md)

| Paquete | Costo estimado | Motivo del descarte |
|---|---|---|
| Reglas recomendadas | 59–60 USD/mes | Incluye Bot Control y DDoS gestionado; varias reglas en `Count`, que no bloquean |
| Reglas esenciales | 44–45 USD/mes | Mismo problema de reglas en `Count` y grupos irrelevantes (PHP) |
| **Construido a medida** | **~16 USD/mes** | Control regla por regla y atribución clara de cada bloqueo |

El criterio no fue solo el precio. Con reglas en modo `Count` no se puede saber qué
produjo un 403, y la tabla de resultados pierde sentido.

Categorías declaradas: comercio electrónico + servicios de API. Se descartaron las otras
cuatro que la consola preseleccionaba, para reducir la superficie de falsos positivos.

[Captura omitida por seguridad: Categorías de aplicación](capturas/08-categorias-aplicacion.md)

### Reglas configuradas

[Captura omitida por seguridad: Reglas y orden final](capturas/14-acl-cinco-reglas-orden.md)

| Prioridad | Regla | Tipo | Acción | WCU | Por qué |
|---|---|---|---|---|---|
| 1 | `<AWS_RATE_RULE_NAME>` | Rate-based, 100 req / 5 min por IP | Block | 2 | Fuerza bruta y escaneos automatizados |
| 2 | `<AWS_USER_AGENT_RULE_NAME>` | Custom, header `User-Agent` contiene `nikto` (lowercase) | Block | 20 | Firma de herramienta de escaneo no cubierta por las administradas |
| 3 | `AWSManagedRulesCommonRuleSet` | Administrada | Block | 700 | Cobertura general OWASP |
| 4 | `AWSManagedRulesKnownBadInputsRuleSet` | Administrada | Block | 200 | Payloads maliciosos conocidos |
| 5 | `AWSManagedRulesSQLiRuleSet` | Administrada | Block | 200 | Respuesta directa al 500 de la línea base |

[Captura omitida por seguridad: Core rule set — 700 WCU](capturas/10-core-rule-set-700wcu.md)
[Captura omitida por seguridad: Los tres grupos administrados](capturas/11-tres-grupos-administrados.md)
[Captura omitida por seguridad: Regla rate-based](capturas/12-regla-tasa.md)
[Captura omitida por seguridad: Regla de User-Agent](capturas/13-regla-user-agent-nikto.md)

**Sobre el orden.** En AWS WAF gana la primera regla que coincide, y es la que queda
registrada como `terminatingRuleId`. Poniendo las propias por delante de las administradas,
los logs atribuyen correctamente los bloqueos que originan ellas.

**Sobre las WCU.** El techo por defecto de una Web ACL es 1500. Solo Core rule set consume
700. Es un límite técnico, independiente del presupuesto: no se pueden encender grupos de
forma indiscriminada aunque haya dinero para pagarlos.

[Captura omitida por seguridad: Web ACL creada](capturas/15-acl-creada.md)

---

## Hallazgo 4 — El plan Free de CloudFront no permite reemplazar su Web ACL

Tras crear `<AWS_GLOBAL_WEB_ACL_NAME>`, la vinculación con la distribución falló. El mensaje es
explícito:

> `Failed to associate web ACL ... with CloudFront distribution <AWS_CLOUDFRONT_DISTRIBUTION_ID>:`
> `You can't remove or replace the web ACL for your distribution.`
> `Distributions with a pricing plan subscription must have a web ACL resource.`

[Captura omitida por seguridad: Restricción del plan Free](capturas/16-plan-free-bloquea-desvinculacion.md)
[Captura omitida por seguridad: Panel reportando cero recursos](capturas/17-no-hay-recursos-vinculados.md)

Una distribución solo admite **una** Web ACL. En el plan Free, esa plaza la ocupa de forma
permanente la ACL que CloudFront crea sola, y no se puede desvincular ni sustituir. La ACL
propia queda creada pero huérfana, sin evaluar tráfico.

### Cómo se detectó

Un primer `curl` con `User-Agent: nikto/2.5` devolvió 403, y se interpretó como prueba de
que la regla propia estaba activa. **Esa conclusión era incorrecta.** La batería completa
posterior lo desmintió:

| # | Ataque | Línea base | Con `<AWS_GLOBAL_WEB_ACL_NAME>` creada |
|---|---|---|---|
| 1 | Control | 200 | 200 |
| 2 | SQLi | **500** | **500** |
| 3 | XSS | 403 | 403 |
| 4 | Traversal | 403 | 403 |
| 5 | User-Agent escáner | 403 | 403 |

Cinco códigos idénticos. Si el grupo `AWSManagedRulesSQLiRuleSet` estuviera evaluando, la
prueba 2 habría pasado de 500 a 403. No se movió. El 403 del User-Agent procedía de la ACL
heredada, cuyas protecciones incluyen detección de escaneo de vulnerabilidades.

> **Lectura defensiva.** Un 403 aislado no prueba qué control actuó. Confirmar un control
> exige o bien un cambio de comportamiento respecto a una línea base medida, o bien el
> `terminatingRuleId` del log. Atribuir un bloqueo a la regla propia porque coincide con
> lo esperado es sesgo de confirmación, y aquí llevó a dar por funcionando una arquitectura
> que no lo estaba.

## Parte 5 — Migración a Application Load Balancer

Descartado CloudFront, se movió la aplicación detrás de un ALB, donde la Web ACL sí se
puede asociar libremente. No es un plan B: WAF sobre ALB es el patrón más extendido en
aplicaciones de negocio, mientras que CloudFront + WAF es específico de CDN pública.

| Recurso | Valor |
|---|---|
| ALB | `<AWS_ALB_NAME>` |
| DNS | `<AWS_ALB_DNS>` |
| Esquema | Internet-facing, IPv4 |
| Zonas | `<AWS_AVAILABILITY_ZONE_1>`, `<AWS_AVAILABILITY_ZONE_2>` y `<AWS_AVAILABILITY_ZONE_3>` |
| Security group | `<AWS_ALB_SECURITY_GROUP_NAME>` (entrada HTTP 80, salida todo) |
| Target group | `<AWS_TARGET_GROUP_NAME>` — instancia, HTTP:80, health check `/` |

### Dos tropiezos de red que conviene recordar

**La zona de disponibilidad.** La EC2 se lanzó con "sin preferencia de subred" y AWS la
colocó en **`<AWS_AVAILABILITY_ZONE_3>`**. Un ALB solo enruta hacia zonas que tenga habilitadas; con solo
`<AWS_AVAILABILITY_ZONE_1>` y `<AWS_AVAILABILITY_ZONE_2>` marcadas, el destino se registra pero nunca recibe tráfico. El síntoma es un 503
con toda la configuración aparentemente correcta. Se solucionó habilitando las tres zonas.

**La regla de salida.** El security group del ALB se creó con regla de entrada pero sin
regla de salida. Sin ella, el balanceador acepta la petición pero no puede reenviarla al
destino. La consola lo avisa, pero es fácil pasarlo por alto.

---

## Parte 6 — Web ACL regional y resultados

| Dato | Valor |
|---|---|
| Nombre | `<AWS_REGIONAL_WEB_ACL_NAME>` |
| Alcance | **Regional, `<AWS_REGION>`** |
| Recurso | `<AWS_ALB_NAME>` |
| Acción por defecto | Allow |
| Capacidad | 1122 WCU |

| Prioridad | Regla | Acción | WCU |
|---|---|---|---|
| 1 | `<AWS_RATE_RULE_NAME>` (rate-based, 100 req / 5 min por IP) | Block | 2 |
| 2 | `<AWS_USER_AGENT_RULE_NAME>` (header `User-Agent` contiene `nikto`) | Block | 20 |
| 3 | `AWSManagedRulesCommonRuleSet` | Block | 700 |
| 4 | `AWSManagedRulesKnownBadInputsRuleSet` | Block | 200 |
| 5 | `AWSManagedRulesSQLiRuleSet` | Block | 200 |

En alcance regional no existen los planes de tarifa fija de CloudFront: todos los grupos
administrados están disponibles, las reglas personalizadas pueden inspeccionar encabezados,
parámetros y cuerpo, y no hay tope de 5 reglas.

### Resultados

Línea base medida sobre el ALB **antes** de asociar la ACL, sin ninguna protección previa
—a diferencia de CloudFront, aquí el punto de partida es realmente limpio.

| # | Ataque | Payload | Sin WAF | Con WAF | Regla responsable |
|---|---|---|---|---|---|
| 1 | Control | `/` | 200 | **200** | — (tráfico legítimo intacto) |
| 2 | SQL injection | `' OR 1=1--` | **500** | **403** | `AWSManagedRulesSQLiRuleSet` |
| 3 | XSS reflejado | `<script>alert(1)</script>` | 200 | **403** | `AWSManagedRulesCommonRuleSet` |
| 4 | Path traversal | `/etc/passwd../` | 200 | **403** | `KnownBadInputs` / `CommonRuleSet` |
| 5 | User-Agent escáner | `nikto/2.5` | 200 | **403** | `<AWS_USER_AGENT_RULE_NAME>` |

*(La columna "regla responsable" está pendiente de confirmar con el campo
`terminatingRuleId` de los logs de CloudWatch.)*

**Lectura del caso 2.** Sin WAF, la inyección llegaba al backend y lo hacía fallar: el 500
prueba que la consulta se intentó ejecutar. Con el grupo SQLi activo, la petición se corta
en el borde y nunca alcanza la base de datos. Esa es exactamente la protección que el plan
Free de CloudFront reservaba para el plan Pro de 15 USD/mes.

**Lectura del caso 1.** Que el control siga en 200 importa tanto como los bloqueos: un WAF
que corta ataques pero también tráfico legítimo es inservible. Queda pendiente la búsqueda
de falsos positivos navegando la aplicación como usuario real.

---

## Parte 7 — Rate limit y evidencia en logs

### La regla de tasa no detiene una ráfaga instantánea

Dos ejecuciones idénticas de 130 peticiones, seguidas:

| Tanda | Resultado | `terminatingRuleId` en el log |
|---|---|---|
| 1ª | 130 × **200** | `Default_Action` / ALLOW |
| 2ª | 130 × **403** | `<AWS_RATE_RULE_NAME>` / **BLOCK** |

La primera ráfaga pasó entera pese a superar el umbral de 100. AWS WAF evalúa las reglas
de tasa en una ventana deslizante de 5 minutos (`evaluationWindowSec: 300`), pero el contador
se actualiza cada ~30 segundos: las 130 peticiones se enviaron en pocos segundos, antes de que
el contador reflejara nada. En la segunda tanda el umbral ya estaba superado y bloqueó todo.

> **Lectura defensiva.** Una regla de tasa protege contra fuerza bruta y escaneo sostenido,
> **no** contra un pico instantáneo. Quien la configure esperando frenar ráfagas de un segundo
> está protegido sobre el papel y no en la práctica. El bloqueo además persiste hasta que la
> ventana desciende del umbral, así que bloquea a quien la dispara — incluido uno mismo.

### Atribución confirmada por `terminatingRuleId`

El campo del log elimina la ambigüedad que arruinó la medición sobre CloudFront:

```json
"terminatingRuleId": "<AWS_RATE_RULE_NAME>",
"terminatingRuleType": "RATE_BASED",
"action": "BLOCK",
"rateBasedRuleList": [{ "limitKey": "IP", "maxRateAllowed": 100, "evaluationWindowSec": 300 }]
```

En los eventos ALLOW, los tres grupos administrados aparecen con `terminatingRule: null` y
`nonTerminatingMatchingRules: []` — prueba formal de que el tráfico legítimo atraviesa las
cinco reglas sin coincidir con ninguna. **Cero falsos positivos en la ruta `/`.**

---

## Hallazgo 5 — Escaneado por terceros en menos de una hora

Entre el tráfico propio apareció una petición que no era de las pruebas:

```json
"clientIp": "<EXTERNAL_CLIENT_IP>",
"country": "US",
"User-Agent": "Hello from Palo Alto Networks, find out more about our scans in
               https://docs-cortex.paloaltonetworks.com/r/1/Cortex-Xpanse/Scanning-activity",
"host": "<AWS_ALB_PUBLIC_IP>",
"uri": "/",
"action": "ALLOW"
```

Un escáner de superficie de ataque de internet (Cortex Xpanse) localizó el balanceador menos
de una hora después de exponerlo. Dos detalles importan:

- **Llegó por la IP, no por el DNS.** El escaneo no necesita conocer el nombre del recurso;
  barre rangos de direcciones. No existe la seguridad por oscuridad en una IP pública.
- **Pasó con ALLOW, y es correcto.** Era un `GET /` sin payload. Un WAF bloquea ataques, no
  reconocimiento pasivo. Frenarlo requeriría reputación de IP o límites de tasa agresivos,
  con el coste en falsos positivos que eso implica.

> **Lectura defensiva.** Cualquier recurso público es descubierto y sondeado en minutos,
> lo conozca alguien o no. El WAF no se justifica por el tráfico esperado sino por el
> inevitable.

---

## Hallazgo 6 — El falso positivo lo causó la regla propia, no las administradas

Navegación manual de la tienda como usuario real: portada, registro, pregunta de seguridad,
login, búsquedas, carrito, perfil.

| Acción | Resultado |
|---|---|
| Carga de portada | OK |
| Búsqueda con apóstrofo (`banana's`) | OK — "No results found", respuesta legítima de la app |
| Registro (`POST /api/Users/`) | OK |
| Pregunta de seguridad (`POST /api/SecurityAnswers/`) | OK |
| Login (`POST /rest/user/login`) | OK |
| Carrito, perfil, navegación | **403 a los ~50 segundos** |

### Qué muestran los logs

Todo el tráfico desde la IP del navegador aparece con `action: ALLOW` y
`terminatingRuleId: Default_Action` durante el primer minuto — los tres grupos administrados
con `terminatingRule: null` en cada evento. A partir de ahí, todo pasa a:

```json
"terminatingRuleId": "<AWS_RATE_RULE_NAME>",
"terminatingRuleType": "RATE_BASED",
"action": "BLOCK"
```

Bloqueando indistintamente `<APPLICATION_BASKET_PATH>`, `/rest/user/whoami`, `/profile`, `/favicon.ico`
y hasta las fuentes y `no-results.png`.

**Causa.** Navegar una SPA durante menos de un minuto supera las 100 peticiones en la ventana
de 5 minutos: cada vista dispara JS, CSS, fuentes, ~15 imágenes de producto, varias llamadas
REST y polling continuo de `socket.io`. El umbral, elegido para poder demostrar la regla con
130 curl, es irreal para una aplicación de una sola página.

**Cero falsos positivos de las reglas administradas. Uno grave de la regla propia.**

### Cómo se afinaría

1. **Subir el umbral** a 1000–2000 por 5 minutos. Sigue frenando fuerza bruta y escaneo, sin
   tocar la navegación legítima.
2. **Acotar la regla por ruta** — aplicarla solo a `/rest/user/login` y endpoints de
   autenticación, que es donde la fuerza bruta importa, en lugar de a todo el sitio.
3. **Pasarla a `Count` primero** y revisar los logs unos días antes de ponerla en `Block`.

La opción 2 es la correcta: un límite global castiga al usuario por usar la aplicación; un
límite sobre el login castiga a quien la ataca.

> **Lectura defensiva.** El riesgo de un WAF no está solo en lo que deja pasar. Una regla
> propia mal calibrada tumbó la experiencia de usuario completa mientras las cinco reglas
> restantes funcionaban correctamente. Por eso la práctica estándar es desplegar en `Count`,
> medir contra tráfico real, y solo después bloquear.

---

## Hallazgo 7 — Los logs de WAF guardan credenciales si no se redactan

En los eventos posteriores al login aparece el header completo:

```
Authorization: Bearer <REDACTED_JWT>
Cookie: token=<REDACTED_JWT>
```

Ese JWT de Juice Shop, decodificado, contiene el email del usuario y el hash de su contraseña.
AWS WAF registra los encabezados tal cual salvo que se configuren explícitamente campos
redactados, opción que en este laboratorio se dejó desactivada a propósito para poder ver los
payloads de los ataques.

**En producción esto es una fuga de credenciales hacia el sistema de logs**, donde suele
haber más gente con acceso que a la base de datos. La corrección es declarar `Authorization`
y `Cookie` como encabezados redactados en la configuración de registro.

> **Lectura defensiva.** Activar el logging no es gratis en términos de riesgo: mueve datos
> sensibles a un sistema nuevo, con su propio control de acceso y su propia retención.

---

## Parte 8 — Logging

- Destino: CloudWatch Logs
- Log group: `<AWS_LOG_GROUP_NAME>`
- Log stream: `<AWS_LOG_STREAM_NAME>`
- Solicitudes de muestra: activadas (sin coste, guarda las 3 últimas coincidencias por regla)
- Campos redactados: ninguno — la URI y la cadena de consulta contienen los payloads y se
  necesitan visibles. En producción con datos reales sí se redactarían.

El prefijo `aws-waf-logs-` es obligatorio. Con cualquier otro nombre, WAF rechaza el
destino sin un mensaje de error claro.

**Nota de consola:** el enlace "Panel → Ver" de la lista de ACL lleva a *Network Security
Director*, un servicio en preview que exige AWS Organizations y cambia el alcance a Global.
No guarda relación con la Web ACL. Las métricas propias están en "Solicitudes de muestra".

---

## Estado actual

- [x] Juice Shop desplegado y accesible
- [x] CloudFront delante, HTTPS al visitante
- [x] Línea base medida y documentada
- [x] Migración a ALB tras el bloqueo del plan Free
- [x] Web ACL regional `<AWS_REGIONAL_WEB_ACL_NAME>` con 5 reglas, asociada y verificada
- [x] Batería de ataques posterior al WAF — 4/4 bloqueados
- [x] Logging en la ACL regional, con `terminatingRuleId` verificado
- [x] Prueba del rate limit — latencia de detección documentada
- [x] Búsqueda de falsos positivos — uno encontrado (`<AWS_RATE_RULE_NAME>`), ninguno de las administradas
- [ ] Capturas pendientes: ALB sirviendo la app, ACL regional con las 5 reglas, batería
      final en CloudShell, evento BLOCK con `<AWS_RATE_RULE_NAME>`, evento del escáner externo
- [x] Capturas originales excluidas de esta edición pública; no se afirma verificación OCR
- [x] README.md redactado
- [x] Destrucción de recursos completada

---

## Costo

| Recurso | Costo/hora aprox. |
|---|---|
| EC2 t3.micro | 0,0104 USD |
| ALB (base + LCU) | ~0,025 USD |
| Web ACL regional (5 USD/mes) | 0,0069 USD |
| 5 reglas (1 USD/mes c/u) | 0,0069 USD |
| **Total** | **≈ 0,05 USD/hora** |

Un fin de semana completo: alrededor de 2,50 USD. El ALB es la partida dominante, y por eso
la alternativa de pagar CloudFront Pro (15 USD/mes, cobrados por suscripción y no por hora)
resultaba más cara para un laboratorio de dos días pese a parecer más "oficial".

Recursos huérfanos que siguen generando cargo y hay que borrar: la distribución de
CloudFront y la Web ACL global `<AWS_GLOBAL_WEB_ACL_NAME>`, que quedó creada sin asociar.

---

## Pendiente de destrucción

En este orden, porque WAF no permite borrar la Web ACL mientras esté asociada:

1. CloudFront `<AWS_CLOUDFRONT_DISTRIBUTION_ID>` → Disable → esperar → Delete
2. Web ACL `<AWS_GLOBAL_WEB_ACL_NAME>` (alcance global) → Delete
3. EC2 `<AWS_INSTANCE_ID>` → Terminate
4. Security group `<AWS_EC2_SECURITY_GROUP_NAME>`
5. Log group `<AWS_LOG_GROUP_NAME>`
6. Revisar Cost Explorer al día siguiente
