# IEECRSpace

A desktop application (and reusable Python module) for working with the
[RSpace](https://www.researchspace.com/) electronic lab notebook at the **Institute of
Experimental Epileptology and Cognition Research (IEECR)**.

It helps lab members **create structured entries**, **log analysis results**,
**organise/rename local data files**, and **export overviews** of a project — all from a
simple tabbed interface, talking to RSpace through its REST API.

The whole program lives in **one self-contained folder** (ImageJ-style): you download it,
double-click a launcher, and everything it needs — a private Python, the dependencies,
and your settings — is set up *inside that folder*. Nothing is installed system-wide and
nothing is written to your user/AppData profile, which keeps it working on managed/domain
Windows machines.

---

## Installation

1. **Download** the project folder (Code → Download ZIP, or a release zip) and unzip it
   somewhere you can keep it (e.g. your Desktop). Keep the whole folder together.
2. **Start it** by double-clicking the launcher for your operating system:
   - **Windows:** `IEECRSpace_Launcher.bat`
   - **macOS:** `IEECRSpace_Launcher.command`
   - **Linux:** run `bash IEECRSpace_Launcher.sh`
3. The **first start** downloads a private copy of Python and the dependencies into the
   folder (needs an internet connection, takes a minute). Every later start is instant.
4. In the app, open the **Settings** tab and paste your **RSpace API key**
   (RSpace → *My RSpace → My Profile → API Key*), then click **Save**.

No pre-installed Python is required — the launcher fetches [`uv`](https://docs.astral.sh/uv/)
into the folder and uses it to provide everything.

> **First-open security prompts:** because the launcher is downloaded from the internet,
> macOS may ask you to confirm (right-click → *Open* the first time) and Windows may show a
> SmartScreen notice (*More info → Run anyway*). This is expected for unsigned scripts.

---

## Main features

The interface is organised into tabs:

| Tab | What it does |
|-----|--------------|
| **Create Entry** | Create one or more entries in a chosen RSpace folder. Pick the subject ID(s) — use **Add subject +** for several animals at once — set the date/time (or tick *Fill in current date & time*), add a short name and any extra tags, and preview the resulting name `date_time_name`. One entry is created per subject, each tagged with its own subject ID plus the shared tags. An optional **autosave** saves the in-progress draft to the `Autosaved/` folder once a minute; drafts can be reloaded from a dropdown, and optionally deleted after publishing. |
| **Rename Files** | Rename local data files with a structured `ID_date_time` prefix (the ID is looked up from RSpace tags, prefix stripped). Optionally erase characters from the original name, move the files into a new folder, and/or copy them to a raw-data location. |
| **Fetch Metadata** | Download the metadata of all documents in a folder as a JSON file (the starting point for the CSV tools). |
| **Summary CSV** | Turn fetched metadata into a spreadsheet — one row per subject. Optionally **filter** entries by tag: add `preprocessed`, `results`, or any method found in the file, and only entries carrying **any** of the selected tags are kept. |
| **File Paths** | Generate a suggested, organised file path for each entry and save them as a CSV. Raw entries go to `method/experimenter/filename`; entries tagged `preprocessed` or `results` go to `processed_data/<lab group>/<experimenter>/<preprocessed\|results>/filename`. |
| **Project Overview** | Build a spreadsheet of a whole folder: one row per document, one column per form field (header = field name, cell = value). Works for shared folders too. |
| **Results Entry** | Log a folder of analysis results: browse to the local **results folder** (its name becomes the entry name), pick the RSpace destination, and add a **comment** describing how the results were obtained. The entry is tagged `results`, so the File Paths tab reproduces its location as `processed_data/<lab group>/<your name>/results/<folder name>`. |
| **Settings** | Store and test your API key and server URL, and set the **lab group** used in processed-data paths (default `ag_beck`). |

The folder pickers show the **entire workspace folder tree** (folders and notebooks, at all
depths), fetched in parallel for speed. Output locations are chosen with a file browser.

### Tag conventions

Tags carry meaning that the tools rely on:

- **Subject IDs** start with `id_` (e.g. `id_OPI111`).
- **Method IDs** start with `m_` (e.g. `m_patch_clamp`).
- `preprocessed` / `results` mark a document's data state and route its generated file path
  into `processed_data/…` (see the File Paths tab).
- Any other tag is treated as a plain data-state tag.

When an ID is used to build a *name*, the prefix is dropped (`id_OPI111` → `OPI111`).

---

## Using the backend as a library

The networking and data logic live in [`src/rspace.py`](src/rspace.py) and can be reused
independently of the GUI. The core is the `RSpaceClient` class (no global state, so it is
easy to test and embed):

```python
from rspace import RSpaceClient

client = RSpaceClient(api_key="your-key", url="https://rspace.uni-bonn.de")

ok, message = client.check_connection()
folders = client.list_folders()
tree    = client.create_tree()                      # full nested folder/notebook tree
client.create_document(folder_id=12345,
                       name="OPI111_20260601_1200_test",
                       tags=["id_OPI111", "m_mea"],
                       content="Notes…")
client.project_overview(folder_id=12345, output_dir="~/Desktop")
```

Stateless helpers (`strip_tag_prefix`, `summarize_documents`, `create_summary_csv`,
`filterable_tags`, `generate_filepaths`, `build_renamed_name`, …) are available as plain
functions. See the module docstring and `__all__` for the full public API. Credentials and
the lab group can be supplied explicitly (as above) or, for the bundled app, stored in
`config/config.json` via `save_credentials()`/`load_credentials()` and
`save_lab_group()`/`load_lab_group()`.

---

## Project structure

```
IEECRSpace/
├── IEECRSpace_Launcher.command / .bat / .sh   # double-click to run (self-installing)
├── src/
│   ├── rspace.py            # RSpace API client + helpers (reusable module)
│   ├── rspace_interface.py  # the PyQt6 GUI
│   └── IEECRlogo.png
├── config/                  # config.json (API key, server URL, lab group) — stays local
├── Autosaved/               # in-progress Create-Entry drafts (created when used)
├── Installation/
│   ├── install.sh / install.bat   # portable setup (run automatically on first launch)
│   └── create_package.py          # build a distributable zip
├── pyproject.toml / uv.lock / .python-version   # pinned Python + dependencies
├── .uv/   (created on install)    # private uv binary, Python and cache
└── .venv/ (created on install)    # the dependency environment
```

`config/`, `Autosaved/`, `.uv/` and `.venv/` are machine-local and are never committed or
shipped — your API key stays on your computer only.

---

## Requirements

- Internet access on first launch (and whenever talking to RSpace).
- A valid RSpace account and API key.
- Windows, macOS or Linux. No administrator rights and no separate Python installation
  needed.
