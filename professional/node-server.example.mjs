// Minimal Node.js project: adapt the application; use a supported LTS runtime.
import http from 'node:http';
const port = Number(process.env.PORT || 3100);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid application port');
const server = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.statusCode = request.url === '/health' ? 200 : 404;
  response.end(JSON.stringify(request.url === '/health' ? {status: 'ok'} : {error: 'not-found'}));
});
server.listen(port, '127.0.0.1');
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(() => process.exit(0)));
