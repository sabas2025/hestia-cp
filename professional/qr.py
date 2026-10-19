#!/usr/bin/env python3
"""Offline QR renderer. Secret URI is read only from stdin and never logged."""
import io
import sys

def main():
    import qrcode
    from qrcode.image.svg import SvgPathImage
    value = sys.stdin.read(4097)
    if len(value) > 4096 or not value.startswith('otpauth://totp/') or '\n' in value or '\x00' in value:
        return 1
    qr = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(value); qr.make(fit=True)
    output = io.BytesIO(); qr.make_image(image_factory=SvgPathImage).save(output)
    sys.stdout.buffer.write(output.getvalue()); return 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        print('Offline QR renderer unavailable; install python3-qrcode from the OS repository.', file=sys.stderr); sys.exit(1)
