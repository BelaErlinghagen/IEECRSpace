"""Worked examples for every public function in ``src/rspace.py``.

This script is a *runnable tour* of the RSpace backend. It is organised into one
section per area of the API, and each section is a small self-contained function
you can read top-to-bottom or call individually. The companion file
``README.md`` (next to this one) is the reference manual; this file is the
"show me" counterpart.

--------------------------------------------------------------------------------
Running it
--------------------------------------------------------------------------------
The networking examples need a live RSpace account. Supply credentials through
environment variables (nothing is written to disk unless you ask for it):

    export RSPACE_API_KEY="your-api-key"
    export RSPACE_URL="https://rspace.uni-bonn.de"        # optional
    export RSPACE_FOLDER_ID="12345"                       # a folder you can read

Then, from the project root:

    python Documentation/examples.py

By default the script only runs **read-only** demos. Operations that create or
move data (creating documents, renaming files) are gated behind the two flags
below so that simply running the file never changes anything on the server or on
disk. Flip them to ``True`` when you want to see the write path.

The stateless / local-data examples (tag parsing, summary CSVs, file-path
generation, renaming) need no network and run with no credentials at all.
"""

import os
import sys
import tempfile
from pathlib import Path

# ``rspace.py`` lives in ``<project>/src``; this file lives in
# ``<project>/Documentation``. Add the source directory to the import path so
# ``import rspace`` works no matter where the script is launched from.
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import rspace
from rspace import RSpaceClient

# ── Toggles ──────────────────────────────────────────────────────────────────
# Read-only demos always run. The two below mutate state, so they are opt-in.
RUN_WRITE_EXAMPLES = False   # create_document / create_documents / create_entry…
RUN_RENAME_EXAMPLES = False  # rename_and_organize_files (renames real files)


# ── Helpers used by the examples themselves ──────────────────────────────────

def _env(name, default=None, required=False):
    """Read an environment variable, optionally treating it as required."""
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(
            f"Set the {name} environment variable to run the networking examples "
            f"(see the module docstring at the top of this file)."
        )
    return value


def _make_client():
    """Build an :class:`RSpaceClient` from RSPACE_API_KEY / RSPACE_URL."""
    api_key = _env("RSPACE_API_KEY", required=True)
    url = _env("RSPACE_URL", rspace.DEFAULT_RSPACE_URL)
    # timeout and session are optional; shown here for completeness.
    return RSpaceClient(api_key, url, timeout=30, session=None)


def _folder_id():
    """Return the demo folder id from RSPACE_FOLDER_ID (as an int)."""
    return int(_env("RSPACE_FOLDER_ID", required=True))


def _banner(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Connecting to a server
# ─────────────────────────────────────────────────────────────────────────────

def example_connection():
    """RSpaceClient(...) and check_connection().

    A client bundles an API key with a server URL and performs every network
    call. It holds no global state, so you can create as many as you like.
    """
    _banner("1. Connection")

    client = RSpaceClient(
        api_key=_env("RSPACE_API_KEY", required=True),
        url=_env("RSPACE_URL", rspace.DEFAULT_RSPACE_URL),
        timeout=30,        # seconds before a request gives up
    )

    # ``base_url`` is the REST root the client talks to.
    print("Talking to:", client.base_url)

    # check_connection() never raises — it returns (ok, human-readable message),
    # which is exactly what you want for a "Test connection" button.
    ok, message = client.check_connection()
    print("Connected!" if ok else "Not connected:", message)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# 2. Reading documents
# ─────────────────────────────────────────────────────────────────────────────

def example_list_documents(client):
    """list_documents() and list_documents(folder_id=…).

    Returns lightweight summaries (name, tags, owner, parentFolderId …) — but
    NOT the field content. Pass a ``folder_id`` to restrict to that subtree.
    """
    _banner("2a. list_documents")

    all_docs = client.list_documents()
    print(f"{len(all_docs)} documents visible to this account")
    for doc in all_docs[:5]:
        print(f"  [{doc['id']}] {doc.get('name','')}  tags={doc.get('tags','')!r}")

    folder_docs = client.list_documents(folder_id=_folder_id())
    print(f"{len(folder_docs)} documents inside folder {_folder_id()}")
    return all_docs


def example_get_document(client, all_docs):
    """get_document(doc_id).

    Fetches ONE complete document, including its ``fields`` (the form contents),
    which the summaries from list_documents() omit.
    """
    _banner("2b. get_document")

    if not all_docs:
        print("No documents to fetch — skipping.")
        return

    doc_id = all_docs[0]["id"]
    full = client.get_document(doc_id)
    print(f"Document {doc_id}: {full.get('name','')}")
    for field in full.get("fields", []):
        # Field content of "text" fields is HTML; here we just show its length.
        content = field.get("content") or ""
        print(f"  field {field.get('name','?')!r}: {len(content)} chars")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Creating documents (WRITE — gated behind RUN_WRITE_EXAMPLES)
# ─────────────────────────────────────────────────────────────────────────────

def example_create_documents(client):
    """create_document(...) and create_documents(...).

    ``create_document`` makes a single entry; ``tags`` may be a list/tuple or a
    comma-separated string. ``create_documents`` makes one entry per (name, tags)
    pair — handy for logging the same observation across several subjects.
    """
    _banner("3. create_document / create_documents")

    if not RUN_WRITE_EXAMPLES:
        print("Skipped (set RUN_WRITE_EXAMPLES = True to actually create entries).")
        return

    folder_id = _folder_id()
    date, time = rspace.current_date_time()  # ("YYYYMMDD", "HHMM")

    # One entry, tagged with a subject id and a method id.
    single = client.create_document(
        folder_id=folder_id,
        name=f"{date}_{time}_example_single",
        tags=["id_OPI111", "m_mea"],          # list or "id_OPI111,m_mea" both work
        content="Created by Documentation/examples.py",
    )
    print("Created document id:", single.get("id"))

    # Several entries at once: one (name, tags) pair per subject.
    items = [
        (f"{date}_{time}_example_OPI111", ["id_OPI111", "m_mea"]),
        (f"{date}_{time}_example_OPI112", ["id_OPI112", "m_mea"]),
    ]
    batch = client.create_documents(folder_id, items, content="Batch example")
    print("Created", len(batch), "documents in a batch")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Tags and the names derived from them
# ─────────────────────────────────────────────────────────────────────────────

def example_tags(client):
    """list_tags(), dates_for_tag(tag), times_for_tag_and_date(tag, date).

    These power the cascading "tag → date → time" pickers in the GUI. Dates and
    times are read out of the entry *names* ("YYYYMMDD_HHMM_extra").
    """
    _banner("4. tags / dates / times")

    tags = client.list_tags()                       # all tags, sorted & unique
    print(f"{len(tags)} distinct tags:", tags[:10], "…" if len(tags) > 10 else "")

    # You can also scope tags to a folder subtree:
    folder_tags = client.list_tags(folder_id=_folder_id())
    print(f"{len(folder_tags)} tags inside folder {_folder_id()}")

    if not tags:
        print("No tags — skipping date/time drill-down.")
        return

    tag = tags[0]
    dates = client.dates_for_tag(tag)               # ["20260101", …]
    print(f"Tag {tag!r} appears on dates:", dates)
    if dates:
        times = client.times_for_tag_and_date(tag, dates[0])  # ["1200", …]
        print(f"  on {dates[0]} at times:", times)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Folders and the workspace tree
# ─────────────────────────────────────────────────────────────────────────────

def example_folders(client):
    """list_folders() and create_tree().

    ``list_folders`` returns a flat, labelled list good for a dropdown.
    ``create_tree`` returns the full nested hierarchy (folders, notebooks and the
    documents inside them) good for a tree widget.
    """
    _banner("5. list_folders / create_tree")

    folders = client.list_folders()
    print(f"{len(folders)} folders/notebooks:")
    for f in folders[:8]:
        kind = "notebook" if f["notebook"] else "folder"
        print(f"  [{f['id']}] {f['label']}  ({kind})")

    # The full tree. exclude_top skips big system folders by default; pass () to
    # include everything, or raise max_workers for faster parallel fetching.
    tree = client.create_tree(max_workers=8)

    def _count(nodes):
        return sum(1 + _count(n["children"]) for n in nodes)

    print(f"Tree has {_count(tree)} nodes across {len(tree)} top-level entries")

    def _print(nodes, depth=0):
        for node in nodes[:3]:            # first few per level, to keep it short
            print("    " * depth + f"- {node['name']} ({node['type']})")
            _print(node["children"], depth + 1)

    _print(tree)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Reports: fetching metadata and building overviews
# ─────────────────────────────────────────────────────────────────────────────

def example_reports(client, output_dir):
    """fetch_metadata(), documents_in_folder(), overview(), project_overview().

    ``fetch_metadata`` dumps a folder's document summaries to JSON (the input for
    the local CSV tools in section 7). ``documents_in_folder`` walks the folder
    *tree* (so it also reaches shared/nested items). ``overview`` collects a
    document×field table in memory; ``project_overview`` writes it as a CSV.
    """
    _banner("6. fetch_metadata / documents_in_folder / overview / project_overview")

    folder_id = _folder_id()

    meta_path = client.fetch_metadata(folder_id, output_dir)
    print("Wrote metadata JSON →", meta_path)

    docs = client.documents_in_folder(folder_id)
    print(f"documents_in_folder found {len(docs)} documents (incl. nested/shared)")

    columns, rows = client.overview(folder_id)
    print(f"overview: {len(columns)} field columns × {len(rows)} documents")

    csv_path = client.project_overview(folder_id, output_dir)
    print("Wrote overview CSV →", csv_path)
    return meta_path


# ─────────────────────────────────────────────────────────────────────────────
# 7. Stateless helpers — NO network required
# ─────────────────────────────────────────────────────────────────────────────

def example_stateless_helpers():
    """strip_tag_prefix, current_date_time, parse_entry_name.

    Pure functions that the rest of the module is built on. No client needed.
    """
    _banner("7. Stateless helpers (no network)")

    print("strip_tag_prefix('id_OPI111')      →", rspace.strip_tag_prefix("id_OPI111"))
    print("strip_tag_prefix('m_patch_clamp')  →", rspace.strip_tag_prefix("m_patch_clamp"))
    print("strip_tag_prefix('preprocessed')   →", rspace.strip_tag_prefix("preprocessed"))

    date, time = rspace.current_date_time()
    print("current_date_time()                →", (date, time))

    print("parse_entry_name('20260601_1200_test') →",
          rspace.parse_entry_name("20260601_1200_test"))
    print("parse_entry_name('free form name')     →",
          rspace.parse_entry_name("free form name"))


def example_local_csv_pipeline(output_dir):
    """summarize_documents → create_summary_csv → generate_filepaths, plus
    filterable_tags and filepaths_for_rows.

    This is the local (offline) data pipeline: starting from document dicts (as
    produced by list_documents / fetch_metadata), it builds summary rows, writes
    a summary CSV, and then derives organised file paths from it.
    """
    _banner("7b. Local CSV / file-path pipeline (no network)")

    # Stand-in for what fetch_metadata would have written. Each dict is shaped
    # like an RSpace document summary.
    docs = [
        {"name": "20260601_1200_baseline",
         "tags": "id_OPI111,m_mea",
         "owner": {"firstName": "Ada", "lastName": "Lovelace"}},
        {"name": "20260601_1330_analysis",
         "tags": "preprocessed",
         "owner": {"firstName": "Ada", "lastName": "Lovelace"}},
    ]

    # summarize_documents: one row per subject id, prefixes stripped for naming.
    rows = rspace.summarize_documents(docs)
    print("summarize_documents rows:")
    for row in rows:
        print("   ", {k: row[k] for k in ("mouseID", "date", "time", "method", "tags")})

    # The OR-filter keeps only entries carrying any of the given tags.
    only_preprocessed = rspace.summarize_documents(docs, filter_tags=["preprocessed"])
    print("filtered to 'preprocessed':", len(only_preprocessed), "row(s)")

    # filepaths_for_rows: organised paths derived from the rows above.
    print("filepaths_for_rows:")
    for mouse_id, path in rspace.filepaths_for_rows(rows, lab_group="ag_beck"):
        print(f"    {mouse_id or '(none)'} → {path}")

    # The file-based variants: write a metadata JSON, then drive the CSV tools.
    import json
    meta_file = Path(output_dir) / "metadata_demo.json"
    meta_file.write_text(json.dumps(docs, indent=2))

    print("filterable_tags:", rspace.filterable_tags(meta_file))

    summary_csv = rspace.create_summary_csv(meta_file, output_dir)
    print("create_summary_csv →", summary_csv)

    filepaths_csv = rspace.generate_filepaths(summary_csv, output_dir, lab_group="ag_beck")
    print("generate_filepaths →", filepaths_csv)


def example_renaming(output_dir):
    """build_renamed_name and rename_and_organize_files.

    ``build_renamed_name`` is pure (just computes the new name). The full
    ``rename_and_organize_files`` renames files on disk, so it is gated.
    """
    _banner("7c. File renaming (touches disk — gated)")

    # Pure name computation — always safe to show.
    print("build_renamed_name('20260101_1200_rec.tif', 'OPI111', strip_front=14) →",
          rspace.build_renamed_name("20260101_1200_rec.tif", "OPI111", strip_front=14))
    print("build_renamed_name('scan.tif', 'OPI111')                              →",
          rspace.build_renamed_name("scan.tif", "OPI111"))

    if not RUN_RENAME_EXAMPLES:
        print("rename_and_organize_files skipped "
              "(set RUN_RENAME_EXAMPLES = True to rename real files).")
        return

    # Create throwaway files in a temp area and rename/organise them.
    work = Path(output_dir) / "rename_demo"
    work.mkdir(parents=True, exist_ok=True)
    sources = []
    for n in range(2):
        p = work / f"raw_{n}.tif"
        p.write_text("dummy")
        sources.append(p)

    final = rspace.rename_and_organize_files(
        files=sources,
        prefix="OPI111",
        dest_folder=work / "organised",
        raw_data_folder=work / "raw_backup",
        strip_front=0,
        strip_back=0,
    )
    print("rename_and_organize_files produced:")
    for path in final:
        print("   ", path)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Drafts / autosave (in-folder JSON) — NO network required
# ─────────────────────────────────────────────────────────────────────────────

def example_drafts():
    """save_draft, list_drafts, load_draft, delete_draft (and autosave_dir).

    The Create-Entry tab autosaves in-progress entries as JSON so an unsaved note
    survives a crash. Point RSPACE_AUTOSAVE_DIR at a temp dir here so the demo
    doesn't litter the project's ``Autosaved/`` folder.
    """
    _banner("8. Drafts / autosave (no network)")

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RSPACE_AUTOSAVE_DIR"] = tmp
        print("autosave_dir() →", rspace.autosave_dir())

        path = rspace.save_draft("draft-001", {"name": "Patch clamp run",
                                               "tags": ["id_OPI111"],
                                               "content": "half-written note"})
        print("save_draft     →", path)

        drafts = rspace.list_drafts()
        print("list_drafts    →", [(d["id"], d["name"], d["saved_at"]) for d in drafts])

        loaded = rspace.load_draft(drafts[0]["path"])
        print("load_draft     →", loaded["name"], "/", loaded["tags"])

        rspace.delete_draft(drafts[0]["path"])
        print("delete_draft   →", len(rspace.list_drafts()), "drafts remaining")

    os.environ.pop("RSPACE_AUTOSAVE_DIR", None)


# ─────────────────────────────────────────────────────────────────────────────
# 9. Stored-credentials convenience layer (optional)
# ─────────────────────────────────────────────────────────────────────────────

def example_stored_credentials():
    """save_credentials / load_credentials / has_credentials / default_client,
    save_lab_group / load_lab_group, test_credentials, and the module-level
    wrappers (check_connection, get_tags, list_all_folders, create_tree,
    get_metadata_in_folder, get_dates_for_tag, get_times_for_tag_and_date,
    project_overview, create_entry, create_entries).

    For apps that want to persist ONE set of credentials, the module can store
    them in ``config/config.json`` and expose functions that work through a
    default client built from them. We redirect the config to a temp dir so this
    demo doesn't touch your real saved key.
    """
    _banner("9. Stored-credentials convenience layer")

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["RSPACE_CONFIG_DIR"] = tmp
        # Reset the module's cached credentials/client so it re-reads our temp dir.
        rspace._credentials = None
        rspace._default_client = None

        print("has_credentials() (before) →", rspace.has_credentials())

        # Validate without saving:
        ok, msg = rspace.test_credentials("not-a-real-key", rspace.DEFAULT_RSPACE_URL)
        print("test_credentials(fake)     →", ok, "—", msg)

        # Persist credentials + lab group into config.json:
        rspace.save_credentials(api_key=_env("RSPACE_API_KEY", "demo-key"),
                                url=_env("RSPACE_URL", rspace.DEFAULT_RSPACE_URL))
        rspace.save_lab_group("ag_beck")
        print("load_credentials()         →", rspace.load_credentials())
        print("load_lab_group()           →", rspace.load_lab_group())
        print("has_credentials() (after)  →", rspace.has_credentials())

        # default_client() builds (and caches) an RSpaceClient from the above.
        client = rspace.default_client()
        print("default_client()           →", type(client).__name__, "@", client.base_url)

        # The module-level wrappers below all delegate to default_client():
        #
        #     rspace.check_connection()
        #     rspace.get_tags(project_folder=None)
        #     rspace.list_all_folders()
        #     rspace.create_tree()
        #     rspace.get_metadata_in_folder(folder_id, output_dir)
        #     rspace.get_dates_for_tag(tag)
        #     rspace.get_times_for_tag_and_date(tag, date)
        #     rspace.project_overview(folder_id, output_dir)
        #     rspace.create_entry(project_folder, tags, name, content)
        #     rspace.create_entries(project_folder, items, content)
        #
        # They only do something useful with a real API key, so we just show one:
        if _env("RSPACE_API_KEY"):
            ok, msg = rspace.check_connection()
            print("check_connection() (wrapper) →", ok, "—", msg)
        else:
            print("(set RSPACE_API_KEY to exercise the networking wrappers)")

        # Clean up module state so we don't leak the temp config to other code.
        rspace._credentials = None
        rspace._default_client = None

    os.environ.pop("RSPACE_CONFIG_DIR", None)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # These never need the network or credentials — always safe to run.
    example_stateless_helpers()
    example_drafts()

    with tempfile.TemporaryDirectory() as out:
        example_local_csv_pipeline(out)
        example_renaming(out)

        # The networking demos only run if an API key is configured.
        if not os.environ.get("RSPACE_API_KEY"):
            print("\n" + "=" * 78)
            print("Set RSPACE_API_KEY (and RSPACE_FOLDER_ID) to run the networking "
                  "examples.\nSee the docstring at the top of this file.")
            print("=" * 78)
            return

        client = example_connection()
        all_docs = example_list_documents(client)
        example_get_document(client, all_docs)
        example_create_documents(client)
        example_tags(client)
        example_folders(client)
        example_reports(client, out)

    example_stored_credentials()


if __name__ == "__main__":
    main()
