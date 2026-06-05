# `rspace` — API reference

Reference documentation for the RSpace backend module, [`src/rspace.py`](../src/rspace.py).

This is the manual; the runnable tour lives next to it in
[`examples.py`](examples.py). Every public name is documented below in
[numpydoc](https://numpydoc.readthedocs.io/) style (Parameters / Returns /
Raises / Notes / Examples).

The module has five layers, each usable on its own:

| Layer | What it is | Needs network? |
|-------|------------|----------------|
| [`RSpaceClient`](#rspaceclient) | A connection object; all server operations are its methods. | yes |
| [Stateless helpers](#stateless-helpers) | Pure string/date helpers the rest is built on. | no |
| [Local data processing](#local-data-processing) | Summaries, CSVs, file-path generation, renaming. | no |
| [Drafts / autosave](#drafts--autosave) | Persist in-progress entries as JSON. | no |
| [Stored-credentials convenience](#stored-credentials-convenience-layer) | Save one set of credentials and call module-level wrappers. | yes |

---

## Contents

- [Quick start](#quick-start)
- [Conventions](#conventions)
- [`RSpaceClient`](#rspaceclient)
  - [`RSpaceClient(...)`](#rspaceclientapi_key-urldefault_rspace_url--timeout30-sessionnone)
  - [`base_url`](#base_url)
  - [`check_connection`](#check_connection)
  - [`list_documents`](#list_documentsfolder_idnone)
  - [`get_document`](#get_documentdoc_id)
  - [`create_document`](#create_documentfolder_id-name-tags-content)
  - [`create_documents`](#create_documentsfolder_id-items-content)
  - [`list_tags`](#list_tagsfolder_idnone)
  - [`dates_for_tag`](#dates_for_tagtag)
  - [`times_for_tag_and_date`](#times_for_tag_and_datetag-date)
  - [`list_folders`](#list_folders)
  - [`create_tree`](#create_treefolder_idnone-exclude_top-max_workers8)
  - [`fetch_metadata`](#fetch_metadatafolder_id-output_dir)
  - [`overview`](#overviewfolder_id)
  - [`documents_in_folder`](#documents_in_folderfolder_id)
  - [`project_overview`](#project_overviewfolder_id-output_dir)
- [Stateless helpers](#stateless-helpers)
- [Local data processing](#local-data-processing)
- [Drafts / autosave](#drafts--autosave)
- [Stored-credentials convenience layer](#stored-credentials-convenience-layer)
- [Module constants](#module-constants)

---

## Quick start

```python
from rspace import RSpaceClient

client = RSpaceClient(api_key="your-key", url="https://rspace.uni-bonn.de")

ok, message = client.check_connection()
folders = client.list_folders()
tree    = client.create_tree()                       # full nested folder/notebook tree

client.create_document(
    folder_id=12345,
    name="20260601_1200_baseline",
    tags=["id_OPI111", "m_mea"],
    content="Notes…",
)
client.project_overview(folder_id=12345, output_dir="~/Desktop")
```

> **Importing the module.** `rspace.py` lives in [`src/`](../src/). Either run
> from inside `src/`, or add it to the import path first:
>
> ```python
> import sys
> from pathlib import Path
> sys.path.insert(0, str(Path("src").resolve()))
> import rspace
> ```
>
> (This is exactly what [`examples.py`](examples.py) does at the top.)

---

## Conventions

Several functions read meaning out of **tags** and **entry names**:

- **Subject IDs** start with `id_` (e.g. `id_OPI111`).
- **Method IDs** start with `m_` (e.g. `m_patch_clamp`).
- `preprocessed` / `results` mark a document's *data state* and route its
  generated file path into `processed_data/…`.
- Any other tag is treated as a plain data-state tag.
- When an ID is used to build a *name*, its prefix is dropped
  (`id_OPI111` → `OPI111`) — see [`strip_tag_prefix`](#strip_tag_prefixtag).
- **Entry names** follow the pattern `YYYYMMDD_HHMM_ExtraInfo`, which
  [`parse_entry_name`](#parse_entry_namename) splits back apart.

Tags may be passed to write methods as either a Python list/tuple
(`["id_OPI111", "m_mea"]`) or a comma-separated string (`"id_OPI111,m_mea"`).

---

# `RSpaceClient`

```python
class RSpaceClient(api_key, url=DEFAULT_RSPACE_URL, *, timeout=30, session=None)
```

A connection to an RSpace server. It holds the API key and server URL and
performs all network operations. There is **no global state**, so you can create
as many clients as you like and test them in isolation.

Methods that talk to the server raise [`requests`](https://requests.readthedocs.io/)
exceptions on failure — *except* [`check_connection`](#check_connection), which
returns an `(ok, message)` tuple instead.

### `RSpaceClient(api_key, url=DEFAULT_RSPACE_URL, *, timeout=30, session=None)`

Construct a client.

**Parameters**

- **api_key** : `str`
  Your RSpace API key (RSpace → *My RSpace → My Profile → API Key*). Surrounding
  whitespace is stripped.
- **url** : `str`, optional
  Base server URL. Defaults to [`DEFAULT_RSPACE_URL`](#module-constants)
  (`"https://rspace.uni-bonn.de"`). A trailing `/` is removed.
- **timeout** : `int`, keyword-only, optional
  Per-request timeout in seconds (default `30`).
- **session** : `requests.Session`, keyword-only, optional
  A pre-configured session to reuse (e.g. for connection pooling or to inject a
  mock in tests). A new `requests.Session()` is created if omitted.

**Examples**

```python
client = RSpaceClient("abc123", "https://rspace.example.org")
client = RSpaceClient("abc123", timeout=10)          # shorter timeout
```

---

### `base_url`

*property* → `str`

The REST root the client posts to: `"{url}/api/v1"`.

```python
>>> RSpaceClient("k", "https://rspace.example.org").base_url
'https://rspace.example.org/api/v1'
```

---

### `check_connection()`

Test reachability and authorisation **without raising**.

**Returns**

- `tuple` of (`bool`, `str`)
  `(True, "<url> (<n> documents)")` if the server is reachable and the key is
  accepted; otherwise `(False, friendly_error_message)`.

**Notes**

Unlike every other network method, this one catches exceptions and converts them
to friendly messages — ideal for a "Test connection" button. It distinguishes
SSL failures, HTTP 401 (bad key), connection errors and timeouts.

**Examples**

```python
ok, message = client.check_connection()
if not ok:
    print("Could not connect:", message)
```

---

### `list_documents(folder_id=None)`

List document **summaries**, optionally restricted to a folder subtree.

**Parameters**

- **folder_id** : `int`, optional
  If given, only documents whose location lies within this folder's subtree are
  returned (resolved by walking each document's parent chain). If `None`
  (default), all visible documents are returned.

**Returns**

- `list` of `dict`
  Document summaries — `name`, `tags`, `owner`, `parentFolderId`, `id`, etc.

**Notes**

Summaries do **not** include field content. Use [`get_document`](#get_documentdoc_id)
for a single document's fields. Results are fetched page by page (100 per page)
until all `totalHits` are collected.

**Examples**

```python
all_docs    = client.list_documents()
folder_docs = client.list_documents(folder_id=12345)
```

---

### `get_document(doc_id)`

Fetch one complete document, **including its fields**.

**Parameters**

- **doc_id** : `int`
  The document's RSpace id.

**Returns**

- `dict`
  The full document. The `fields` key holds the form fields; `string`/`date`
  fields contain plain text, `text` fields contain HTML.

**Raises**

- `requests.exceptions.HTTPError`
  If the document does not exist or is not accessible.

**Examples**

```python
full = client.get_document(987654)
for field in full["fields"]:
    print(field["name"], "→", field["content"])
```

---

### `create_document(folder_id, name, tags, content)`

Create a single document (entry) in a folder.

**Parameters**

- **folder_id** : `int`
  The destination folder/notebook id.
- **name** : `str`
  The entry name. By convention `YYYYMMDD_HHMM_ExtraInfo`
  (see [Conventions](#conventions)).
- **tags** : `list`, `tuple`, or `str`
  Tags to apply. A list/tuple is joined with commas; a comma-separated string is
  passed through unchanged.
- **content** : `str`
  The body of the entry's single field. May contain HTML.

**Returns**

- `dict`
  The created document as returned by the API (includes its new `id`).

**Raises**

- `requests.exceptions.HTTPError`
  On a rejected request (e.g. bad folder id or key).

**See also**

[`create_documents`](#create_documentsfolder_id-items-content) — create several
at once. [`current_date_time`](#current_date_time) — build the date/time name
prefix.

**Examples**

```python
date, time = rspace.current_date_time()
resp = client.create_document(
    folder_id=12345,
    name=f"{date}_{time}_baseline",
    tags=["id_OPI111", "m_mea"],
    content="Recording went well.",
)
print("New id:", resp["id"])
```

---

### `create_documents(folder_id, items, content)`

Create several documents that share a body — one per `(name, tags)` pair.

**Parameters**

- **folder_id** : `int`
  The destination folder/notebook id.
- **items** : `list` of `tuple`
  A list of `(name, tags)` pairs. `tags` follows the same rules as in
  [`create_document`](#create_documentfolder_id-name-tags-content). Typically one
  pair per subject.
- **content** : `str`
  The shared body applied to every created document.

**Returns**

- `list` of `dict`
  One API response per created document, in the order of `items`.

**Notes**

A thin loop over [`create_document`](#create_documentfolder_id-name-tags-content);
it issues one request per item (not a bulk endpoint).

**Examples**

```python
date, time = rspace.current_date_time()
items = [
    (f"{date}_{time}_OPI111", ["id_OPI111", "m_mea"]),
    (f"{date}_{time}_OPI112", ["id_OPI112", "m_mea"]),
]
responses = client.create_documents(12345, items, content="Cohort baseline")
```

---

### `list_tags(folder_id=None)`

Collect the unique tags applied across documents.

**Parameters**

- **folder_id** : `int`, optional
  Restrict to a folder subtree (same semantics as
  [`list_documents`](#list_documentsfolder_idnone)). `None` (default) covers all
  visible documents.

**Returns**

- `list` of `str`
  Sorted, de-duplicated tags.

**Examples**

```python
tags = client.list_tags()
methods = [t for t in tags if t.startswith("m_")]
```

---

### `dates_for_tag(tag)`

Find the dates on which a tag was used, read from entry **names**.

**Parameters**

- **tag** : `str`
  The exact tag to match (e.g. `"id_OPI111"`).

**Returns**

- `list` of `str`
  Sorted, unique `YYYYMMDD` dates parsed from the names of documents carrying
  `tag`. Names that don't match the entry-name pattern contribute nothing.

**See also**

[`times_for_tag_and_date`](#times_for_tag_and_datetag-date) — drill down to
times.

**Examples**

```python
dates = client.dates_for_tag("id_OPI111")     # ['20260101', '20260601', …]
```

---

### `times_for_tag_and_date(tag, date)`

Find the times for a tag on a given date, read from entry **names**.

**Parameters**

- **tag** : `str`
  The exact tag to match.
- **date** : `str`
  A `YYYYMMDD` date (as returned by [`dates_for_tag`](#dates_for_tagtag)).

**Returns**

- `list` of `str`
  Sorted, unique `HHMM` times from documents tagged `tag` whose name date equals
  `date`.

**Examples**

```python
times = client.times_for_tag_and_date("id_OPI111", "20260601")   # ['1200', '1330']
```

---

### `list_folders()`

List accessible folders and notebooks as a flat, labelled collection.

**Returns**

- `list` of `dict`
  Sorted by `label`. Each dict has:

  | Key | Type | Meaning |
  |-----|------|---------|
  | `id` | `int` | Folder/notebook id. |
  | `name` | `str` | Its own name. |
  | `label` | `str` | `"Parent > Name"` (or just `Name` at the top). |
  | `notebook` | `bool` | `True` for notebooks, `False` for folders. |
  | `parentId` | `int` or `None` | Parent folder id, if any. |

**Notes**

Good for populating a dropdown. For the full nested hierarchy (including the
documents inside), use [`create_tree`](#create_treefolder_idnone-exclude_top-max_workers8).

**Examples**

```python
for f in client.list_folders():
    print(f["id"], f["label"], "(notebook)" if f["notebook"] else "")
```

---

### `create_tree(folder_id=None, exclude_top=..., max_workers=8)`

Build the workspace hierarchy as a nested tree of nodes.

**Parameters**

- **folder_id** : `int`, optional
  Where to start. `None` (default) starts at the workspace root.
- **exclude_top** : `tuple` of `str`, optional
  Top-level folder names to skip entirely. Defaults to
  [`DEFAULT_EXCLUDED_TOP_FOLDERS`](#module-constants) (`("Gallery", "Examples")`)
  — large system folders that slow traversal and aren't useful as entry
  locations. Pass `()` to include everything. Only applied at the top level.
- **max_workers** : `int`, optional
  Number of threads used to fetch the folders at each depth in parallel
  (default `8`). Set `1` to fetch sequentially.

**Returns**

- `list` of `dict`
  Top-level nodes. Each node is:

  ```python
  {
      "id": int,
      "name": str,
      "type": "folder" | "notebook" | "document" | ...,
      "notebook": bool,
      "children": [ ...nodes... ],   # empty for leaves
  }
  ```

  Children are sorted folders/notebooks first, then everything else,
  alphabetically.

**Notes**

The traversal is breadth-first: all folders on the current level are fetched at
once. Worker threads issue read-only GETs only; the tree is assembled on the
calling thread, so no locking is involved.

**Examples**

```python
tree = client.create_tree()

def walk(nodes, depth=0):
    for n in nodes:
        print("  " * depth + f"{n['name']} ({n['type']})")
        walk(n["children"], depth + 1)

walk(tree)
```

---

### `fetch_metadata(folder_id, output_dir)`

Save a folder's document summaries to a JSON file on disk.

**Parameters**

- **folder_id** : `int`
  The folder whose documents to dump (subtree-scoped, like
  [`list_documents`](#list_documentsfolder_idnone)).
- **output_dir** : `str` or `path-like`
  Destination directory. Created (with parents) if missing.

**Returns**

- `str`
  Path to the written file, named `metadata_<folder_id>.json`.

**Notes**

The JSON it writes is the input expected by the local CSV tools —
[`create_summary_csv`](#create_summary_csvmetadata_file-output_dir-filter_tagsnone)
and [`filterable_tags`](#filterable_tagsmetadata_file).

**Examples**

```python
path = client.fetch_metadata(12345, "~/Desktop")
# → '~/Desktop/metadata_12345.json'
```

---

### `overview(folder_id)`

Collect a document × field table for a folder, in memory.

**Parameters**

- **folder_id** : `int`
  The folder to summarise. Walks the folder *tree*, so shared and nested
  documents are included.

**Returns**

- `tuple` of (`list`, `list`)
  `(columns, rows)` where:
  - `columns` is the union of field names across all documents, in first-seen
    order;
  - `rows` is a list of `(document_name, {field_name: value})`.

  Field values are flattened to single-line plain text (HTML stripped, entities
  unescaped, whitespace collapsed). Documents that can't be read are skipped;
  repeated field names within a document are joined with `"; "`.

**See also**

[`project_overview`](#project_overviewfolder_id-output_dir) — the same data
written straight to a CSV.

**Examples**

```python
columns, rows = client.overview(12345)
print(columns)
for name, record in rows:
    print(name, record)
```

---

### `documents_in_folder(folder_id)`

List every document inside a folder subtree by walking the folder **tree**.

**Parameters**

- **folder_id** : `int`
  The root folder to descend from.

**Returns**

- `list` of `dict`
  `[{"id": int, "name": str}, …]` for every document found at any depth.

**Notes**

Unlike the global `/documents` listing used by
[`list_documents`](#list_documentsfolder_idnone), this walks `folders/tree`
recursively, so it also reaches documents in **shared** folders and nested
subfolders/notebooks.

**Examples**

```python
docs = client.documents_in_folder(12345)
print(len(docs), "documents (including shared/nested)")
```

---

### `project_overview(folder_id, output_dir)`

Write a folder's document × field overview to a CSV.

**Parameters**

- **folder_id** : `int`
  The folder to summarise (see [`overview`](#overviewfolder_id)).
- **output_dir** : `str` or `path-like`
  Destination directory. Created (with parents) if missing.

**Returns**

- `str`
  Path to the written file, named `overview_<folder_id>.csv`. The first column is
  `"Document Name"`; the remaining columns are the form fields (one row per
  document).

**Examples**

```python
csv_path = client.project_overview(12345, "~/Desktop")
```

---

# Stateless helpers

Pure functions (no network, no I/O) that the rest of the module builds on.

### `strip_tag_prefix(tag)`

Remove a leading `id_` or `m_` ID prefix from a tag.

**Parameters** — **tag** : `str`.
**Returns** — `str`: the tag without its ID prefix (unchanged if it has none).

```python
>>> strip_tag_prefix("id_OPI111")
'OPI111'
>>> strip_tag_prefix("m_patch_clamp")
'patch_clamp'
>>> strip_tag_prefix("preprocessed")
'preprocessed'
```

### `current_date_time()`

**Returns** — `tuple` of (`str`, `str`): the current local date and time as
`("YYYYMMDD", "HHMM")`.

```python
>>> current_date_time()
('20260601', '1200')
```

### `parse_entry_name(name)`

Split an entry name `"YYYYMMDD_HHMM_Extra"` into its parts.

**Parameters** — **name** : `str`.
**Returns** — `tuple` of (`date`, `time`, `extra`). If `name` doesn't match the
pattern, returns `("", "", name)`.

```python
>>> parse_entry_name("20260601_1200_test")
('20260601', '1200', 'test')
>>> parse_entry_name("free form")
('', '', 'free form')
```

---

# Local data processing

Offline functions that turn document dicts (from
[`list_documents`](#list_documentsfolder_idnone) /
[`fetch_metadata`](#fetch_metadatafolder_id-output_dir)) into summaries, CSVs and
organised file paths, plus a file-renaming utility.

### `filterable_tags(metadata_file)`

Return the tags in a metadata JSON file that make sense as summary **filters**:
the special `preprocessed` / `results` tags and any method (`m_`) tags present.

**Parameters** — **metadata_file** : `str` or `path-like` — a JSON file of
document dicts.
**Returns** — `list` of `str`, sorted.

### `summarize_documents(docs, filter_tags=None)`

Turn document dicts into **summary rows** — one row per subject (`id_`) tag.

**Parameters**

- **docs** : `list` of `dict`
  Document summaries.
- **filter_tags** : collection of `str`, optional
  If non-empty, keep only documents carrying **at least one** of these tags (an
  OR filter — e.g. `["preprocessed", "m_mea"]` keeps entries that are
  preprocessed *or* used that method).

**Returns**

- `list` of `dict`
  Each row is keyed by [`SUMMARY_FIELDS`](#module-constants): `mouseID`, `date`,
  `time`, `experimenter_name`, `method`, `tags`, `extra`. The `mouseID` and
  `method` values have their prefixes stripped; `tags` keeps the raw list
  (`;`-joined). Documents with no subject id but tagged `preprocessed`/`results`
  produce one row with an empty `mouseID` (so their paths can still be built).

**Examples**

```python
rows = summarize_documents(docs)
rows = summarize_documents(docs, filter_tags=["preprocessed"])
```

### `create_summary_csv(metadata_file, output_dir, filter_tags=None)`

Read a metadata JSON file, summarise it, and write `summary_<stem>.csv`.

**Parameters** — **metadata_file** : path-like; **output_dir** : path-like;
**filter_tags** : optional (see [`summarize_documents`](#summarize_documentsdocs-filter_tagsnone)).
**Returns** — `str`: the written CSV path.

### `filepaths_for_rows(rows, lab_group=LAB_GROUP)`

Build organised file paths from summary rows.

**Parameters**

- **rows** : `list` of `dict`
  Rows shaped like [`summarize_documents`](#summarize_documentsdocs-filter_tagsnone)
  output.
- **lab_group** : `str`, optional
  Lab group used in `processed_data/…` paths (default
  [`LAB_GROUP`](#module-constants), `"ag_beck"`).

**Returns**

- `list` of `tuple`
  `(mouseID, filepath)` pairs. The filename is `mouseID_date_time_extra` (empty
  parts omitted). The directory depends on tags:
  - `preprocessed` → `processed_data/<lab>/<experimenter>/preprocessed/…`
  - `results` → `processed_data/<lab>/<experimenter>/results/…`
  - otherwise (raw) → `<method>/<experimenter>/…` (method falls back to
    `unknown_method`).

  An entry tagged both `preprocessed` and `results` yields one path for each.

### `generate_filepaths(summary_csv, output_dir, lab_group=None)`

Read a summary CSV, build organised paths, and write
`filepaths_<stem>.csv` (columns: `mouseID`, `filepath`).

**Parameters** — **summary_csv** : path-like; **output_dir** : path-like;
**lab_group** : `str`, optional (defaults to the saved
[`load_lab_group()`](#load_lab_group) setting).
**Returns** — `str`: the written CSV path.

### `build_renamed_name(original_name, prefix, strip_front=0, strip_back=0)`

Compute a new file name (pure; touches nothing on disk).

**Parameters**

- **original_name** : `str` — the current file name.
- **prefix** : `str` — prepended as `"{prefix}_{remainder}"`.
- **strip_front** : `int`, optional — characters removed from the start of the
  name (the extension is always kept).
- **strip_back** : `int`, optional — characters removed from the end of the stem.

**Returns** — `str`: the new name.

```python
>>> build_renamed_name("20260101_1200_rec.tif", "OPI111", strip_front=14)
'OPI111_rec.tif'
>>> build_renamed_name("scan.tif", "OPI111")
'OPI111_scan.tif'
```

### `rename_and_organize_files(files, prefix, dest_folder=None, raw_data_folder=None, strip_front=0, strip_back=0)`

Rename files with a `prefix_` and optionally move/copy them. **Touches the
filesystem.**

**Parameters**

- **files** : iterable of path-like — the files to process.
- **prefix** : `str` — name prefix (see
  [`build_renamed_name`](#build_renamed_nameoriginal_name-prefix-strip_front0-strip_back0)).
- **dest_folder** : path-like, optional — if given, renamed files are **moved**
  here (folder created as needed).
- **raw_data_folder** : path-like, optional — if given, files are **copied** here
  (from their post-move location).
- **strip_front**, **strip_back** : `int`, optional — passed to
  `build_renamed_name`.

**Returns** — `list` of `pathlib.Path`: the final location of each file.

**Notes** — Order of operations: (1) rename in place → (2) move to `dest_folder`
→ (3) copy to `raw_data_folder`.

---

# Drafts / autosave

Persist in-progress entries as JSON inside the application folder, so an unsaved
note survives a crash. The directory is `$RSPACE_AUTOSAVE_DIR` if set, else
`<project>/Autosaved`.

### `autosave_dir()`

**Returns** — `pathlib.Path`: the drafts directory (see above).

### `save_draft(draft_id, data)`

Write a draft dict to `<autosave_dir>/<draft_id>.json`, stamping `saved_at`.

**Parameters** — **draft_id** : `str`; **data** : `dict`.
**Returns** — `str`: the written path.

### `list_drafts()`

**Returns** — `list` of `dict`: `[{"path", "id", "name", "saved_at"}, …]`, newest
first.

### `load_draft(path)`

**Parameters** — **path** : path-like.
**Returns** — `dict`: the stored draft.

### `delete_draft(path)`

Delete the draft file at `path` (silently ignored if it doesn't exist). Returns
`None`.

---

# Stored-credentials convenience layer

*Optional.* For apps that want to persist **one** set of credentials, the module
can store them in `config/config.json` (inside the application folder, override
with `$RSPACE_CONFIG_DIR`) and expose module-level functions that operate through
a default client built from them. Applications that don't want this can ignore it
and use [`RSpaceClient`](#rspaceclient) directly.

### Credential storage

| Function | Description |
|----------|-------------|
| `load_credentials()` | Return the saved `(api_key, url)` (migrating from a legacy location on first use). Cached. |
| `save_credentials(api_key, url)` | Persist credentials (preserving other config keys) and reset the cached default client. Returns `(api_key, url)`. |
| `has_credentials()` | `True` if an API key has been configured. |
| `load_lab_group()` | The configured lab group for processed-data paths (default `ag_beck`). |
| `save_lab_group(lab_group)` | Persist the lab group; blank falls back to the default. |
| `default_client()` | A shared [`RSpaceClient`](#rspaceclient) built from the saved credentials (cached). |
| `test_credentials(api_key, url)` | Validate the given credentials **without saving**. Returns `(ok, message)`. |

### Module-level wrappers

Thin wrappers that delegate to [`default_client()`](#stored-credentials-convenience-layer);
they take no credentials because the saved ones are used.

| Function | Delegates to |
|----------|--------------|
| `check_connection()` | [`RSpaceClient.check_connection`](#check_connection) |
| `get_tags(project_folder=None)` | [`list_tags`](#list_tagsfolder_idnone) |
| `list_all_folders()` | [`list_folders`](#list_folders) |
| `create_tree()` | [`RSpaceClient.create_tree`](#create_treefolder_idnone-exclude_top-max_workers8) |
| `get_metadata_in_folder(folder_id, output_dir)` | [`fetch_metadata`](#fetch_metadatafolder_id-output_dir) |
| `get_dates_for_tag(tag)` | [`dates_for_tag`](#dates_for_tagtag) |
| `get_times_for_tag_and_date(tag, date)` | [`times_for_tag_and_date`](#times_for_tag_and_datetag-date) |
| `project_overview(folder_id, output_dir)` | [`RSpaceClient.project_overview`](#project_overviewfolder_id-output_dir) |
| `create_entry(project_folder, tags, name, content)` | [`create_document`](#create_documentfolder_id-name-tags-content) |
| `create_entries(project_folder, items, content)` | [`create_documents`](#create_documentsfolder_id-items-content) |

**Example**

```python
import rspace

rspace.save_credentials("your-key", "https://rspace.uni-bonn.de")
rspace.save_lab_group("ag_beck")

ok, message = rspace.check_connection()
folders = rspace.list_all_folders()
rspace.create_entry(12345, ["id_OPI111"], "20260601_1200_test", "Notes")
```

---

# Module constants

| Name | Value | Meaning |
|------|-------|---------|
| `DEFAULT_RSPACE_URL` | `"https://rspace.uni-bonn.de"` | Default server URL. |
| `ID_PREFIX` | `"id_"` | Subject-ID tag prefix. |
| `METHOD_PREFIX` | `"m_"` | Method-ID tag prefix. |
| `SUMMARY_FIELDS` | `["mouseID", "date", "time", "experimenter_name", "method", "tags", "extra"]` | Column order of the summary CSV. |
| `DEFAULT_EXCLUDED_TOP_FOLDERS` | `("Gallery", "Examples")` | Top-level folders [`create_tree`](#create_treefolder_idnone-exclude_top-max_workers8) skips by default. |
| `LAB_GROUP` | `"ag_beck"` | Default lab group in `processed_data/…` paths. |
| `PREPROCESSED_TAG` | `"preprocessed"` | Data-state tag routed to `processed_data/…/preprocessed`. |
| `RESULTS_TAG` | `"results"` | Data-state tag routed to `processed_data/…/results`. |

The public API is also enumerated in the module's `__all__`.

---

*See [`examples.py`](examples.py) for a runnable demonstration of everything
above, and the module docstring in [`src/rspace.py`](../src/rspace.py) for the
authoritative source.*
