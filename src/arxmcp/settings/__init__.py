"""Settings: everything a process needs to know before it does anything.

The bottom box. It owns

* the server configuration (:class:`Config`, every ``ARXMCP_*`` knob and
  its default);
* the application paths: where corpus, indexes, notebooks, caches, logs
  and backups live in a source checkout, an installed app or a container
  (:class:`ApplicationPaths`), and the notebook slug that names a
  notebook's directory (:data:`NOTEBOOK_SLUG_RE`);
* operator preferences persisted in ``notebooks.db``, such as the contact
  email and the MinerU binary, read only when asked
  (:func:`get_setting` and friends);
* the arXiv CA pin: the vendored bundle and the SSL context built from it
  (:func:`build_arxiv_ssl_context`).

Settings imports no other ``arxmcp`` box, and validating a :class:`Config`
reads no corpus state: whether a dataset has been ingested is checked by
whoever opens it. Other boxes import from this package root only.
"""

from arxmcp.settings.application_paths import (
    COMPATIBILITY_ALIAS_FIELDS,
    NOTEBOOK_SLUG_RE,
    ApplicationMode,
    ApplicationPathError,
    ApplicationPaths,
    derived_index_path,
    legacy_source_path,
)
from arxmcp.settings.config import (
    CONFIG_REFERENCE_HINT,
    DEFAULT_BIND_PORT,
    DEFAULT_FRESHNESS_INTERVAL_SECONDS,
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    DEFAULT_RESULT_BYTE_CAP,
    LOOPBACK_HOSTS,
    Config,
)
from arxmcp.settings.operator import (
    DEFAULT_DB_PATH,
    OperatorSettingsStore,
    delete_setting,
    get_contact_email,
    get_mineru_bin,
    get_setting,
    set_setting,
)
from arxmcp.settings.ssl_pin import (
    VENDORED_ARXIV_CA_BUNDLE,
    arxiv_ssl_context_from_env,
    build_arxiv_ssl_context,
    resolve_arxiv_ca_bundle,
)

__all__ = [
    "COMPATIBILITY_ALIAS_FIELDS",
    "CONFIG_REFERENCE_HINT",
    "DEFAULT_BIND_PORT",
    "DEFAULT_DB_PATH",
    "DEFAULT_FRESHNESS_INTERVAL_SECONDS",
    "DEFAULT_REFRESH_INTERVAL_SECONDS",
    "DEFAULT_RESULT_BYTE_CAP",
    "LOOPBACK_HOSTS",
    "NOTEBOOK_SLUG_RE",
    "VENDORED_ARXIV_CA_BUNDLE",
    "ApplicationMode",
    "ApplicationPathError",
    "ApplicationPaths",
    "Config",
    "OperatorSettingsStore",
    "arxiv_ssl_context_from_env",
    "build_arxiv_ssl_context",
    "delete_setting",
    "derived_index_path",
    "get_contact_email",
    "get_mineru_bin",
    "get_setting",
    "legacy_source_path",
    "resolve_arxiv_ca_bundle",
    "set_setting",
]
