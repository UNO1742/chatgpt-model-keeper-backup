# Third-party components

The desktop shell dynamically uses PySide6 / Qt 6.12 and Qt WebEngine, including
Chromium. These components retain their respective licenses. Qt for Python is
available under LGPLv3/GPLv3/commercial terms; see
https://doc.qt.io/qtforpython-6/licenses.html and the installed PySide6 package.
Qt / PySide6 source: https://code.qt.io/pyside/pyside-setup.git/ and
https://code.qt.io/qt/qtwebengine.git/ . The application does not prevent users
from replacing the dynamically loaded Qt libraries with compatible builds.
Chromium licensing: https://www.chromium.org/chromium-os/licensing/ .

The Horizon orb renderer, watercolor texture, original ChatGPT UI stylesheet
OpenAI Sans fonts, original PowerSlider component and its original runtime
dependency bundles are **not** part of this
repository or release payload and are **not** covered by this project's MIT
license. At first use, the application retrieves the public resources identified
in `runtime_manifest.json` directly from their original ChatGPT CDN, verifies
their pinned SHA-256 digests and caches them locally. No OpenAI authentication,
cookies or conversation content are used. Availability and rights in these
resources remain with their respective owner. This project is not affiliated
with OpenAI.

The power slider executes the original component function and its original
React/Radix/Motion dependencies. A narrowly scoped export shim exposes its
entry point without rewriting the component body. It evaluates only the
generic dependency closure needed for the independent slider; it does not
start the authenticated ChatGPT app or account/business modules. Desktop
placement, blue accent variables, allowed option data, accessibility bindings
and local preset events are supplied by this project.

The Edge extension manifest contains a public key solely to keep its identifier
stable. No signing private key ships with the repository or the installer: the
key used for one-click deployment is generated locally on each machine (see
Extension packaging below). No account credential is included.

## Extension packaging

`extension_deploy.py` writes the CRX3 container described by Chromium's
`crx_file` format (magic `Cr24`, version 3, protobuf `CrxFileHeader` with
`sha256_with_rsa`) and signs it with an RSA-2048 key minted per machine on first
deployment. The key pair stays in the local install directory; only the public
half reaches the extension manifest. Packaging is written in-tree with the
standard library, so the frozen build carries no extra crypto stack. The PyPI
package `crx3` (MIT) implements the same format if a reference is needed.
