# AWS WAF sobre OWASP Juice Shop — laboratorio de defensa en el borde

> **Edición anonimizada.** Los identificadores son placeholders y las capturas originales se excluyeron. Consulte [SANITIZACION.md](SANITIZACION.md) antes de reutilizar los ejemplos.


Despliegue de una aplicación deliberadamente vulnerable detrás de AWS WAF, con medición
antes/después, análisis de logs y búsqueda de falsos positivos.

El objetivo no era "activar un WAF". Era comprobar, con evidencia, **qué bloquea realmente,
qué deja pasar, y qué rompe** — incluyendo el caso en que la regla que rompe la aplicación
es la que escribí yo.

- **Fecha:** septiembre de 2026 · **Región:** `<AWS_REGION>` (región anonimizada)
- **Costo total:** por debajo de 3 USD, recursos destruidos el mismo día
- **Edición pública anonimizada: capturas originales excluidas por seguridad**

---

## Resultados

Línea base medida **sin ninguna protección**, sobre la arquitectura final, antes de asociar
la Web ACL. Cada payload se envió codificado en URL para que el shell no lo alterara.

| # | Ataque | Payload | Sin WAF | Con WAF | Regla que bloquea |
|---|---|---|---|---|---|
| 1 | Control | `/` | 200 | **200** | — tráfico legítimo intacto |
| 2 | SQL injection | `' OR 1=1--` | **500** | **403** | `AWSManagedRulesSQLiRuleSet` |
| 3 | XSS reflejado | `<script>alert(1)</script>` | 200 | **403** | `AWSManagedRulesCommonRuleSet` |
| 4 | Path traversal | `/etc/passwd../` | 200 | **403** | `KnownBadInputs` / `CommonRuleSet` |
| 5 | User-Agent de escáner | `nikto/2.5` | 200 | **403** | `<AWS_USER_AGENT_RULE_NAME>` |

[Captura omitida por seguridad: Línea base sin WAF](capturas/07-linea-base-cloudshell.md)

**El caso 2 es el que importa.** Sin WAF, la inyección no devolvía un 200 inocuo: devolvía
**500**. Eso significa que la consulta llegó al backend y la base de datos falló al
ejecutarla — la vulnerabilidad no es teórica, es explotable. Con el grupo de reglas SQLi
activo, la petición se corta en el borde y nunca alcanza la aplicación.

**El caso 1 importa igual.** Un WAF que bloquea ataques pero también tráfico legítimo no
sirve. Por eso el control se mide siempre, y por eso la búsqueda de falsos positivos ocupa
una sección propia más abajo.

---

## Arquitectura

```
Internet → ALB (<AWS_REGION>, 3 AZ)
             └── Web ACL regional · 5 reglas
                   ↓
             EC2 t3.micro · Docker · OWASP Juice Shop
                   ↓
             CloudWatch Logs (aws-waf-logs-*)
```

El laboratorio empezó sobre **CloudFront** y hubo que migrarlo a **ALB**. El motivo está
documentado en el Hallazgo 2: el plan gratuito de CloudFront no permite asociar una Web ACL
propia. La arquitectura final no es un plan B — WAF sobre Application Load Balancer es el
patrón más extendido en aplicaciones de negocio.

### Reglas

| # | Regla | Tipo | Acción | WCU | Por qué |
|---|---|---|---|---|---|
| 1 | `<AWS_RATE_RULE_NAME>` | Rate-based, 100 req / 5 min por IP | Block | 2 | Fuerza bruta y escaneo sostenido |
| 2 | `<AWS_USER_AGENT_RULE_NAME>` | Custom, header `User-Agent` | Block | 20 | Firma de escáner no cubierta por las administradas |
| 3 | `AWSManagedRulesCommonRuleSet` | Administrada | Block | 700 | Cobertura general OWASP |
| 4 | `AWSManagedRulesKnownBadInputsRuleSet` | Administrada | Block | 200 | Payloads maliciosos conocidos |
| 5 | `AWSManagedRulesSQLiRuleSet` | Administrada | Block | 200 | Respuesta directa al 500 de la línea base |

[Captura omitida por seguridad: Reglas y orden](capturas/14-acl-cinco-reglas-orden.md)

**Sobre el orden.** En AWS WAF gana la primera regla que coincide, y es la que queda
registrada como `terminatingRuleId`. Las reglas propias van por delante de las administradas
para que los logs atribuyan correctamente los bloqueos que originan.

**Sobre las WCU.** El techo por defecto de una Web ACL es 1500 y Core rule set consume 700
por sí solo. Es un límite técnico independiente del presupuesto: no se pueden encender
grupos de forma indiscriminada aunque haya dinero para pagarlos.

---

## Hallazgos

### 1. Medir la línea base no es burocracia

La primera versión de la regla propia bloqueaba el User-Agent `sqlmap`. La medición previa
mostró que **ese User-Agent ya devolvía 403 antes de que existiera ninguna regla mía**.
Haberla dejado así habría producido un bloqueo correcto e inatribuible: el resultado habría
sido idéntico sin la regla.

Se cambió la firma a `nikto`, verificando primero que no estuviera cubierta. Solo así el
403 posterior demuestra algo.

> Sin un "antes" medido, un "después" que funciona no prueba que funcione *por lo que hiciste*.

### 2. CloudFront impone un WAF que no se puede reemplazar en el plan Free

El asistente de creación de CloudFront incluye un paso de seguridad que, con todos los
toggles de reglas apagados, deja igualmente `Security protections: Enabled`. Al intentar
editarlo después, **no existe opción para desactivarlo**.

[Captura omitida por seguridad: Sin opción de desactivar](capturas/04-security-sin-opcion-desactivar.md)

Consecuencia: la distribución ya tenía asociada una Web ACL propia de AWS con tres reglas
(`AmazonIpReputationList`, `CommonRuleSet`, `KnownBadInputs`) antes de crear nada.

Al crear la ACL propia y tratar de asociarla:

> `You can't remove or replace the web ACL for your distribution.`
> `Distributions with a pricing plan subscription must have a web ACL resource.`

[Captura omitida por seguridad: Restricción del plan Free](capturas/16-plan-free-bloquea-desvinculacion.md)

Una distribución admite **una sola** Web ACL. En el plan Free esa plaza está ocupada de
forma permanente. Además, las reglas personalizadas quedan limitadas a inspección de
direcciones IP —sin headers, parámetros ni cuerpo— y el grupo SQL database exige plan Pro
(15 USD/mes).

Con esas limitaciones el laboratorio era imposible. De ahí la migración a ALB.

> Un entorno "sin WAF" ya no existe por defecto en CloudFront. Cualquier medición de línea
> base tiene que declarar qué protecciones base estaban activas o las conclusiones no son
> reproducibles.

### 3. El panel de control no es evidencia

Tras crear la ACL propia, el banner superior confirmaba la asociación mientras el panel de
recursos mostraba **"No hay recursos vinculados"**.

[Captura omitida por seguridad: Panel reportando cero recursos](capturas/17-no-hay-recursos-vinculados.md)

Un `curl` con el User-Agent de escáner devolvió 403, y esa señal aislada se interpretó como
prueba de que la regla propia estaba activa. **Era incorrecto.** La batería completa lo
desmintió: los cinco códigos eran idénticos a la línea base, incluido el 500 de la SQLi que
habría tenido que pasar a 403. El 403 procedía de la ACL heredada.

> Un 403 aislado no prueba qué control actuó. Confirmar un control exige un cambio de
> comportamiento respecto a una línea base medida, o el `terminatingRuleId` del log.
> Atribuir un bloqueo a la regla propia porque coincide con lo esperado es sesgo de
> confirmación.

### 4. Una regla de tasa no detiene una ráfaga instantánea

Dos ejecuciones idénticas de 130 peticiones, seguidas:

| Tanda | Resultado | `terminatingRuleId` |
|---|---|---|
| 1ª | 130 × **200** | `Default_Action` / ALLOW |
| 2ª | 130 × **403** | `<AWS_RATE_RULE_NAME>` / **BLOCK** |

La primera ráfaga pasó entera pese a superar el umbral. AWS WAF evalúa las reglas de tasa en
una ventana deslizante de 5 minutos (`evaluationWindowSec: 300`) pero el contador se
actualiza cada ~30 segundos: las 130 peticiones se enviaron antes de que reflejara nada.

> Una regla de tasa protege contra fuerza bruta y escaneo sostenido, **no** contra un pico de
> un segundo. Quien la configure esperando frenar ráfagas está protegido sobre el papel y no
> en la práctica.

### 5. El falso positivo lo causó mi regla, no las administradas

Navegación manual de la tienda como usuario real:

| Acción | Resultado |
|---|---|
| Portada, búsqueda con apóstrofo (`banana's`) | OK |
| Registro, pregunta de seguridad, login | OK |
| Carrito, perfil, navegación | **403 a los ~50 segundos** |

Los logs muestran todo el tráfico del navegador con `action: ALLOW` y los tres grupos
administrados en `terminatingRule: null` durante el primer minuto. A partir de ahí, todo
pasa a `<AWS_RATE_RULE_NAME>` / BLOCK: `/rest/basket`, `/profile`, `/favicon.ico`, las fuentes y
hasta la imagen de "sin resultados".

**Causa.** Navegar una SPA menos de un minuto supera las 100 peticiones: cada vista dispara
JS, CSS, fuentes, ~15 imágenes de producto, varias llamadas REST y polling de `socket.io`.
El umbral, elegido para poder demostrar la regla, es irreal para esta aplicación.

**Cero falsos positivos de las cinco reglas administradas. Uno grave de la regla propia.**

Cómo se afinaría, en orden de preferencia:

1. **Acotar la regla por ruta** — aplicarla solo a `/rest/user/login` y endpoints de
   autenticación, que es donde la fuerza bruta importa.
2. **Subir el umbral** a 1000–2000 por 5 minutos.
3. **Desplegar en `Count` primero**, medir contra tráfico real, y solo después bloquear.

La opción 1 es la correcta: un límite global castiga al usuario por usar la aplicación; un
límite sobre el login castiga a quien la ataca.

> El riesgo de un WAF no está solo en lo que deja pasar. Una regla propia mal calibrada tumbó
> la experiencia de usuario completa mientras las otras cinco funcionaban bien.

### 6. Escaneado por terceros en menos de una hora

Entre el tráfico propio apareció una petición que no era de las pruebas:

```json
"clientIp": "<EXTERNAL_CLIENT_IP>",
"User-Agent": "Hello from Palo Alto Networks, find out more about our scans in
               https://docs-cortex.paloaltonetworks.com/r/1/Cortex-Xpanse/Scanning-activity",
"host": "<AWS_ALB_PUBLIC_IP>",
"uri": "/",
"action": "ALLOW"
```

Un escáner de superficie de ataque localizó el balanceador menos de una hora después de
exponerlo. Dos detalles:

- **Llegó por la IP, no por el DNS.** El escaneo barre rangos de direcciones; no necesita
  conocer el nombre del recurso. No existe seguridad por oscuridad en una IP pública.
- **Pasó con ALLOW, y es correcto.** Era un `GET /` sin payload. Un WAF bloquea ataques, no
  reconocimiento pasivo.

> El WAF no se justifica por el tráfico esperado sino por el inevitable.

### 7. Los logs guardan credenciales si no se redactan

En los eventos posteriores al login aparece el header completo:

```
Authorization: Bearer <REDACTED_JWT>
Cookie: token=<REDACTED_JWT>
```

Ese JWT, decodificado, contiene el email del usuario y el hash de su contraseña. AWS WAF
registra los encabezados tal cual salvo que se declaren campos redactados — opción que aquí
se dejó desactivada a propósito para poder ver los payloads de los ataques.

En producción esto es una fuga de credenciales hacia el sistema de logs, donde suele haber
más gente con acceso que a la base de datos. La corrección es declarar `Authorization` y
`Cookie` como encabezados redactados.

> Activar el logging no es gratis en términos de riesgo: mueve datos sensibles a un sistema
> nuevo, con su propio control de acceso y su propia retención.

---

## Detalles operativos que costaron tiempo

Documentados porque volverían a costarlo:

- **El user data con indentación no se ejecuta.** Cloud-init exige `#!` en la posición 1 de
  la línea 1. La instancia arranca bien y la aplicación nunca aparece.
- **La zona de disponibilidad del destino.** La EC2 se lanzó sin preferencia de subred y
  AWS la colocó en `<AWS_AVAILABILITY_ZONE_3>`. Un ALB solo enruta hacia zonas habilitadas: con solo `<AWS_AVAILABILITY_ZONE_1>` y
  `<AWS_AVAILABILITY_ZONE_2>` marcadas el destino se registra pero nunca recibe tráfico. El síntoma es un 503 con
  todo aparentemente bien configurado.
- **La regla de salida del security group.** Sin ella el balanceador acepta la petición pero
  no puede reenviarla al destino.
- **El prefijo del log group.** Debe empezar por `aws-waf-logs-` o WAF rechaza el destino sin
  un mensaje claro.
- **`AllViewer` como origin request policy.** Con caché desactivada a secas, CloudFront no
  reenvía cookies ni headers al origen: el login se rompe y el `User-Agent` no llega a las
  reglas.

---

## Costo y limpieza

| Recurso | USD/hora aprox. |
|---|---|
| EC2 t3.micro | 0,0104 |
| ALB (base + LCU) | ~0,025 |
| Web ACL regional | 0,0069 |
| 5 reglas | 0,0069 |
| **Total** | **≈ 0,05** |

Todos los recursos fueron destruidos el mismo día: distribución de CloudFront, ambas Web
ACL, ALB, target group, instancia y security groups. La elección de construir el paquete de
reglas a mano en lugar de aceptar los paquetes sugeridos por la consola (59 y 44 USD/mes)
redujo el costo a una fracción y, más importante, evitó reglas en modo `Count` que habrían
hecho inatribuible cualquier bloqueo.

[Captura omitida por seguridad: Comparativa de paquetes](capturas/09-comparativa-costos-paquetes.md)

---

## Qué aprendí

Vengo del lado ofensivo: estos cuatro ataques los conozco de plataformas de práctica. Montar
la defensa cambió qué preguntas me hago.

La más útil: **¿cómo sé que este control está funcionando?** No por lo que dice la consola
—que en este laboratorio se equivocó— ni por un código de respuesta aislado, sino por un
cambio medido frente a una línea base y por el `terminatingRuleId` del log.

La segunda: **un control mal calibrado hace daño.** La única regla que rompió la aplicación
fue la mía, y lo hizo mientras las otras cinco trabajaban correctamente. De ahí que la
práctica estándar sea desplegar en `Count`, medir contra tráfico real y bloquear después.

Y la tercera, la que menos esperaba: **la plataforma tiene opiniones propias.** CloudFront
impone un WAF que no se puede quitar, condiciona la inspección disponible según el plan
contratado y reporta estados que no se corresponden con la realidad. Trabajar con eso —y
documentarlo— es parte del trabajo.

---

## Contenido del repositorio

```
README.md      este informe
notas.md       bitácora cruda de la ejecución, con lo que salió mal y por qué
capturas/      notas de las 18 capturas omitidas por seguridad
SANITIZACION.md resumen y alcance de la anonimización
.gitignore     exclusiones preventivas para datos sensibles
```
