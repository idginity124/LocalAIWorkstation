# Experimental Krita bridge

The bridge runs Krita on a private Xvfb display and exchanges file-based requests with the local API. The plugin executes Krita operations on the Qt main thread. It does not open a network port or connect to the user's existing Krita documents. Process separation is not a filesystem sandbox.

From the repository root, run `bash scripts/krita-deneme.sh` for an optional real-engine probe. It requires Krita, compatible Qt/Python bindings, Xvfb and xauth. Output is written under the ignored `runtime-reports/` directory.

The application integration and current limits are documented in [Krita integration](../../docs/KRITA_INTEGRATION.md). Source release checks do not run this GUI/GPU probe.
