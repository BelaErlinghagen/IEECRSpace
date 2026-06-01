"""RSpace API client and helpers.

This module is designed to be reused on its own, independently of the bundled GUI.
The core is the :class:`RSpaceClient` class, which holds a connection (API key +
server URL) and exposes the RSpace operations as plain methods — no hidden global
state, so you can create as many clients as you like and test them easily:

    from rspace import RSpaceClient

    client = RSpaceClient(api_key="abc123", url="https://rspace.example.org")
    ok, msg = client.check_connection()
    for doc in client.list_documents(folder_id=12345):
        print(doc["name"])
    client.create_document(folder_id=12345, name="OPI111_20260601_1200_test",
                           tags=["id_OPI111", "m_mea"], content="hello")
    client.project_overview(folder_id=12345, output_dir="~/Desktop")

Stateless helpers (no network) are module-level functions and can be used directly:
``strip_tag_prefix``, ``current_date_time``, ``parse_entry_name``,
``summarize_documents`` / ``create_summary_csv``, ``filepaths_for_rows`` /
``generate_filepaths``, ``build_renamed_name`` and ``rename_and_organize_files``.

For applications that want to persist one set of credentials (as the bundled GUI
does), an optional convenience layer stores them in a per-user config file
(``load_credentials`` / ``save_credentials``) and offers module-level functions
(``get_tags``, ``list_all_folders``, ``create_entry`` …) that operate through a
default client built from those saved credentials.
"""

import csv
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import requests

__all__ = [
    "DEFAULT_RSPACE_URL",
    "RSpaceClient",
    # stateless helpers
    "strip_tag_prefix", "current_date_time", "parse_entry_name",
    "ID_PREFIX", "METHOD_PREFIX", "SUMMARY_FIELDS",
    # local data processing (no network)
    "summarize_documents", "create_summary_csv",
    "filepaths_for_rows", "generate_filepaths",
    "build_renamed_name", "rename_and_organize_files",
    # stored-credentials convenience
    "load_credentials", "save_credentials", "has_credentials", "default_client",
    "check_connection", "test_credentials",
    "get_tags", "list_all_folders", "get_metadata_in_folder",
    "get_dates_for_tag", "get_times_for_tag_and_date", "project_overview",
    "create_entry", "create_entries",
]

DEFAULT_RSPACE_URL = "https://rspace.uni-bonn.de"

# Tags encode two kinds of IDs: subject IDs prefixed "id_" (e.g. "id_OPI111") and
# method IDs prefixed "m_" (e.g. "m_patch_clamp"). Any other tag is a plain
# data-state tag (e.g. "preprocessed"), not an ID.
ID_PREFIX = "id_"
METHOD_PREFIX = "m_"

# Entries are named "YYYYMMDD_HHMM_ExtraInfo".
ENTRY_NAME_RE = re.compile(r"^(\d{8})_(\d{4})_(.+)$")

# Column order of the summary CSV produced by create_summary_csv / summarize_documents.
SUMMARY_FIELDS = ["mouseID", "date", "time", "experimenter_name", "method", "tags", "extra"]


# ── Stateless helpers ────────────────────────────────────────────────────────────

def strip_tag_prefix(tag):
    """Return `tag` without a leading "id_" or "m_" ID prefix (unchanged otherwise)."""
    for prefix in (ID_PREFIX, METHOD_PREFIX):
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return tag


def current_date_time():
    """Return the current local (date, time) as (YYYYMMDD, HHMM) strings."""
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%H%M")


def parse_entry_name(name):
    """Split an entry name "YYYYMMDD_HHMM_Extra" into (date, time, extra).

    If the name doesn't match that pattern, returns ("", "", name).
    """
    match = ENTRY_NAME_RE.match(name or "")
    return match.groups() if match else ("", "", name or "")


def _split_tags(tag_string):
    """Split an RSpace comma-separated tag string into a clean list."""
    return [t.strip() for t in (tag_string or "").split(",") if t.strip()]


def _ensure_dir(output_dir):
    """Create `output_dir` (and parents) if needed and return it as a Path."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── Local data processing (no network) ────────────────────────────────────────────

def summarize_documents(docs):
    """Turn a list of RSpace document dicts into summary rows.

    One row per subject ("id_") tag found on a document. The ``mouseID`` and
    ``method`` values have their prefixes stripped (they are used for naming),
    while ``tags`` keeps the raw tag list. Each row is a dict keyed by
    :data:`SUMMARY_FIELDS`.
    """
    rows = []
    for doc in docs:
        date, time, extra = parse_entry_name(doc.get("name", ""))

        owner = doc.get("owner") or {}
        first = (owner.get("firstName") or "").lower()
        last = (owner.get("lastName") or "").lower()
        experimenter = f"{first}_{last}"

        all_tags = _split_tags(doc.get("tags"))
        method = ";".join(strip_tag_prefix(t) for t in all_tags if t.startswith(METHOD_PREFIX))
        tags = ";".join(all_tags)

        for tag in all_tags:
            if tag.startswith(ID_PREFIX):
                rows.append({
                    "mouseID": strip_tag_prefix(tag),
                    "date": date,
                    "time": time,
                    "experimenter_name": experimenter,
                    "method": method,
                    "tags": tags,
                    "extra": extra,
                })
    return rows


def create_summary_csv(metadata_file, output_dir):
    """Read a metadata JSON file, summarise it (see :func:`summarize_documents`) and
    write a ``summary_<stem>.csv`` into output_dir. Returns the CSV path."""
    meta_path = Path(metadata_file)
    with open(meta_path) as f:
        docs = json.load(f)
    rows = summarize_documents(docs)

    out = _ensure_dir(output_dir) / f"summary_{meta_path.stem}.csv"
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return str(out)


def filepaths_for_rows(rows):
    """Build organised file paths from summary rows (dicts shaped like
    :func:`summarize_documents` output).

    Returns a list of (mouseID, "method/experimenter/mouseID_date_time_extra") pairs;
    the method falls back to "unknown_method" when absent.
    """
    pairs = []
    for row in rows:
        method = next((m for m in (row.get("method") or "").split(";") if m), "unknown_method")
        experimenter = row.get("experimenter_name", "")
        mouse_id = row.get("mouseID", "")
        parts = [mouse_id] + [p for p in (row.get("date", ""), row.get("time", ""),
                                          row.get("extra", "")) if p]
        pairs.append((mouse_id, f"{method}/{experimenter}/{'_'.join(parts)}"))
    return pairs


def generate_filepaths(summary_csv, output_dir):
    """Read a summary CSV, build organised file paths (see :func:`filepaths_for_rows`)
    and write them to ``filepaths_<stem>.csv`` (columns: mouseID, filepath) in
    output_dir. Returns the written CSV path."""
    with open(summary_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    pairs = filepaths_for_rows(rows)

    out = _ensure_dir(output_dir) / f"filepaths_{Path(summary_csv).stem}.csv"
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mouseID", "filepath"])
        writer.writerows(pairs)
    return str(out)


def build_renamed_name(original_name, prefix, strip_front=0, strip_back=0):
    """Return the new file name for `original_name` given `prefix`.

    `strip_front` characters are removed from the start of the original name and
    `strip_back` characters from its end (the file extension is always kept);
    both can be applied at once. `prefix` is then prepended. For example,
    build_renamed_name("20260101_1200_rec.tif", "OPI111", strip_front=14)
    returns "OPI111_rec.tif".
    """
    p = Path(original_name)
    suffix = p.suffix
    stem = original_name[: -len(suffix)] if suffix else original_name
    if strip_front > 0:
        stem = stem[strip_front:]
    if strip_back > 0:
        stem = stem[:-strip_back]
    remainder = f"{stem}{suffix}"
    if prefix and remainder:
        return f"{prefix}_{remainder}"
    return prefix or remainder


def rename_and_organize_files(files, prefix, dest_folder=None, raw_data_folder=None,
                              strip_front=0, strip_back=0):
    """Rename files with `prefix_` and optionally move/copy them.

    Steps (in order):
      1. Rename each file in place to `{prefix}_{original_name}`, after erasing
         `strip_front` characters from the start and `strip_back` characters from
         the end of the original name (see :func:`build_renamed_name`).
      2. If dest_folder given: create it and move renamed files there.
      3. If raw_data_folder given: copy files (from their post-step-2 location) there.

    Returns a list of final Path objects.
    """
    final_paths = []
    for f in files:
        f = Path(f)
        renamed = f.parent / build_renamed_name(f.name, prefix, strip_front, strip_back)
        f.rename(renamed)
        current = renamed

        if dest_folder is not None:
            dest = Path(dest_folder)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), dest / current.name)
            current = dest / current.name

        if raw_data_folder is not None:
            rd = Path(raw_data_folder)
            rd.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(current), rd / current.name)

        final_paths.append(current)
    return final_paths


def _field_value(field):
    """Return an RSpace field's content as flat plain text.

    `string`/`date` fields hold plain text already; `text` fields hold HTML. Block
    tags become spaces, remaining tags are stripped, entities are unescaped, and
    whitespace is collapsed so multi-line fields fit in a single CSV cell.
    """
    content = field.get("content") or ""
    content = re.sub(r"</(p|div|tr|li|h[1-6])>|<br\s*/?>", " ", content, flags=re.I)
    content = re.sub(r"<[^>]+>", "", content)
    content = html.unescape(content)
    return " ".join(content.split())


# ── RSpace API client ──────────────────────────────────────────────────────────────

class RSpaceClient:
    """A connection to an RSpace server.

    Holds the API key and server URL and performs all network operations. Create
    one with explicit credentials::

        client = RSpaceClient("my-api-key", "https://rspace.example.org")

    Methods that talk to the server raise ``requests`` exceptions on failure, except
    :meth:`check_connection`, which returns a (ok, message) tuple instead.
    """

    def __init__(self, api_key, url=DEFAULT_RSPACE_URL, *, timeout=30, session=None):
        self.api_key = (api_key or "").strip()
        self.url = (url or DEFAULT_RSPACE_URL).rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._folder_parent_cache = {}

    # -- low-level request helpers --

    @property
    def base_url(self):
        return f"{self.url}/api/v1"

    @property
    def _headers(self):
        return {"apiKey": self.api_key, "Accept": "application/json"}

    def _get(self, path, params=None):
        resp = self._session.get(f"{self.base_url}/{path}", headers=self._headers,
                                 params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, body):
        resp = self._session.post(f"{self.base_url}/{path}", headers=self._headers,
                                  json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # -- connection --

    def check_connection(self):
        """Return (True, "<url> (<n> documents)") if reachable and authorised, else
        (False, friendly_error_message)."""
        if not self.api_key:
            return False, "No API key entered."
        try:
            data = self._get("documents", {"pageSize": 1})
            return True, f"{self.url}  ({data.get('totalHits', '?')} documents)"
        except requests.exceptions.SSLError:
            return False, ("Secure (SSL/TLS) connection failed. This usually means the "
                           "Python running the app is too old — reinstall using the "
                           "provided installer, which sets up a modern Python.")
        except requests.exceptions.HTTPError as exc:
            code = getattr(exc.response, "status_code", None)
            if code == 401:
                return False, ("API key was rejected (HTTP 401). Check that you pasted "
                               "the complete, current key.")
            return False, f"Server returned HTTP {code}." if code else str(exc)
        except requests.exceptions.ConnectionError:
            return False, (f"Could not reach {self.url}. Check the server URL and your "
                           "internet connection.")
        except requests.exceptions.Timeout:
            return False, f"Connection to {self.url} timed out. Please try again."
        except Exception as exc:
            return False, str(exc)

    # -- documents --

    def list_documents(self, folder_id=None):
        """Return all document summaries, optionally restricted to a folder subtree.

        Note: these summaries do NOT include field content — use :meth:`get_document`
        for a single document's fields.
        """
        params = {"pageSize": 100, "pageNumber": 0}
        docs = []
        while True:
            data = self._get("documents", params)
            docs.extend(data.get("documents", []))
            if len(docs) >= data.get("totalHits", 0):
                break
            params["pageNumber"] += 1

        if folder_id is None:
            return docs
        return [d for d in docs if self._is_in_subtree(d.get("parentFolderId"), folder_id)]

    def get_document(self, doc_id):
        """Return a single full document (including its ``fields``)."""
        return self._get(f"documents/{doc_id}")

    def create_document(self, folder_id, name, tags, content):
        """Create a document in folder_id and return the API response dict.

        `tags` may be a list/tuple or a comma-separated string.
        """
        if isinstance(tags, (list, tuple)):
            tags = ",".join(tags)
        body = {
            "name": name,
            "tags": tags,
            "parentFolderId": folder_id,
            "fields": [{"content": content}],
        }
        return self._post("documents", body)

    def create_documents(self, folder_id, items, content):
        """Create several documents; `items` is a list of (name, tags) pairs (e.g. one
        per subject). Returns a list of response dicts."""
        return [self.create_document(folder_id, name, tags, content) for name, tags in items]

    # -- tags & folders --

    def list_tags(self, folder_id=None):
        """Return the sorted unique tags applied to documents (optionally folder-scoped)."""
        tags = set()
        for doc in self.list_documents(folder_id):
            tags.update(_split_tags(doc.get("tags")))
        return sorted(tags)

    def dates_for_tag(self, tag):
        """Return sorted unique dates (YYYYMMDD) from the names of documents tagged `tag`."""
        dates = set()
        for doc in self.list_documents():
            if tag in _split_tags(doc.get("tags")):
                date, _, _ = parse_entry_name(doc.get("name", ""))
                if date:
                    dates.add(date)
        return sorted(dates)

    def times_for_tag_and_date(self, tag, date):
        """Return sorted unique times (HHMM) from documents tagged `tag` whose name date is `date`."""
        times = set()
        for doc in self.list_documents():
            if tag in _split_tags(doc.get("tags")):
                d, t, _ = parse_entry_name(doc.get("name", ""))
                if d == date and t:
                    times.add(t)
        return sorted(times)

    def _folder_parent(self, folder_id):
        if folder_id not in self._folder_parent_cache:
            try:
                self._folder_parent_cache[folder_id] = self._get(f"folders/{folder_id}").get("parentFolderId")
            except Exception:
                self._folder_parent_cache[folder_id] = None
        return self._folder_parent_cache[folder_id]

    def _is_in_subtree(self, candidate_folder_id, target_folder_id):
        visited = set()
        current = candidate_folder_id
        while current is not None and current not in visited:
            if current == target_folder_id:
                return True
            visited.add(current)
            current = self._folder_parent(current)
        return False

    def list_folders(self):
        """Return accessible folders/notebooks as {id, name, label, notebook, parentId} dicts."""
        root = self._get("folders/tree")
        top_ids = {r["id"] for r in root.get("records", [])}
        all_docs = self.list_documents()
        parent_ids = {d["parentFolderId"] for d in all_docs if d.get("parentFolderId")} | top_ids

        folder_info = {}
        for fid in parent_ids:
            try:
                folder_info[fid] = self._get(f"folders/{fid}")
            except Exception:
                pass
        for info in list(folder_info.values()):
            pid = info.get("parentFolderId")
            if pid and pid not in folder_info:
                try:
                    folder_info[pid] = self._get(f"folders/{pid}")
                except Exception:
                    pass

        result = []
        for fid, info in folder_info.items():
            pid = info.get("parentFolderId")
            parent_name = folder_info.get(pid, {}).get("name", "") if pid else ""
            label = f"{parent_name} > {info['name']}" if parent_name else info["name"]
            result.append({
                "id": fid,
                "name": info["name"],
                "label": label,
                "notebook": bool(info.get("notebook")),
                "parentId": pid,
            })
        return sorted(result, key=lambda x: x["label"])

    # -- reports (fetch + write) --

    def fetch_metadata(self, folder_id, output_dir):
        """Save all documents in folder_id as ``metadata_<id>.json`` in output_dir;
        return the file path."""
        docs = self.list_documents(folder_id)
        out = _ensure_dir(output_dir) / f"metadata_{folder_id}.json"
        with open(out, "w") as f:
            json.dump(docs, f, indent=2)
        return str(out)

    def overview(self, folder_id):
        """Collect a per-document × per-field overview of a folder.

        Returns (columns, rows) where ``columns`` is the union of field names (in
        first-seen order) and ``rows`` is a list of (document_name, {field: value}).
        """
        columns, seen, rows = [], set(), []
        for doc in self.list_documents(folder_id):
            full = self.get_document(doc["id"])
            fields = sorted(full.get("fields", []) or [], key=lambda f: f.get("columnIndex", 0))
            record = {}
            for field in fields:
                name = field.get("name") or "Field"
                value = _field_value(field)
                if name in record:
                    if value:
                        record[name] = f"{record[name]}; {value}"
                else:
                    record[name] = value
                if name not in seen:
                    seen.add(name)
                    columns.append(name)
            rows.append((doc.get("name", ""), record))
        return columns, rows

    def project_overview(self, folder_id, output_dir):
        """Write an overview CSV (see :meth:`overview`) for a folder into output_dir;
        return the CSV path. One row per document; first column is the document name."""
        columns, rows = self.overview(folder_id)
        out = _ensure_dir(output_dir) / f"overview_{folder_id}.csv"
        with open(out, "w", newline="") as f:
            writer = csv.writer(f)
            # "Document Name" rather than "Name" so it never collides with a form
            # field that happens to be named "Name".
            writer.writerow(["Document Name"] + columns)
            for name, record in rows:
                writer.writerow([name] + [record.get(c, "") for c in columns])
        return str(out)


# ── Stored-credentials convenience layer (optional) ─────────────────────────────────
# Persists a single set of credentials in a per-user config file and exposes
# module-level functions that operate through a default client built from them.
# Applications that don't want this can ignore it and use RSpaceClient directly.

def _config_dir():
    """Return the per-user config directory for stored credentials."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "RSpaceInterface"


def _config_file():
    return _config_dir() / "config.json"


def _find_apikey_file():
    """Locate a legacy APIkey.txt next to the script or in the cwd, or None."""
    for candidate in (Path(__file__).parent / "APIkey.txt", Path.cwd() / "APIkey.txt"):
        if candidate.exists():
            return candidate
    return None


def _read_legacy_apikey():
    """Read a legacy two-line APIkey.txt (key + URL, any order). Returns (key, url) or None."""
    legacy = _find_apikey_file()
    if not legacy:
        return None
    lines = [l.strip() for l in legacy.read_text().splitlines() if l.strip()]
    if not lines:
        return None
    if lines[0].startswith("http"):
        url = lines[0].rstrip("/")
        key = lines[1] if len(lines) > 1 else ""
    else:
        key = lines[0]
        url = lines[1].rstrip("/") if len(lines) > 1 else DEFAULT_RSPACE_URL
    return key, url


_credentials = None      # cached (api_key, url)
_default_client = None    # cached RSpaceClient built from the saved credentials


def load_credentials():
    """Return the saved (api_key, url), loading from config.json (or migrating a legacy
    APIkey.txt) on first use. Cached in module state."""
    global _credentials
    if _credentials is not None:
        return _credentials

    cfg = _config_file()
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
            _credentials = (data.get("api_key", ""), data.get("url") or DEFAULT_RSPACE_URL)
            return _credentials
        except Exception:
            pass  # fall through to migration / defaults

    migrated = _read_legacy_apikey()
    if migrated:
        save_credentials(migrated[0], migrated[1])  # persist to the new location
        return _credentials

    _credentials = ("", DEFAULT_RSPACE_URL)
    return _credentials


def save_credentials(api_key, url):
    """Persist credentials to the user config file and refresh the default client."""
    global _credentials, _default_client
    url = (url or DEFAULT_RSPACE_URL).rstrip("/")
    api_key = (api_key or "").strip()
    _ensure_dir(_config_dir())
    _config_file().write_text(json.dumps({"api_key": api_key, "url": url}, indent=2))
    _credentials = (api_key, url)
    _default_client = None  # rebuilt lazily with the new credentials
    return _credentials


def has_credentials():
    """True if an API key has been configured."""
    return bool(load_credentials()[0])


def default_client():
    """Return a shared RSpaceClient built from the saved credentials (cached)."""
    global _default_client
    if _default_client is None:
        _default_client = RSpaceClient(*load_credentials())
    return _default_client


# Module-level convenience functions — thin wrappers around the default client.

def check_connection():
    return default_client().check_connection()


def test_credentials(api_key, url):
    """Validate the given credentials without saving them. Returns (ok, message)."""
    return RSpaceClient(api_key, url).check_connection()


def get_tags(project_folder=None):
    return default_client().list_tags(project_folder)


def list_all_folders():
    return default_client().list_folders()


def get_metadata_in_folder(folder_id, output_dir):
    return default_client().fetch_metadata(folder_id, output_dir)


def get_dates_for_tag(tag):
    return default_client().dates_for_tag(tag)


def get_times_for_tag_and_date(tag, date):
    return default_client().times_for_tag_and_date(tag, date)


def project_overview(folder_id, output_dir):
    return default_client().project_overview(folder_id, output_dir)


def create_entry(project_folder, tags, name, content):
    return default_client().create_document(project_folder, name, tags, content)


def create_entries(project_folder, items, content):
    return default_client().create_documents(project_folder, items, content)
