# Paso a paso: sistema de tickets con EC2 como núcleo

**Versión EC2 del caso práctico. Referencia: 28 de octubre de 2026.**

EC2 ejecuta la aplicación web y toda la API de negocio con Nginx, Gunicorn y Flask. Cognito autentica a los usuarios y DynamoDB conserva los tickets. Esta versión sustituye la ejecución en Lambda y la entrada por API Gateway del diseño anterior.

La entrega contiene código, plantilla CloudFormation y scripts de instalación. **No se han creado recursos en tu cuenta.** Las comprobaciones locales cubren reglas de negocio, HTTP y validación criptográfica con claves de prueba. La instalación en Amazon Linux y el recorrido contra AWS requieren ejecutar esta guía.

## 1. Arquitectura del proyecto

```text
Navegador ──HTTPS──> CloudFront ──HTTP restringido──> EC2
    │                                               │
    │                             Nginx :80 ─────────┤
    │                             ├── archivos web  │
    │                             └── /api/         │
    │                                  │            │
    │                             Gunicorn/Flask    │
    │                             127.0.0.1:8000    │
    │                                  │            │
    └── acceso ──> Cognito              └──TLS──> DynamoDB

Administración: Systems Manager. Instalación: S3 privado y Run Command.
```

CloudFront proporciona una URL HTTPS sin comprar dominio. Toda solicitud de aplicación llega a EC2 porque la caché está deshabilitada. El frontend y `/api` comparten origen, por lo que la aplicación no necesita CORS entre ellos.

**Límite del laboratorio:** el tramo CloudFront–EC2 utiliza HTTP y puede transportar tokens y datos sin cifrado en ese tramo. El security group admite únicamente la prefix list de CloudFront y Nginx exige un encabezado secreto de esa distribución. Estos controles restringen el acceso, pero no cifran el tráfico. Usa exclusivamente datos ficticios. Para publicar datos reales, configura un origen HTTPS con certificado público válido y nombre DNS propio, o rediseña el acceso con una conectividad adecuada.

Fuente: [Comportamiento y protocolos de orígenes personalizados](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/RequestAndResponseBehaviorCustomOrigin.html).

## 2. Recursos y configuración inicial

| Recurso | Configuración |
| --- | --- |
| EC2 | Una `t3.micro`, Linux x86_64, Amazon Linux 2023 |
| Créditos de CPU | Modo Standard, para evitar cargos por CPU excedente de Unlimited |
| EBS | Un volumen raíz gp3 cifrado de 8 GiB, eliminación al terminar la instancia |
| IPv4 pública | Una Elastic IP para mantener estable el origen |
| VPC | Red propia y una subred pública con ruta a Internet Gateway |
| Entrada | Puerto 80 solo desde la prefix list de CloudFront |
| Administración | Systems Manager, sin abrir SSH ni crear key pair |
| Aplicación | Flask, Gunicorn con un worker y dos threads, Nginx |
| Datos | Una tabla DynamoDB Standard con 5 RCU y 5 WCU aprovisionadas |
| Identidad | Cognito Lite, Hosted UI clásico y scope `tickets-api/access` |
| Distribución | CloudFront de pago por uso, sin caché para este laboratorio |
| Artefactos | Un bucket S3 privado para `application.zip` |

El usuario de Linux `tickets` ejecuta la API sin privilegios root. Solo Nginx escucha en la interfaz de red. El SDK obtiene credenciales temporales del rol de la instancia mediante IMDSv2.

## 3. Free Tier y presupuesto

En **Billing and Cost Management**, registra plan, saldo de créditos, fecha de vencimiento y ofertas activas. Los clientes nuevos elegibles pueden recibir USD 100 iniciales y hasta USD 100 adicionales. El plan gratuito termina a los seis meses o al agotarse los créditos. Las cuentas anteriores al 15 de julio de 2025 tienen condiciones heredadas.

En el programa actual, que una instancia esté marcada “Free tier eligible” no significa que funcione ilimitadamente sin consumir créditos. Confirma la elegibilidad de la AMI, EC2, EBS, Elastic IP y servicios auxiliares en tu cuenta. Fuente: [Free Tier para EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html).

Estimación **bruta orientativa** para `us-east-1`, Linux bajo demanda y 730 horas:

| Concepto | Cálculo de referencia | Importe aproximado |
| --- | --- | --- |
| EC2 t3.micro | 730 × USD 0,0104/h | USD 7,59 |
| Una IPv4 pública | 730 × USD 0,005/h | USD 3,65 |
| EBS gp3 8 GiB | 8 × USD 0,08/GB-mes de referencia | USD 0,64 |
| Subtotal de infraestructura | Antes de beneficios, impuestos y otros servicios | **USD 11,88/mes** |

Fuentes: [T3 en N. Virginia](https://aws.amazon.com/ec2/instance-types/t3/), [IPv4 pública](https://aws.amazon.com/vpc/pricing/) y [EBS](https://aws.amazon.com/ebs/pricing/). Valida el precio regional en la calculadora al desplegar. La cifra excluye S3, CloudFront, datos transferidos y consumo que exceda cuotas de Cognito/DynamoDB.

Un laboratorio de ocho horas consume mucho menos cómputo que un mes completo. EBS y Elastic IP continúan generando consumo mientras existan, incluso con EC2 detenido.

Crea un presupuesto mensual de consumo bruto de **USD 15**, con avisos al 50 %, 80 % y 100 %. Revisa el saldo de créditos por separado. Los avisos no apagan recursos y pueden tener demora. Si mantienes otros proyectos en la cuenta, ajusta la meta total.

## 4. Herramientas y acceso

Necesitas Bash, Python 3.11 o posterior y AWS CLI v2 actual. SAM y Docker ya no son necesarios para este proyecto.

- [Instalación de AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
- [Inicio de sesión mediante consola y CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).

Usa una identidad administrativa de laboratorio distinta de la cuenta raíz, protegida con MFA. Debe poder crear CloudFormation, EC2/VPC, IAM y perfiles de instancia, Cognito, DynamoDB, S3, CloudFront, y ejecutar comandos SSM. En cuentas institucionales, utiliza el rol autorizado por tu administrador.

Si ya tienes el perfil `tickets-lab` de la guía anterior, puedes reutilizarlo. Para un usuario o rol IAM compatible con el inicio de sesión local:

```bash
aws login --profile tickets-signin
aws configure set credential_process 'aws configure export-credentials --profile tickets-signin --format process' --profile tickets-lab
aws configure set region us-east-1 --profile tickets-lab
```

Para IAM Identity Center, utiliza `aws configure sso --profile tickets-lab` y luego `aws sso login --profile tickets-lab` con los datos de tu organización.

```bash
export AWS_PROFILE=tickets-lab
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_PAGER=""
aws sts get-caller-identity
```

**Verificación:** la cuenta y la identidad corresponden al laboratorio.

## 5. Archivos del proyecto

Extrae `solucion-tickets-ec2.zip` y abre la carpeta `solucion-tickets-ec2` en la terminal. Todos los comandos siguientes se ejecutan desde allí.

```text
solucion-tickets-ec2/
├── template.yaml
├── README.md
├── backend/
│   ├── app.py              Rutas HTTP Flask
│   ├── auth.py             Validación JWT y JWKS
│   ├── domain.py           Reglas de tickets y acceso a DynamoDB
│   └── requirements.txt
├── web/                    HTML, CSS y JavaScript
├── deploy/
│   ├── install.sh          Instalación dentro de EC2
│   ├── nginx.conf          Proxy, archivos estáticos y control del origen
│   └── tickets.service     Servicio systemd
├── scripts/
│   ├── prepare_parameters.py
│   └── build_release.py
└── tests/                  Pruebas locales sin servicios AWS
```

`parameters.json` contendrá el secreto del origen y no debe compartirse. El secreto también existirá en la configuración de CloudFront y en el servidor, por lo que los administradores con permisos de lectura correspondientes pueden acceder a él. No es una credencial IAM.

## 6. Pruebas locales

Crea un entorno virtual e instala las dependencias principales fijadas en el proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt cfn-lint
python -m unittest discover -s tests -v
cfn-lint template.yaml
```

Las pruebas de dominio usan una tabla simulada. Las pruebas HTTP usan Flask y tokens RS256 firmados con claves efímeras de prueba. Incluyen firma incorrecta, emisor incorrecto, expiración, cliente, scope, tipo de token y aislamiento entre usuarios. No realizan solicitudes a AWS ni prueban la instalación real de Nginx.

**Verificación:** `18` pruebas terminan en `OK` y la plantilla no muestra errores de validación estática.

## 7. Preparación de parámetros

Obtén la prefix list regional del tráfico de origen de CloudFront:

```bash
PREFIX_LIST_ID=$(aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)

python3 scripts/prepare_parameters.py --prefix-list-id "$PREFIX_LIST_ID"
```

El script genera un secreto aleatorio y guarda ambos valores en `parameters.json` con permisos `600`. Se niega a sobrescribirlo para evitar desincronizar la distribución y el servidor.

La prefix list de CloudFront tiene peso 55 en las reglas del security group. Este diseño consume una regla ponderada para HTTP y no agrega otra para SSH. Si alcanzas una cuota, revisa las reglas del grupo antes de solicitar cambios. Fuente: [Prefix lists administradas](https://docs.aws.amazon.com/vpc/latest/userguide/working-with-aws-managed-prefix-lists.html).

## 8. Creación de la infraestructura

```bash
aws cloudformation validate-template --template-body file://template.yaml

aws cloudformation create-stack \
  --stack-name aprende-tickets-ec2 \
  --template-body file://template.yaml \
  --parameters file://parameters.json \
  --capabilities CAPABILITY_IAM \
  --tags Key=Proyecto,Value=TicketsEC2 Key=Ambiente,Value=Lab

aws cloudformation wait stack-create-complete --stack-name aprende-tickets-ec2
```

Conserva el nombre corto y en minúsculas `aprende-tickets-ec2`. Se utiliza también en el prefijo del dominio de Cognito.

La plantilla resuelve una AMI x86_64 actual de Amazon Linux 2023 mediante un parámetro público de SSM. La instancia tiene una Elastic IP y una ruta a Internet para descargar paquetes y comunicarse con los servicios AWS. No se crea NAT Gateway.

CloudFront puede tardar varios minutos. Si el comando de espera termina sin completar, consulta los eventos de CloudFormation. **`CREATE_COMPLETE` confirma los recursos, pero todavía falta instalar la aplicación.**

## 9. Salidas y variables del despliegue

```bash
aws cloudformation describe-stacks \
  --stack-name aprende-tickets-ec2 --output json > stack-outputs.json

python3 scripts/build_release.py
```

El script genera:

- `web/config.js`: identificadores públicos y URL del frontend/API.
- `deploy/service.env`: región, tabla, emisor y cliente para el proceso Flask.
- `application.zip`: código y archivos para instalar en EC2.
- `ssm-command.json`: instrucciones para descargar e instalar el paquete.

Carga las variables auxiliares:

```bash
BUCKET_NAME=$(python3 -c 'import json; d=json.load(open("stack-outputs.json")); print(next(v["OutputValue"] for v in d["Stacks"][0]["Outputs"] if v["OutputKey"]=="BucketName"))')
INSTANCE_ID=$(python3 -c 'import json; d=json.load(open("stack-outputs.json")); print(next(v["OutputValue"] for v in d["Stacks"][0]["Outputs"] if v["OutputKey"]=="InstanceId"))')
SITE_URL=$(python3 -c 'import json; d=json.load(open("stack-outputs.json")); print(next(v["OutputValue"] for v in d["Stacks"][0]["Outputs"] if v["OutputKey"]=="WebsiteUrl"))')
```

En una terminal nueva, vuelve a cargar el perfil y las variables.

## 10. Comprobación de Systems Manager

En la consola, abre **Systems Manager → Fleet Manager** o la lista de nodos administrados. Confirma que `INSTANCE_ID` aparece como conectado.

También puedes consultar:

```bash
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[*].[InstanceId,PingStatus]' --output table
```

Si no aparece, espera unos minutos y revisa el rol, el agente SSM, la Elastic IP y la ruta a Internet. No necesitas abrir el puerto 22. La instancia usa el agente incluido en la AMI estándar de Amazon Linux 2023.

Fuente: [Run Command en EC2](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html).

## 11. Publicación e instalación en EC2

Sube el paquete al bucket privado:

```bash
aws s3 cp application.zip "s3://$BUCKET_NAME/application.zip" --only-show-errors
```

Envía el comando de instalación:

```bash
COMMAND_ID=$(aws ssm send-command \
  --document-name AWS-RunShellScript \
  --instance-ids "$INSTANCE_ID" \
  --parameters file://ssm-command.json \
  --query 'Command.CommandId' --output text)

aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}'
```

La instalación espera a `cloud-init`, descarga el código, instala Python 3.11 y Nginx, crea el entorno virtual, configura el usuario de servicio y arranca Gunicorn/systemd. También limita el tamaño del journal. Las dependencias provienen de los repositorios de Amazon Linux y de PyPI.

Si el waiter agota su tiempo mientras el comando sigue `InProgress`, consulta el estado y espera otra vez. Si termina en `Failed`, lee el error antes de repetir. La descarga inicial puede tomar varios minutos.

**Verificación:** el comando finaliza en `Success` y devuelve “Servicio Flask listo”.

## 12. Verificación del servidor

En **EC2 → Instancia → Connect → Session Manager**, inicia una sesión con la identidad administrativa autorizada. Si usas CLI, necesitas el plugin de Session Manager instalado.

Dentro del servidor ejecuta:

```bash
sudo systemctl status tickets nginx --no-pager
sudo nginx -t
curl -i http://127.0.0.1:8000/healthz
sudo journalctl -u tickets -n 30 --no-pager
```

Desde tu equipo local:

```bash
curl -i "${SITE_URL}api/healthz"
curl -i "${SITE_URL}api/tickets"
```

**Esperado:** `200` con `status: ok` en salud y `401` en tickets sin token. La salud comprueba el proceso, no la disponibilidad de DynamoDB.

Nginx rechaza solicitudes sin el encabezado del origen. La entrada directa desde tu IP al puerto 80 de EC2 también está bloqueada por el security group. Gunicorn escucha exclusivamente en `127.0.0.1:8000`.

## 13. Creación de usuarios

En **Cognito → User pools**, abre el pool indicado por la salida `UserPoolId`.

1. En **Users**, crea `ana` con contraseña temporal segura.
2. Selecciona no enviar invitación y evita configurar SMS.
3. Crea `bruno` con otra contraseña.
4. Mantén desactivado el autorregistro.

El primer acceso pedirá cambiar la contraseña. El laboratorio utiliza nombres de usuario y no configura recuperación por correo. Un administrador puede restablecer las contraseñas desde la consola.

Comprueba que el cliente es público, sin secreto, tiene Authorization Code y admite `openid` y `tickets-api/access`. La URL de callback y salida debe coincidir con `WebsiteUrl`, incluida la barra final.

## 14. Recorrido funcional

1. Abre `WebsiteUrl` y pulsa **Iniciar sesión**.
2. Accede como Ana y completa el cambio de contraseña.
3. Crea un ticket con título de 5 a 100 caracteres, descripción de 10 a 1 000 y prioridad válida.
4. Consulta el detalle.
5. Cambia de `ABIERTO` a `EN_PROCESO` y después a `CERRADO`.
6. Conserva el identificador para las pruebas de aislamiento.

EC2 valida la firma RS256 con las claves JWKS de Cognito, el emisor, vencimiento, cliente, tipo `access` y scope. Luego usa `sub` para construir `PK=USER#<sub>` en DynamoDB.

El access token permanece en memoria durante la sesión local. El prototipo no implementa renovación automática. Al recargar, pulsa nuevamente el inicio de sesión. Cerrar sesión borra el token local y termina la sesión web de Cognito, pero una copia previa del token puede seguir válida hasta su vencimiento.

## 15. Pruebas de contrato y aislamiento

Desde una ventana privada, entra como Bruno. Su listado debe estar vacío. En la consola del navegador del sitio de Bruno ejecuta, sustituyendo el identificador:

```javascript
await api('/tickets/' + encodeURIComponent('ID_DEL_TICKET_DE_ANA'))
```

**Esperado:** `404`. Repite con actualización:

```javascript
await api('/tickets/' + encodeURIComponent('ID_DEL_TICKET_DE_ANA'),
  'PATCH', { estado: 'EN_PROCESO' })
```

**Esperado:** `404`, sin cambios en el ticket de Ana.

Otras comprobaciones:

| Prueba | Resultado |
| --- | --- |
| API sin token | `401` |
| Token vencido, firma o cliente incorrectos | `401` |
| Access token sin scope | `403` |
| Título vacío | `400` |
| Crear con `PK` o campos adicionales | `400` |
| Pasar directamente de abierto a cerrado | `409` |
| Listado con `limit=21` | `400` |
| Tres tickets y dos páginas de `limit=2` | Continuación sin repetidos |

La lógica del servidor impide cambiar el propietario. El rol técnico de EC2 tiene acceso a la tabla completa, por lo que el aislamiento entre usuarios depende de esa lógica.

## 16. Operación y diagnóstico

En la sesión del servidor:

```bash
sudo journalctl -u tickets --since '10 minutes ago' --no-pager
sudo tail -n 30 /var/log/nginx/error.log
df -h
free -m
```

Los logs del backend contienen identificador de solicitud, resultado y duración. El formato de acceso Nginx excluye argumentos para no registrar códigos OAuth del callback. Los logs permanecen en EC2. Esta plantilla no instala CloudWatch Agent ni envía logs a CloudWatch Logs.

Usa las métricas básicas de EC2 para CPU, red y comprobaciones de estado. La memoria y el disco se revisan dentro del servidor, o con un agente adicional si decides instalarlo y presupuestarlo.

El equipo administra actualizaciones de Amazon Linux, parches de dependencias, rotación de logs y recuperación. EC2 mantiene el consumo mientras está encendido, aunque no reciba solicitudes.

## 17. Problemas frecuentes

| Síntoma | Revisión |
| --- | --- |
| `AccessDenied` al crear el stack | Evento fallido y permisos de despliegue |
| Falla la regla de prefix list | ID regional y cuota ponderada del security group |
| Nodo SSM no aparece | Instance profile, agente, Elastic IP y ruta a Internet |
| Instalación SSM en `Failed` | Salida del comando, repositorios y espacio en disco |
| CloudFront devuelve `502` o `504` | Servicio Nginx, DNS del origen, puerto 80 y prefix list |
| CloudFront devuelve `403` | Encabezado secreto, Nginx y acceso por HTTPS |
| Nginx devuelve `502` | Gunicorn, variables de entorno y logs de systemd |
| `redirect_mismatch` | Callback Cognito y `config.js`, incluida la barra final |
| API devuelve `401` | Sesión vencida, access token y configuración de cliente/emisor |
| API devuelve `503` de identidad | Conectividad HTTPS desde EC2 hacia las claves JWKS |
| API devuelve `429` | Límite global de Nginx o capacidad DynamoDB |
| EC2 responde lento | Memoria disponible y créditos de CPU del modo Standard |

No abras SSH ni Gunicorn a Internet para diagnosticar. SSM permite revisar los servicios sin esas reglas.

## 18. Actualizaciones y límites

Para cambiar el código, ejecuta pruebas, vuelve a generar el paquete y repite los pasos de publicación e instalación. El despliegue reinicia el proceso y puede interrumpir solicitudes. No implementa publicación sin caída ni rollback automático de aplicación.

Para cambios de infraestructura, valida la plantilla y usa **Update stack** con un change set en CloudFormation. Conserva el parámetro secreto existente. Si reemplazas la instancia, vuelve a instalar el paquete. En un laboratorio nuevo, también puedes eliminar y recrear los recursos.

Una sola EC2 constituye un punto único de fallo. Una ampliación de producción debería abordar HTTPS al origen, recuperación, respaldos, despliegues y disponibilidad. El tráfico sostenido puede superar CPU y memoria de `t3.micro`.

Detener EC2 reduce el cómputo, pero deja el sitio sin servicio. El disco y la Elastic IP siguen existiendo. Si liberas manualmente la Elastic IP, revisa el DNS del origen y la configuración de CloudFront antes de volver a publicar.

## 19. Eliminación del laboratorio

La eliminación borra tickets y usuarios. Guarda primero las evidencias necesarias.

```bash
aws sts get-caller-identity
```

Confirma que `BUCKET_NAME` pertenece a este stack y vacíalo:

```bash
aws s3 rm "s3://$BUCKET_NAME/" --recursive --only-show-errors
aws cloudformation delete-stack --stack-name aprende-tickets-ec2
aws cloudformation wait stack-delete-complete --stack-name aprende-tickets-ec2
```

CloudFormation elimina la instancia, su volumen raíz, la asociación y asignación de Elastic IP, Cognito, DynamoDB y los recursos de red. CloudFront puede requerir varios minutos. Si queda `DELETE_FAILED`, consulta el recurso y reintenta cuando resuelvas la causa. Si es necesario, deshabilita primero la distribución y espera su despliegue.

Verifica en EC2 que no queden volúmenes ni Elastic IP del laboratorio. Si creaste snapshots, recursos adicionales o logs externos manualmente, revísalos por separado. Consulta Billing tras su siguiente actualización.

`parameters.json` contiene un secreto del origen ya eliminado. Retíralo junto con los archivos locales generados cuando ya no los necesites. No borres los archivos fuente del proyecto.

## 20. Evidencias de entrega

- [ ] Arquitectura con EC2 identificado como núcleo de la aplicación.
- [ ] Instancia, volumen y security group revisados.
- [ ] Aplicación servida por Nginx y API por Gunicorn/systemd.
- [ ] Inicio de sesión y creación de ticket desde el navegador.
- [ ] Prueba de aislamiento entre Ana y Bruno.
- [ ] Revisión de logs y métricas del servidor.
- [ ] Consumo registrado antes de créditos.
- [ ] Eliminación comprobada, incluida Elastic IP y EBS.

Fuentes de implementación: [Python en Amazon Linux 2023](https://docs.aws.amazon.com/linux/al2023/ug/python.html), [encabezados de origen CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/add-origin-custom-headers.html), [políticas de solicitudes al origen](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-origin-request-policies.html), [políticas de caché](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html).
