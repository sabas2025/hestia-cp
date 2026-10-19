# Browser QA

The release suite requires PHP, system Python with `qrcode`, ShellCheck, Node.js,
the exact Composer-locked TOTP library, Playwright and Chromium.

Run `npm ci --ignore-scripts` in this directory, install the Playwright browser,
and supply `PLAYWRIGHT_MODULE` and `CHROME_BIN` to `run_checks.py`.

The suite generates both previews from the current PHP templates. The previews
contain illustrative data and do not connect to a VPS or enable authentication.
