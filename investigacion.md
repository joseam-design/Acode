# Investigacion LSP en Acode - Documento Tecnico

## 1. Resumen Ejecutivo

**Problema:** Los servidores LSP en Acode fracasan al conectarse via WebSocket/stdio. El servidor Dart `dart language-server --client-id acode` no recibe ni envia mensajes correctamente.

**Causa Raiz:** El protocolo LSP sobre WebSocket requiere腌制 de mensajes con `Content-Length: <bytes>\r\n\r\n<JSON>` cuando se usa sobre streams. Acode envia JSON plano directamente via WebSocket, lo cual confunde a servidores que esperan el protocolo standard de Content-Length.

---

## 2. Arquitectura LSP en Acode

### 2.1 Estructura de Archivos

```
src/cm/lsp/
|-- index.ts              # Exporta API publica
|-- api.ts                # API principal del cliente LSP
|-- clientManager.ts      # Gestiona clientes LSP por archivo (1191 lineas)
|-- transport.ts          # CREA CONEXIONES - PROBLEMA AQUI (400 lineas)
|-- serverLauncher.ts     # Inicia/gestiona servidores via terminal (1291 lineas)
|-- serverRegistry.ts     # Registro de servidores disponibles (428 lineas)
|-- serverCatalog.ts      # Catalogo de bundles de servidores
|-- types.ts              # Definiciones de tipos TypeScript (534 lineas)
|-- diagnostics.ts        # Manejo de diagnosticos/errors
|-- tooltipExtensions.ts  # Hover tooltips
|-- formatter.ts          # Formateo de codigo
|-- inlayHints.ts         # Inlay hints
|-- workspace.ts          # Workspace management
|-- codeActions.ts        # Code actions
|-- documentSymbols.ts    # Document symbols
|-- rename.ts             # Rename support
|-- references.ts         # Find references
|-- installRuntime.ts     # Instalacion de runtime
|-- installerUtils.ts    # Utilidades de instalacion
|-- providerUtils.ts      # Utilidades de providers
|-- formattingSupport.ts  # Soporte de formateo
|-- providerUtils.ts      # Utilidades de providers
|-- servers/              # Definiciones de servidores
|   |-- index.ts
|   |-- javascript.ts     # TypeScript, vtsls, eslint (308 lineas)
|   |-- python.ts         # Python (ty, pylsp)
|   |-- systems.ts
|   |-- web.ts
|   |-- shared.ts
|   |-- luau.ts
```

### 2.2 Flujo de Conexion LSP

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DE CONEXION LSP                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. serverLauncher.ensureServerRunning()                         │
│     ├─> Verifica si terminal esta instalada                      │
│     ├─> Verifica instalacion del servidor                        │
│     ├─> startInteractiveServer()                                 │
│     │   └─> Ejecuta: $PREFIX/axs lsp --session {id} {cmd}      │
│     │                                                            │
│  2. axs bridge escribe puerto en:                                │
│     ~/.axs/lsp_ports/{serverName}_{session}                      │
│                                                                  │
│  3. serverLauncher.getLspPort()                                 │
│     └─> Lee archivo de puerto                                   │
│                                                                  │
│  4. transport.createTransport()                                  │
│     ├─> Crea WebSocket a ws://127.0.0.1:{port}/                 │
│     │   └─> USA WebSocket NATIVO del browser (NO el plugin!)    │
│     │                                                            │
│  5. clientManager.#initializeClient()                           │
│     ├─> new LSPClient(config)                                   │
│     └─> client.connect(transport)                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Componentes Clave

| Archivo | Lineas | Responsabilidad | Relevancia |
|---------|--------|-----------------|------------|
| `transport.ts` | 400 | Crea conexiones WebSocket/stdio | **CRITICO** - aqui se origina el problema |
| `clientManager.ts` | 1191 | Gestiona clientes LSP por archivo | Alto |
| `serverLauncher.ts` | 1291 | Inicia servidores, auto-port discovery | Alto |
| `serverRegistry.ts` | 428 | Registro de servidores | Medio |
| `websocket.js` (plugin) | 188 | Plugin Cordova WebSocket | **NO SE USA** |

---

## 3. El Problema Identificado: Protocolo Content-Length

### 3.1 Protocolo LSP Standard (para streams)

Segun `vscode-languageserver-protocol`, cuando se usa LSP sobre streams (TCP, stdio, WebSocket con stream semantics):

```
Content-Length: <numero de bytes en el body>\r\n
Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n
\r\n
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {...}
}
```

### 3.2 Que Env Acode vs. Lo Que Espera El Servidor

**Lo que Acode envia (WRONG):**
```javascript
// transport.ts:298 - ENVIO DIRECTO DE JSON
socket.send(message);  // "{"jsonrpc":"2.0","id":1,..."
```

**Lo que espera un servidor LSP standard (CORRECTO):**
```
Content-Length: 156\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
```

### 3.3 Evidencia en el Codigo

**Archivo:** `src/cm/lsp/transport.ts:290-300`
```typescript
const transportInterface: TransportInterface = {
  send(message: string): void {
    if (!connected || !socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket transport is not open");
    }
    if (binaryMode && encoder) {
      socket.send(encoder.encode(message));  // ← Solo codifica, no agrega Content-Length
    } else {
      socket.send(message);  // ← ENVIA JSON PLANO
    }
  },
```

**No hay handling de Content-Length en todo el archivo.**

### 3.4 Test Manual Exitoso

Tu test en Python funciono porque agrego manualmente el header:

```python
message = f'Content-Length: {len(init)}\r\n\r\n{init}'  # ← SI incluye Content-Length
```

---

## 4. Por Que Funciona Con Otros Servidores (Teoria)

### 4.1 Servidores Que Funcionan

- **TypeScript (typescript-language-server)** - Configurado como `websocket` pero probablemente tiene parsing robusto
- **Python (pylsp)** - Especificamente dice en `transport.ts:76` que no requiere subprotocol negotiation

### 4.2 Servidores Que Fallasn

- **Dart language-server** - Es strict con el protocolo Content-Length
- **Flutter/Dart LSP servers** - Siguen estrictamente el spec de LSP

### 4.3 Diferencia Tecnica

| Servidor | Maneja JSON directo? | Espera Content-Length? |
|----------|---------------------|------------------------|
| typescript-language-server | Si (via websocket bridge) | No - usa bridge axs |
| pylsp | Si | No - usa bridge axs |
| dart language-server | **No** | **Si** |
| flutter analysis server | **No** | **Si** |

---

## 5. Por Que No Se Usa El Plugin Cordova WebSocket

### 5.1 Plugin WebSocket

**Archivo:** `src/plugins/websocket/www/websocket.js` (188 lineas)

```javascript
// Este plugin NUNCA se usa en el codigo LSP
const connect = function(url, protocols = null, headers = null, binaryType) {
    return new Promise((resolve, reject) => {
        exec(instanceId => resolve(new WebSocketInstance(url, instanceId)),
             reject, "WebSocketPlugin", "connect", [...]);
    });
};
```

### 5.2 WebSocket Nativo del Browser

**Archivo:** `src/cm/lsp/transport.ts:78`
```typescript
const ws = new WebSocket(wsUrl);  // ← WebSocket del browser, NO el plugin Cordova
```

**Tambien en:** `src/cm/lsp/serverLauncher.ts:249`
```typescript
const ws = new WebSocket(url);  // ← Para checkServerAlive
```

---

## 6. Soluciones Posibles

### 6.1 Solucion A: Modificar transport.ts para agregar Content-Length (RECOMENDADA)

**Archivo a modificar:** `src/cm/lsp/transport.ts`

**Cambios requeridos:**

1. **En la funcion send():**
```typescript
send(message: string): void {
  if (!connected || !socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("WebSocket transport is not open");
  }
  
  // AGREGAR: Codificar mensaje con Content-Length
  const encoder = new TextEncoder();
  const bytes = encoder.encode(message);
  const contentLength = bytes.length;
  
  // Construir header LSP
  const header = `Content-Length: ${contentLength}\r\n`;
  const framedMessage = header + message;
  
  if (binaryMode && encoder) {
    socket.send(encoder.encode(framedMessage));
  } else {
    socket.send(framedMessage);
  }
}
```

2. **En handleMessage():**
```typescript
function handleMessage(event: MessageEvent): void {
  let data: string;
  if (typeof event.data === "string") {
    data = event.data;
  } else if (event.data instanceof ArrayBuffer) {
    data = new TextDecoder().decode(event.data);
  } else if (event.data instanceof Blob) {
    event.data.text().then((text: string) => {
      dispatchToListeners(text);
    });
    return;
  } else {
    console.warn("Unknown WebSocket message type", typeof event.data);
    data = String(event.data);
  }
  
  // PARSEAR: Extraer mensajes del stream con Content-Length
  const messages = parseLspMessages(data);
  messages.forEach((msg) => dispatchToListeners(msg));
}
```

3. **Nueva funcion parseLspMessages():**
```typescript
function parseLspMessages(data: string): string[] {
  const messages: string[] = [];
  const headerEnd = "\r\n\r\n";
  
  // Buscar todos los mensajes con Content-Length
  let pos = 0;
  while (pos < data.length) {
    const headerIdx = data.indexOf(headerEnd, pos);
    if (headerIdx === -1) break;
    
    // Extraer Content-Length
    const headerPart = data.substring(pos, headerIdx);
    const match = /Content-Length:\s*(\d+)/i.exec(headerPart);
    
    if (!match) {
      // No hay Content-Length, tratar como mensaje plano (backward compat)
      messages.push(data.substring(pos));
      break;
    }
    
    const contentLength = parseInt(match[1], 10);
    const bodyStart = headerIdx + headerEnd.length;
    const bodyEnd = bodyStart + contentLength;
    
    if (bodyEnd > data.length) {
      // Mensaje incompleto
      break;
    }
    
    const message = data.substring(bodyStart, bodyEnd);
    messages.push(message);
    pos = bodyEnd;
  }
  
  return messages;
}
```

### 6.2 Solucion B: Soportar Ambos Protocolos

Detectar automaticamente si el servidor usa Content-Length o JSON plano:

```typescript
function parseLspMessages(data: string): string[] {
  // Intentar parsing con Content-Length primero
  const contentLengthMatch = data.match(/Content-Length:\s*(\d+)/i);
  
  if (contentLengthMatch) {
    // Usar protocolo standard
    return parseContentLengthMessages(data);
  } else {
    // Backward compatibility: JSON plano
    try {
      JSON.parse(data);
      return [data];
    } catch {
      return [];
    }
  }
}
```

### 6.3 Solucion C: Crear Transport Dedicado para Dart/Flutter

Crear un transport especifico que maneje Content-Length:

**Nuevo archivo:** `src/cm/lsp/transports/dartLspTransport.ts`

```typescript
import type { Transport, TransportHandle } from "./types";
import type { LspServerDefinition, TransportContext } from "./types";

export function createDartLspTransport(
  server: LspServerDefinition,
  context: TransportContext,
): TransportHandle {
  // Implementacion con Content-Length
}
```

---

## 7. Configuracion de Servidores para Dart/Flutter

### 7.1 Servidor Suggested: Dart Analysis Server

El servidor standard de Dart/Flutter es `dart_language_server` o usar el analysis server directamente:

```dart
dart --observe=PORT path/to/project
```

### 7.2 Servidores Alternativos

1. **dart_language_server** (NPM):
   ```bash
   npm install -g dart_language_server
   ```

2. **analysis_server** (incluido en Dart SDK):
   ```bash
   $DART_SDK/bin/dart $DART_SDK/bin/snapshots/analysis_server.dart.snapshot --client-id=acode --client-version=1.0
   ```

### 7.3 Configuracion Recomendada en Acode

Para configurar un servidor Dart personalizado:

1. Ir a Settings > LSP Settings
2. Agregar servidor custom:
   - **ID:** `dart`
   - **Label:** `Dart / Flutter`
   - **Languages:** `dart`
   - **Transport:** WebSocket o stdio
   - **Command:** `dart_language_server` o path al analysis server
   - **Args:** segun el servidor

---

## 8. Debugging y Logging

### 8.1 Habilitar Debug WebSocket

El codigo tiene suporte para debug en `transport.ts:121-123`:

```typescript
if (context?.debugWebSocket) {
  console.debug(`[LSP:${server.id}] <=`, data);
}
```

Para habilitar, pasar `debugWebSocket: true` en `TransportContext`.

### 8.2 Log Messages en ServerLauncher

**Archivo:** `src/cm/lsp/serverLauncher.ts:946-955`

```typescript
const callback: ExecutorCallback = (type, data) => {
  if (type === "stderr") {
    if (/proot warning/i.test(data)) return;
    console.warn(`[LSP:${serverId}] ${data}`);
  } else if (type === "stdout" && data && data.trim()) {
    console.info(`[LSP:${serverId}] ${data}`);
    if (/listening on/i.test(data)) {
      signalServerReady(serverId);
    }
  }
};
```

### 8.3 Log en ClientManager

**Archivo:** `src/cm/lsp/clientManager.ts:63-72`

```typescript
function isVerboseLspLoggingEnabled(): boolean {
  const buildInfo = (globalThis as { BuildInfo?: { debug?: boolean } })
    .BuildInfo;
  return !!buildInfo?.debug;
}
```

Habilitar poniendo `debug: true` en BuildInfo global.

---

## 9. Archivos Especificos a Modificar

### 9.1 Lista de Archivos Criticos

| # | Archivo | Cambios | Prioridad |
|---|---------|---------|-----------|
| 1 | `src/cm/lsp/transport.ts` | Agregar Content-Length parsing/generation | **ALTA** |
| 2 | `src/cm/lsp/transport.ts` | Modificar send() para enviar con headers | **ALTA** |
| 3 | `src/cm/lsp/transport.ts` | Modificar handleMessage() para parsear | **ALTA** |
| 4 | `src/cm/lsp/transport.ts` | Agregar parseLspMessages() | **ALTA** |
| 5 | `src/cm/lsp/clientManager.ts` | Pasar debugWebSocket en context | MEDIA |
| 6 | `src/settings/lspSettings.js` | UI para configurar dart server | BAJA |
| 7 | `src/settings/lspServerDetail.js` | Detalle del servidor | BAJA |

### 9.2 Diff de Cambios Recomendados

**transport.ts - Funcion send():**

```diff
 send(message: string): void {
   if (!connected || !socket || socket.readyState !== WebSocket.OPEN) {
     throw new Error("WebSocket transport is not open");
   }
+  const encoder = new TextEncoder();
+  const bytes = encoder.encode(message);
+  const header = `Content-Length: ${bytes.length}\r\n\r\n`;
+  const framedMessage = header + message;
   if (binaryMode && encoder) {
-    socket.send(encoder.encode(message));
+    socket.send(encoder.encode(framedMessage));
   } else {
-    socket.send(message);
+    socket.send(framedMessage);
   }
 }
```

**transport.ts - Nueva funcion parseLspMessages():**

```typescript
function parseLspMessages(data: string): string[] {
  const messages: string[] = [];
  const headerEnd = "\r\n\r\n";
  let pos = 0;
  
  while (pos < data.length) {
    const headerIdx = data.indexOf(headerEnd, pos);
    if (headerIdx === -1) {
      // Intentar parsing como JSON plano
      try {
        JSON.parse(data.substring(pos));
        messages.push(data.substring(pos));
      } catch {}
      break;
    }
    
    const headerPart = data.substring(pos, headerIdx);
    const match = /Content-Length:\s*(\d+)/i.exec(headerPart);
    
    if (!match) {
      messages.push(data.substring(pos));
      break;
    }
    
    const contentLength = parseInt(match[1], 10);
    const bodyStart = headerIdx + headerEnd.length;
    const bodyEnd = bodyStart + contentLength;
    
    if (bodyEnd > data.length) break;
    
    messages.push(data.substring(bodyStart, bodyEnd));
    pos = bodyEnd;
  }
  
  return messages;
}
```

---

## 10. Plan de Implementacion

### Fase 1: Fix Critico (transport.ts)
1. Modificar `send()` para agregar Content-Length
2. Modificar `handleMessage()` para parsear con Content-Length
3. Test con servidor Dart manual

### Fase 2: Server Dart/Flutter
1. Crear configuracion de servidor Dart en `serverCatalog.ts`
2. Definir installer para `dart_language_server`
3. Test de conexion completa

### Fase 3: Testing
1. Test con dart_language_server
2. Test con analysis_server de Flutter
3. Test de syntax highlighting
4. Test de error reporting
5. Test de autocomplete

### Fase 4: UI
1. Agregar servidor Dart a la lista predefinida
2. Mejorar UI de configuracion LSP

---

## 11. Recursos y Referencias

### Protocolo LSP
- Especificacion: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
- Content-Length: Seccion "Base Protocol"

### Archivos de Referencia
- `vscode-languageserver-protocol`: Maneja Content-Length en `ReadableStreamMessageReader`
- `@codemirror/lsp-client`: Cliente LSP que espera Content-Length en el transporte

### Servidores Dart/Flutter
- `dart_language_server`: https://github.com/natee-ack/natee_server
- Analysis Server: Incluido en `$DART_SDK/bin/snapshots/analysis_server.dart.snapshot`

---

## 12. Preguntas Abiertas y Dudas

1. **El bridge axs:** El codigo menciona que axs proxy maneja la conversion. Confirmar si axs agrega/parsea Content-Length.

2. **WebSocket vs stdio:** El servidor Dart dice `--stdio` pero se conecta por WebSocket. Hay un mismatch.

3. **Binary mode:** El codigo tiene soporte para modo binario pero no esta claro si ayuda con Content-Length.

4. **Seguridad:** Al agregar Content-Length, asegurar que no se expongan datos sensibles en logs.

5. **Backward compatibility:** Mantener compatibilidad con servidores que no usan Content-Length.

---

## 13. Test Cases

### TC-1: Connection basica
```bash
websocketd --port=9999 dart language-server --client-id acode
# Acode deberia conectarse a ws://127.0.0.1:9999
```

### TC-2: Initialize handshake
```bash
# Enviar initialize y recibir response
```

### TC-3: Syntax errors
```python
# python3 -c "import asyncio, websockets, json..."
# Enviar diagnostico y verificar que aparece en Acode
```

### TC-4: Autocomplete
```bash
# Enviar completion request
# Verificar que aparecen sugerencias en Acode
```

---

## 14. Conclusiones

El problema principal de LSP en Acode es que **no implementa el protocolo Content-Length** requerido por servidores LSP estrictos como el de Dart/Flutter. La solucion es modificar `transport.ts` para:

1. **Enviar** mensajes con `Content-Length: <bytes>\r\n\r\n<JSON>`
2. **Recibir** y parsear mensajes con el mismo formato
3. Mantener backward compatibility con servidores mas flexibles

El fix es relativamente simple (20-30 lineas de codigo) pero tiene alto impacto en la funcionalidad LSP de Acode.