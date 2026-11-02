# Guía para Windows (Git Bash)

Esta guía adapta los comandos del [README](../README.md), escritos para macOS/Linux, para quienes trabajan en **Windows 10/11 con Git Bash**. Cubre desde la instalación de herramientas hasta la creación de la infraestructura (secciones 4 a 8 del README).

Probado en Windows 11 con AWS CLI 2.39.1 y Python 3.12.10.

> **Importante:** ejecuta todo en **Git Bash en tu PC**, dentro de la carpeta del proyecto. No uses AWS CloudShell: ahí no está el proyecto clonado y los comandos fallan con `No such file or directory: 'template.yaml'`.

---

## 1. Requisitos

| Herramienta | Instalación | Verificación |
|---|---|---|
| Git for Windows (incluye Git Bash) | https://git-scm.com/download/win | `git --version` |
| AWS CLI v2 | Instalador MSI: https://awscli.amazonaws.com/AWSCLIV2.msi | `aws --version` → `aws-cli/2.x.x` |
| Python 3.12 o 3.13 | Ver más abajo | `py --version` |

Después de instalar cualquiera de ellas, **cierra y vuelve a abrir Git Bash** para que reconozca el nuevo `PATH`.

> Para ver la versión de AWS CLI usa `aws --version`. La opción `aws -v` no existe y muestra un error.

### Python: dos casos

Ejecuta `py --version`:

- **Caso A: muestra una versión** (por ejemplo `Python 3.12.10`). Ya tienes Python; continúa.
- **Caso B: dice que no se encontró Python o abre Microsoft Store.** Instala **Python Install Manager** (Microsoft Store o python.org), reabre Git Bash y ejecuta:

  ```bash
  py install 3.13
  py --version
  ```

Si al escribir `python3` se abre Microsoft Store: **Configuración → Aplicaciones → Configuración avanzada de aplicaciones → Alias de ejecución de aplicaciones** y desactiva `python.exe` y `python3.exe` ("Instalador de aplicaciones"). En todo caso, en Windows usa `py` o `python`, no `python3`.

### Clonar el proyecto

```bash
cd ~
git clone https://github.com/FraGoTe/sistema-tickets.git
cd sistema-tickets
```

El proyecto queda en `C:\Users\<tu-usuario>\sistema-tickets`. El archivo `.gitattributes` del repositorio hace que los archivos de `deploy/` mantengan finales de línea Linux (LF) aunque clones en Windows; sin eso, `install.sh` fallaría al ejecutarse en la EC2.

---

## 2. Equivalencias rápidas

| macOS/Linux (README) | Windows (Git Bash) |
|---|---|
| `python3 ...` | `python ...` (con el venv activo) o `py ...` |
| `source .venv/bin/activate` | `source .venv/Scripts/activate` |
| `cfn-lint template.yaml` | `cfn-lint template.yaml` o, si da `Permission denied`, `cfn-lint.exe template.yaml` |
| Comandos partidos en varias líneas con `\` | Escribirlos **en una sola línea** |
| `VAR=$(aws ... --output text)` | `VAR=$(aws ... --output text \| tr -d '\r')` |

**¿Por qué `tr -d '\r'`?** En Windows, `aws.exe` y `python.exe` terminan su salida con un carácter invisible `\r`. Si guardas esa salida en una variable, el `\r` queda pegado al valor y los comandos siguientes fallan.

**¿Por qué una sola línea?** Al copiar comandos partidos con `\` puede colarse un carácter invisible después de la barra, y el comando se rompe (por ejemplo `Invalid requirement: '-r'` en `pip`).

---

## 3. Credenciales AWS y variables de sesión (README §4)

### Iniciar sesión

```bash
aws login --profile tickets-signin
```

1. Cuando pregunte `AWS Region [us-east-1]:`, presiona **Enter** (o escribe la región que indique el curso).
2. Se abre el navegador: haz clic en tu sesión activa de AWS para autorizar.
3. Si pregunta `Configure AWS skills and the AWS MCP server...? [y/n/never]`, responde `n`.

> Si la pregunta de la región se cerró y escribes `us-east-1` en el prompt `$`, verás `bash: us-east-1: command not found`. Vuelve a ejecutar `aws login`.

### Crear el perfil del laboratorio

```bash
aws configure set credential_process "aws configure export-credentials --profile tickets-signin --format process" --profile tickets-lab
aws configure set region us-east-1 --profile tickets-lab
aws sts get-caller-identity --profile tickets-lab
```

El último comando debe mostrar tu `Account` y `Arn`.

> No necesitas `aws configure sso`. Ese método requiere IAM Identity Center y una URL de portal del tipo `https://d-xxxxxxxxxx.awsapps.com/start`; con la URL de la consola falla con `Invalid start url provided`.

### Variables de sesión

Ejecútalas **cada vez que abras Git Bash**:

```bash
export AWS_PROFILE=tickets-lab
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_PAGER=""
aws sts get-caller-identity
```

> Usa la **misma región** en el login, el perfil, estas variables y la consola. Si mezclas regiones, el stack se crea en una y los comandos lo buscan en otra.

La sesión de `aws login` expira. Si más tarde aparece un error de credenciales, vuelve a ejecutar `aws login --profile tickets-signin`.

---

## 4. Entorno Python y pruebas locales (README §6)

### Crear el entorno virtual

Usa la versión que mostró `py --version`:

- **Si tienes 3.12:** `py -3.12 -m venv .venv`
- **Si tienes 3.13:** `py -3.13 -m venv .venv`

El comando no muestra nada si funcionó.

### Activarlo

- **Git Bash** (recomendado, es la terminal de esta guía):

  ```bash
  source .venv/Scripts/activate
  ```

- **PowerShell:**

  ```powershell
  .venv\Scripts\Activate.ps1
  ```

Sabrás que está activo porque el prompt muestra `(.venv)`. En Git Bash puede verse como `((.venv) )`; es solo visual.

> `source .venv/bin/activate` (la versión de macOS/Linux) da error en Windows porque la carpeta se llama `Scripts`, no `bin`.

### Dependencias, pruebas y validación

```bash
python -m pip install -r backend/requirements.txt cfn-lint
python -m unittest discover -s tests -v
```

Las pruebas deben terminar en `OK`. El aviso amarillo `A new release of pip is available` no es un error.

Para validar la plantilla hay dos casos:

- **Si funciona:** `cfn-lint template.yaml`
- **Si da `Permission denied`:** `cfn-lint.exe template.yaml`

Si la plantilla es válida, **no muestra nada** y vuelve al prompt.

---

## 5. Preparación de parámetros (README §7)

```bash
PREFIX_LIST_ID=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query 'PrefixLists[0].PrefixListId' --output text | tr -d '\r')
echo "$PREFIX_LIST_ID"
python scripts/prepare_parameters.py --prefix-list-id "$PREFIX_LIST_ID"
```

- El `echo` debe mostrar un valor como `pl-3b927c52` (en `us-east-1`; cambia según la región).
- El script responde `parameters.json generado con permisos 600. No lo compartas.`
- Si responde `parameters.json ya existe`, consérvalo y continúa.

> Sin `| tr -d '\r'`, el script responde `Identificador de prefix list inválido`.

---

## 6. Creación de la infraestructura (README §8)

> A partir de aquí se crean recursos que consumen créditos o saldo. Al terminar el laboratorio, sigue la sección **19. Eliminación del laboratorio** del README.

```bash
aws cloudformation validate-template --template-body file://template.yaml
aws cloudformation create-stack --stack-name aprende-tickets-ec2 --template-body file://template.yaml --parameters file://parameters.json --capabilities CAPABILITY_IAM --tags Key=Proyecto,Value=TicketsEC2 Key=Ambiente,Value=Lab
aws cloudformation wait stack-create-complete --stack-name aprende-tickets-ec2
```

- `create-stack` devuelve un `StackId`.
- `wait` puede tardar **10 a 20 minutos sin mostrar nada**; no lo interrumpas. Termina cuando vuelve el prompt `$`.
- El avance se puede ver en la consola: **CloudFormation → Stacks → aprende-tickets-ec2 → Events**.
- No repitas `create-stack`: si el stack ya existe, falla con `AlreadyExistsException`.

---

## Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `python3`: "No se encontró Python" o se abre Microsoft Store | Alias de Windows; Python no instalado | Usa `py` o `python`. Ver **1. Requisitos → Python** |
| `source .venv/bin/activate`: No such file | En Windows la carpeta es `Scripts` | `source .venv/Scripts/activate` |
| `ERROR: Invalid requirement: '-r'` | Comando copiado en varias líneas con `\` | Escríbelo en una sola línea |
| `cfn-lint: Permission denied` | Ejecución del script desde Git Bash | `cfn-lint.exe template.yaml` |
| `Identificador de prefix list inválido` | `\r` invisible al final del valor | Agrega `\| tr -d '\r'` al capturar la salida |
| `No such file or directory: 'template.yaml'` | Se está ejecutando en CloudShell o fuera de la carpeta | Git Bash local, dentro de `~/sistema-tickets` |
| `bash: us-east-1: command not found` | La pregunta de región de `aws login` ya se cerró | Vuelve a ejecutar `aws login --profile tickets-signin` |
| `aws configure sso`: `Invalid start url provided` | Se usó la URL de la consola | No es necesario; usa `aws login` (sección 3) |
| `file deploy/install.sh` muestra `with CRLF line terminators` | Clonaste antes de que existiera `.gitattributes` | Clona de nuevo o ejecuta: `find backend deploy web -type f ! -path '*__pycache__*' -exec sed -i 's/\r$//' {} +` |
