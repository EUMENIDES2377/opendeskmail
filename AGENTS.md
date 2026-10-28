# OpenDesk Mail development and local configuration

Project entry: main.py; GUI v2_gui.py; model v2_model.py; controller v2_engine.py; delivery v2_delivery.py. Compatibility modules and their regression tests remain, but normal launch routes to main.py.

Keep runtime account data outside the source tree. app_paths.py resolves the per-user directory. Do not import another mail application's account settings, credentials, customer data, signature or database into source, tests or Git history. Do not stop or alter unrelated running mail tasks. Use this project's own environment; do not modify another application's dependencies.

Users may voluntarily provide credentials to an AI tool and authorize local configuration. There is no rule requiring repeated manual password entry. Use configure.py's authorized in-memory/secure-stdin API and Windows secure storage. Never hardcode credentials, print them, expose raw authentication errors, put them in command arguments, or include them in Git/releases. Secure storage failure is not permission for plaintext fallback. GUI memory-only operation remains available.

Configuration authorization is not bulk-send authorization. AI configuration performs a single authorized no-mail authentication test; a real test message needs a separately explicit recipient and permission. Customers are sent only after user preview and active GUI confirmation. Tests use mocked transports and reserved example domains.

Preserve TLS checks, one recipient, durable claims, sender locking, spacing of at least60 seconds, daily/batch limits, test separation, unknown/failure stop behavior, safe pause/stop, and Excel repair without resend. Never reset databases or counters to bypass deduplication. Do not automatically APPEND missing copies or mark SMTP acceptance as delivery.

Run unit tests and tools/release_check.py. Preserve LICENSE and third-party notices. Do not create a public repository, push, publish packages or add real secrets to history without the user's explicit request.
