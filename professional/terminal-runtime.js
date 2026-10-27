#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { spawn } from 'node-pty';
import { WebSocketServer } from 'ws';

const sessionName = 'HESTIASID';
// node-pty changes UID/GID; never let its children inherit root's extra groups.
if (process.getuid() !== 0) throw new Error('The terminal service requires its reviewed root unit');
process.setgroups([]);
const hostname = execFileSync('/bin/hostname', [], { encoding: 'utf8', timeout: 2000 }).trim();
const systemIPs = JSON.parse(
	execFileSync(`${process.env.HESTIA}/bin/v-list-sys-ips`, ['json'], { encoding: 'utf8', timeout: 2000 }),
);
const { config } = JSON.parse(
	execFileSync(`${process.env.HESTIA}/bin/v-list-sys-config`, ['json'], { encoding: 'utf8', timeout: 2000 }),
);

function parseCookies(cookieHeader) {
	const cookies = Object.create(null);
	if (typeof cookieHeader !== 'string' || cookieHeader.length === 0) {
		return cookies;
	}

	for (const part of cookieHeader.split(';')) {
		const cookie = part.trim();
		if (cookie.length === 0) {
			continue;
		}

		const separatorIndex = cookie.indexOf('=');
		if (separatorIndex < 0) {
			cookies[cookie] = cookies[cookie] || [];
			cookies[cookie].push('');
			continue;
		}

		if (separatorIndex === 0) {
			continue;
		}

		const key = cookie.slice(0, separatorIndex).trim();
		const value = cookie.slice(separatorIndex + 1).trim();
		if (key.length === 0) {
			continue;
		}

		cookies[key] = cookies[key] || [];
		cookies[key].push(value);
	}

	return cookies;
}

const wss = new WebSocketServer({
	host: '127.0.0.1',
	maxPayload: 65536,
	port: Number.parseInt(config.WEB_TERMINAL_PORT, 10),
	verifyClient: (info, cb) => {
		const cookies = parseCookies(info.req.headers.cookie);
		const sessionIDs = cookies[sessionName] || [];
		if (sessionIDs.length !== 1 || !/^[A-Za-z0-9,-]{1,128}$/.test(sessionIDs[0])) {
			cb(false, 401, 'Unauthorized');
			return;
		}

		const origin = info.origin || info.req.headers.origin;
		if (wss.clients.size >= 32) { cb(false, 503, 'Terminal capacity reached'); return; }
		let matches = origin === `https://${hostname}:${config.BACKEND_PORT}`;

		if (!matches) {
			for (const ip of Object.keys(systemIPs)) {
				if (origin === `https://${ip}:${config.BACKEND_PORT}`) {
					matches = true;
					break;
				}
			}
		}

		if (matches) {
			cb(true);
			return;
		}
		cb(false, 403, 'Forbidden');
	},
});

wss.on('connection', (ws, req) => {
	wss.clients.add(ws);
	ws.on('error', () => { console.error('Terminal transport failed'); ws.terminate(); });

	const remoteIP = req.headers['x-real-ip'] || req.socket.remoteAddress;

	// Check if session is valid
	const cookies = parseCookies(req.headers.cookie);
	const sessionIDs = cookies[sessionName] || [];
	if (sessionIDs.length !== 1 || sessionIDs[0].length === 0) {
		console.error(`Missing ${sessionName} cookie from ${remoteIP}, refusing connection`);
		ws.close(1000, 'You are not authenticated.');
		return;
	}
	const sessionID = sessionIDs[0];
	console.log('New terminal connection');

	let authResult;
	const authenticate = () => JSON.parse(execFileSync(
		`${process.env.HESTIA}/php/bin/php`,
		[`${process.env.HESTIA}/web-terminal/web-terminal-session-auth.php`],
		{ encoding: 'utf8', input: JSON.stringify({session_id: sessionID, remote_ip: remoteIP}),
			timeout: 2000, maxBuffer: 32768, stdio: ['pipe', 'pipe', 'ignore'] },
	));
	try {
		authResult = authenticate();
	} catch {
		console.error('Terminal session verification failed');
		ws.close(1000, 'Your session has expired.');
		return;
	}

	if (!authResult?.ok || typeof authResult.user !== 'string' || authResult.user.length === 0) {
		console.error('Unauthenticated terminal connection');
		ws.close(1000, 'You are not authenticated.');
		return;
	}
	const login = authResult.user;
	const impersonating = typeof authResult.look === 'string' ? authResult.look : '';
	const username = impersonating.length > 0 ? impersonating : login;

	// Get user info
	const passwd = readFileSync('/etc/passwd').toString();
	const userline = passwd.split('\n').find((line) => line.startsWith(`${username}:`));
	if (!userline) {
		console.error(`User ${username} not found, refusing connection`);
		ws.close(1000, 'You are not allowed to access this server.');
		return;
	}
	const [, , uid, gid, , homedir, shell] = userline.split(':');

	if (!Number.isSafeInteger(Number(uid)) || Number(uid) < 1000 || !Number.isSafeInteger(Number(gid)) || Number(gid) < 1 ||
		!shell.startsWith('/') || shell.endsWith('nologin') || shell.endsWith('/false')) {
		console.error(`User ${username} has no shell, refusing connection`);
		ws.close(1000, 'You have no shell access.');
		return;
	}

	// Spawn shell as logged in user
	let pty;
	try { pty = spawn(shell, [], {
		name: 'xterm-color',
		uid: Number.parseInt(uid, 10),
		gid: Number.parseInt(gid, 10),
		cwd: homedir,
		env: {
			SHELL: shell,
			TERM: 'xterm-color',
			USER: username,
			HOME: homedir,
			PWD: homedir,
			HESTIA: process.env.HESTIA,
		},
	}); } catch {
		console.error('Terminal process creation failed'); ws.close(1000, 'Terminal unavailable.'); return;
	}
	console.log(`New pty (${pty.pid}): ${shell} as ${username} (${uid}:${gid}) in ${homedir}`);

	// Send/receive data from websocket/pty
	pty.on('data', (data) => {
		if (ws.bufferedAmount > 1048576) { ws.close(1013, 'Terminal output limit reached.'); return; }
		if (ws.readyState === 1) ws.send(data);
	});
	ws.on('message', (data) => {
		try { pty.write(data); } catch { ws.close(1000, 'Terminal unavailable.'); }
	});
	const sessionTimer = setInterval(() => {
		try {
			const current = authenticate();
			if (!current?.ok || current.user !== login || (current.look || '') !== impersonating) ws.close(1000, 'Your session has expired.');
		} catch { ws.close(1000, 'Your session has expired.'); }
	}, 30000);

	// Ensure pty is killed when websocket is closed and vice versa
	pty.on('exit', () => {
		console.log(`Ended pty (${pty.pid})`);
		if (ws.readyState === 1) {
			ws.close();
		}
	});
	ws.on('close', () => {
		console.log('Ended terminal connection');
		clearInterval(sessionTimer);
		try { pty.kill(); } catch { console.error('Terminal process cleanup failed'); }
		wss.clients.delete(ws);
	});
});
