// Serve repository-relative preview fonts/images instead of mocking them as HTML.
const fs = require('fs');
const path = require('path');
module.exports = async function previewAsset(route, root) {
  const pathname = new URL(route.request().url()).pathname;
  if (route.request().method() !== 'GET' || !/^\/web\/(webfonts|images)\//.test(pathname)) return false;
  const file = path.resolve(root, '.' + pathname);
  if (!file.startsWith(path.join(root, 'web') + path.sep) || !fs.existsSync(file)) {
    await route.fulfill({status: 404, body: ''}); return true;
  }
  const type = file.endsWith('.svg') ? 'image/svg+xml' : file.endsWith('.woff2') ? 'font/woff2' : 'font/woff';
  await route.fulfill({contentType: type, body: fs.readFileSync(file)});
  return true;
};
