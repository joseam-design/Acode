/*
	Language servers that expose stdio are proxied through a lightweight
	WebSocket bridge so the CodeMirror client can continue to speak WebSocket.
*/

import type { Transport } from "@codemirror/lsp-client";
import type {
	LspServerDefinition,
	TransportContext,
	TransportHandle,
	WebSocketTransportOptions,
} from "./types";

const DEFAULT_TIMEOUT = 5000;
const RECONNECT_BASE_DELAY = 500;
const RECONNECT_MAX_DELAY = 10000;
const RECONNECT_MAX_ATTEMPTS = 5;

type MessageListener = (data: string) => void;

interface TransportInterface extends Transport {
	send(message: string): void;
	subscribe(handler: MessageListener): void;
	unsubscribe(handler: MessageListener): void;
}

/**
 * Parsea uno o más mensajes LSP del buffer acumulado.
 *
 * El protocolo base de LSP (spec Microsoft) exige framing con Content-Length
 * tanto para envío como para recepción, independientemente del transporte
 * (WebSocket, stdio, TCP). Sin este parsing, los diagnósticos (líneas rojas),
 * autocompletado y hover fallan en todos los servidores estrictos como
 * Dart/Flutter, y pueden fallar intermitentemente en TS/Python con mensajes
 * grandes o fragmentados en múltiples frames WebSocket.
 *
 * @returns parsed    - cuerpos JSON completos listos para despachar a listeners
 * @returns remaining - fragmento incompleto que debe quedar en el buffer
 *                      hasta el próximo frame WebSocket
 */
function parseLspMessages(buffer: string): {
	parsed: string[];
	remaining: string;
} {
	const parsed: string[] = [];
	const HEADER_SEP = "\r\n\r\n";
	let pos = 0;

	while (pos < buffer.length) {
		const sepIdx = buffer.indexOf(HEADER_SEP, pos);

		if (sepIdx === -1) {
			// Sin separador de header: puede ser JSON plano (backward compat con
			// servidores que no usan Content-Length) o un fragmento incompleto.
			const fragment = buffer.substring(pos).trim();
			if (fragment.startsWith("{")) {
				try {
					JSON.parse(fragment);
					parsed.push(fragment);
					pos = buffer.length;
				} catch {
					// Fragmento incompleto — retener en buffer hasta el próximo frame
				}
			}
			break;
		}

		// Hay separador: extraer valor de Content-Length del header
		const headerPart = buffer.substring(pos, sepIdx);
		const match = /Content-Length:\s*(\d+)/i.exec(headerPart);

		if (!match) {
			// Header presente pero sin Content-Length — protocolo inesperado,
			// saltar este bloque e intentar el siguiente
			pos = sepIdx + HEADER_SEP.length;
			continue;
		}

		const contentLength = parseInt(match[1], 10);
		const bodyStart = sepIdx + HEADER_SEP.length;
		const bodyEnd = bodyStart + contentLength;

		if (bodyEnd > buffer.length) {
			// Mensaje incompleto — retener desde pos en buffer
			break;
		}

		parsed.push(buffer.substring(bodyStart, bodyEnd));
		pos = bodyEnd;
	}

	return {
		parsed,
		remaining: pos < buffer.length ? buffer.substring(pos) : "",
	};
}

function createWebSocketTransport(
	server: LspServerDefinition,
	context: TransportContext,
): TransportHandle {
	const transport = server.transport;
	if (!transport) {
		throw new Error(
			`LSP server ${server.id} is missing transport configuration`,
		);
	}

	let url = transport.url;
	const options: WebSocketTransportOptions = transport.options ?? {};

	// Use dynamic port from auto-port discovery if available
	if (context.dynamicPort && context.dynamicPort > 0) {
		url = `ws://127.0.0.1:${context.dynamicPort}/`;
		console.info(
			`[LSP:${server.id}] Using auto-discovered port ${context.dynamicPort}`,
		);
	}

	// URL is only required when not using dynamic port
	if (!url) {
		throw new Error(
			`WebSocket transport for ${server.id} has no URL (and no dynamic port available)`,
		);
	}

	// Store validated URL in a const for TypeScript narrowing in nested functions
	const wsUrl: string = url;

	const listeners = new Set<MessageListener>();
	const binaryMode = !!options.binary;
	const timeout = options.timeout ?? DEFAULT_TIMEOUT;
	const enableReconnect = options.reconnect !== false;
	const maxReconnectAttempts =
		options.maxReconnectAttempts ?? RECONNECT_MAX_ATTEMPTS;

	let socket: WebSocket | null = null;
	let disposed = false;
	let reconnectAttempts = 0;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let connected = false;

	// Buffer acumulador: los mensajes LSP pueden llegar fragmentados en múltiples
	// frames WebSocket, o varios mensajes pueden llegar en un mismo frame.
	// Sin este buffer, parseLspMessages solo vería fragmentos y descartaría datos.
	let messageBuffer = "";

	// NOTA: `encoder` se mantiene igual que en el original (línea 72).
	// sendFramed() usa su propio TextEncoder local para evitar variable shadow.
	const encoder = binaryMode ? new TextEncoder() : null;

	/**
	 * Envía un mensaje LSP con el framing Content-Length requerido por el
	 * protocolo base de LSP (https://microsoft.github.io/language-server-protocol/
	 * specifications/lsp/3.17/specification/#baseProtocol).
	 *
	 * IMPORTANTE: Content-Length debe indicar el tamaño en BYTES UTF-8 del body,
	 * no la longitud de la cadena JS (que cuenta code units y difiere para
	 * caracteres multibyte como emoji o CJK).
	 *
	 * Se usa en dos lugares:
	 *   1. transportInterface.send() — mensajes del cliente al servidor
	 *   2. dispatchToListeners() — auto-respuesta a window/workDoneProgress/create
	 */
	function sendFramed(message: string): void {
		const utf8Encoder = new TextEncoder();
		const bodyBytes = utf8Encoder.encode(message);
		const framedMessage = `Content-Length: ${bodyBytes.length}\r\n\r\n${message}`;
		if (binaryMode && encoder) {
			socket!.send(utf8Encoder.encode(framedMessage));
		} else {
			socket!.send(framedMessage);
		}
	}

	function createSocket(): WebSocket {
		try {
			// pylsp's websocket endpoint does not require subprotocol negotiation.
			// Avoid passing protocols to keep the handshake simple.
			const ws = new WebSocket(wsUrl);
			if (binaryMode) {
				ws.binaryType = "arraybuffer";
			}
			return ws;
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			throw new Error(
				`Failed to construct WebSocket for ${server.id} (${wsUrl}): ${message}`,
			);
		}
	}

	/**
	 * Extrae mensajes LSP completos del buffer acumulado y los despacha.
	 * Actualiza messageBuffer con el fragmento incompleto restante (si hay).
	 */
	function flushLspBuffer(): void {
		const result = parseLspMessages(messageBuffer);
		if (result.parsed.length > 0) {
			result.parsed.forEach((msg) => dispatchToListeners(msg));
		}
		messageBuffer = result.remaining;
	}

	function handleMessage(event: MessageEvent): void {
		if (typeof event.data === "string") {
			messageBuffer += event.data;
			flushLspBuffer();
		} else if (event.data instanceof Blob) {
			// Handle Blob synchronously by queuing - avoids async ordering issues
			event.data
				.text()
				.then((text: string) => {
					messageBuffer += text;
					flushLspBuffer();
				})
				.catch((err: Error) => {
					console.error("Failed to read Blob message", err);
				});
		} else if (event.data instanceof ArrayBuffer) {
			messageBuffer += new TextDecoder().decode(event.data);
			flushLspBuffer();
		} else {
			console.warn(
				"Unknown WebSocket message type",
				typeof event.data,
				event.data,
			);
			messageBuffer += String(event.data);
			flushLspBuffer();
		}
	}

	function dispatchToListeners(data: string): void {
		// Debugging aid while stabilising websocket transport
		if (context?.debugWebSocket) {
			console.debug(`[LSP:${server.id}] <=`, data);
		}

		// Temporary fix
		// Intercept server requests that the CodeMirror LSP client doesn't handle
		// The client only handles notifications, but some servers (e.g., TypeScript)
		// send requests like window/workDoneProgress/create that need a response
		try {
			const msg = JSON.parse(data);
			if (
				msg &&
				typeof msg.id !== "undefined" &&
				msg.method === "window/workDoneProgress/create"
			) {
				// This is a request, respond with success
				const response = JSON.stringify({
					jsonrpc: "2.0",
					id: msg.id,
					result: null,
				});
				if (context?.debugWebSocket) {
					console.debug(`[LSP:${server.id}] => (auto-response)`, response);
				}
				if (socket && socket.readyState === WebSocket.OPEN) {
					// Usar sendFramed: la auto-respuesta también debe llevar Content-Length
					// (el send directo previo era otro punto donde se enviaba JSON plano)
					sendFramed(response);
				}
				// Don't pass this request to listeners since we handled it
				console.info(
					`[LSP:${server.id}] Auto-responded to window/workDoneProgress/create`,
				);
				return;
			}
		} catch (_) {
			// Not valid JSON or missing fields, pass through normally
		}

		listeners.forEach((listener) => {
			try {
				listener(data);
			} catch (error) {
				console.error("LSP transport listener failed", error);
			}
		});
	}

	function handleClose(event: CloseEvent): void {
		connected = false;
		messageBuffer = ""; // Descartar datos incompletos al cerrar la conexión
		if (disposed) return;

		const wasClean = event.wasClean || event.code === 1000;
		if (wasClean) {
			console.info(`[LSP:${server.id}] WebSocket closed cleanly`);
			return;
		}

		console.warn(
			`[LSP:${server.id}] WebSocket closed unexpectedly (code: ${event.code})`,
		);

		if (enableReconnect && reconnectAttempts < maxReconnectAttempts) {
			scheduleReconnect();
		} else if (reconnectAttempts >= maxReconnectAttempts) {
			console.error(`[LSP:${server.id}] Max reconnection attempts reached`);
		}
	}

	function handleError(event: Event): void {
		if (disposed) return;
		const errorEvent = event as ErrorEvent;
		const reason =
			errorEvent?.message || errorEvent?.type || "connection error";
		console.error(`[LSP:${server.id}] WebSocket error: ${reason}`);
	}

	function scheduleReconnect(): void {
		if (disposed || reconnectTimer) return;

		const delay = Math.min(
			RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts),
			RECONNECT_MAX_DELAY,
		);
		reconnectAttempts++;

		console.info(
			`[LSP:${server.id}] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${maxReconnectAttempts})`,
		);

		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			if (disposed) return;
			attemptReconnect();
		}, delay);
	}

	function attemptReconnect(): void {
		if (disposed) return;

		try {
			socket = createSocket();
			setupSocketHandlers(socket);

			socket.onopen = () => {
				connected = true;
				reconnectAttempts = 0;
				messageBuffer = ""; // Limpiar buffer también al reconectar
				console.info(`[LSP:${server.id}] Reconnected successfully`);
				if (socket) {
					socket.onopen = null;
				}
			};
		} catch (error) {
			console.error(`[LSP:${server.id}] Reconnection failed`, error);
			if (reconnectAttempts < maxReconnectAttempts) {
				scheduleReconnect();
			}
		}
	}

	function setupSocketHandlers(ws: WebSocket): void {
		ws.onmessage = handleMessage;
		ws.onclose = handleClose;
		ws.onerror = handleError;
	}

	// Initial socket creation
	socket = createSocket();

	const ready = new Promise<void>((resolve, reject) => {
		const timeoutId = setTimeout(() => {
			if (socket) {
				socket.onopen = null;
				socket.onerror = null;
			}
			try {
				socket?.close();
			} catch (_) {
				// Ignore close errors
			}
			reject(new Error(`Timed out opening WebSocket for ${server.id}`));
		}, timeout);

		if (socket) {
			socket.onopen = () => {
				clearTimeout(timeoutId);
				connected = true;
				if (socket) {
					setupSocketHandlers(socket);
				}
				resolve();
			};

			socket.onerror = (event: Event) => {
				clearTimeout(timeoutId);
				if (socket) {
					socket.onopen = null;
					socket.onerror = null;
				}
				const errorEvent = event as ErrorEvent;
				const reason =
					errorEvent?.message || errorEvent?.type || "connection error";
				reject(new Error(`WebSocket error for ${server.id}: ${reason}`));
			};
		}
	});

	const transportInterface: TransportInterface = {
		send(message: string): void {
			if (!connected || !socket || socket.readyState !== WebSocket.OPEN) {
				throw new Error("WebSocket transport is not open");
			}
			if (context?.debugWebSocket) {
				console.debug(`[LSP:${server.id}] =>`, message);
			}
			sendFramed(message);
		},
		subscribe(handler: MessageListener): void {
			listeners.add(handler);
		},
		unsubscribe(handler: MessageListener): void {
			listeners.delete(handler);
		},
	};

	const dispose = (): void => {
		disposed = true;
		connected = false;
		messageBuffer = ""; // Limpiar buffer al destruir el transport

		if (reconnectTimer) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}

		listeners.clear();

		if (socket) {
			if (
				socket.readyState === WebSocket.CLOSED ||
				socket.readyState === WebSocket.CLOSING
			) {
				return;
			}
			try {
				socket.close(1000, "Client disposed");
			} catch (_) {
				// Ignore close errors
			}
		}
	};

	return { transport: transportInterface, dispose, ready };
}

function createStdioTransport(
	server: LspServerDefinition,
	context: TransportContext,
): TransportHandle {
	if (!server.transport) {
		throw new Error(
			`LSP server ${server.id} is missing transport configuration`,
		);
	}
	if (
		!server.transport.url &&
		!(context.dynamicPort && context.dynamicPort > 0)
	) {
		throw new Error(
			`STDIO transport for ${server.id} is missing a websocket bridge url`,
		);
	}
	if (!server.transport.options?.binary) {
		console.info(
			`LSP server ${server.id} is using stdio bridge without binary mode. Falling back to text frames.`,
		);
	}
	return createWebSocketTransport(server, context);
}

export function createTransport(
	server: LspServerDefinition,
	context: TransportContext = {},
): TransportHandle {
	if (!server) {
		throw new Error("createTransport requires a server configuration");
	}
	if (!server.transport) {
		throw new Error(
			`LSP server ${server.id || "unknown"} is missing transport configuration`,
		);
	}

	const kind = server.transport.kind;
	if (!kind) {
		throw new Error(
			`LSP server ${server.id} transport is missing 'kind' property`,
		);
	}

	switch (kind) {
		case "websocket":
			return createWebSocketTransport(server, context);
		case "stdio":
			return createStdioTransport(server, context);
		case "external":
			if (typeof server.transport.create === "function") {
				return server.transport.create(server, context);
			}
			throw new Error(
				`LSP server ${server.id} declares an external transport without a create() factory`,
			);
		default:
			throw new Error(`Unsupported transport kind: ${kind}`);
	}
}

export default { createTransport };
