# Graph Report - WPXX_OncoSeg  (2026-10-16)

## Corpus Check
- 63 files · ~58,699 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 17 file(s) not represented in the graph (top: .gz 10, .css 4, (none) 2)

## Summary
- 1034 nodes · 3296 edges · 52 communities (37 shown, 15 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 209 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `54ebc1ba`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- simpleitk
- lung_api.py
- WorkflowService
- get
- app.js
- annotate.js
- totalseg_stats.py
- oncometra.py
- oncometra.js
- test_oncometra.py
- platform_api.py
- build_router
- SpeechToTextNotConfigured
- test_platform.py
- imaging.py
- ViewerFullscreen
- os
- get_slice
- platformWorkspace
- StudyStore
- AI-Native Cloud PACS/RIS Blueprint
- main.py
- Oncometra Imaging Workspace
- not_found_handler
- Segmenter
- MVP Scaffold
- Recommended Platform Decomposition
- static/import-files.mjs
- Oncometra Demonstration
- mask-editing.mjs
- README.md
- OncoRadar integration decisions
- Running the unified workspace
- demo_admin.py
- nodule-controls.mjs
- MVP Build Sequence
- oncoradar_import.py
- annotation-workflow.mjs
- Local Hosting And Deployment Modes
- json
- pathlib
- sync_oncoradar
- radiomics.py
- seed_demo
- platform_services.py

## God Nodes (most connected - your core abstractions)
1. `WorkflowService` - 47 edges
2. `build_router()` - 46 edges
3. `get()` - 42 edges
4. `audit()` - 29 edges
5. `WorkspaceCase` - 24 edges
6. `study_head()` - 23 edges
7. `require_admin()` - 23 edges
8. `retire_seeded_demo_cases()` - 23 edges
9. `start_job()` - 22 edges
10. `image_directory()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `Suggested Domain Model` --references--> `Patient`  [INFERRED]
  docs/ai-native-pacs-ris-blueprint.md → app/models.py
- `Database-Backed Workflow` --references--> `Patient`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py
- `Database-Backed Workflow` --references--> `StudyRecord`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py
- `Suggested Domain Model` --references--> `WorklistItem`  [INFERRED]
  docs/ai-native-pacs-ris-blueprint.md → app/models.py
- `Database-Backed Workflow` --references--> `WorklistItem`  [INFERRED]
  docs/mvp-scaffold.md → app/models.py

## Import Cycles
- None detected.

## Communities (52 total, 15 thin omitted)

### Community 0 - "simpleitk"
Cohesion: 0.06
Nodes (61): image_directory(), WorkspaceCase, open_local_exam(), preview(), _ct_grid(), is_tumor_text(), paint_frames(), paint_on_grid() (+53 more)

### Community 1 - "lung_api.py"
Cohesion: 0.08
Nodes (77): accept_job(), _acquire_worker_lock(), add_nodule(), annotation_state(), approve_case(), cancel_job(), check_editable(), check_version() (+69 more)

### Community 2 - "WorkflowService"
Cohesion: 0.15
Nodes (8): AiArtifact, AiTask, Report, TrainingRun, WorklistItem, WorkflowService, Suggested Domain Model, Database-Backed Workflow

### Community 3 - "get"
Cohesion: 0.16
Nodes (28): auto_segment(), AutoSegmentRequest, get_report(), get_study(), get_workspace(), healthz(), list_ai_tasks(), list_billing() (+20 more)

### Community 4 - "app.js"
Cohesion: 0.07
Nodes (65): api(), applyViewerLayout(), applyZoom(), bootstrap(), canvasPointToImage(), comparisonAvailable(), displayCtx, drawBrushStroke() (+57 more)

### Community 5 - "annotate.js"
Cohesion: 0.11
Nodes (56): activeNodule(), addNodule(), api(), axes(), base(), cancelPendingPoint(), changeEditSetting(), changeReview() (+48 more)

### Community 6 - "totalseg_stats.py"
Cohesion: 0.14
Nodes (21): _binary(), compact_organs(), _compact_stats(), _device(), _dicom_files(), format_volume(), group_series(), _is_skip_desc() (+13 more)

### Community 7 - "oncometra.py"
Cohesion: 0.12
Nodes (40): add_user(), adjudicate(), Assign, assignment_payload(), audit(), begin_local_import(), BootstrapUser, boundaries() (+32 more)

### Community 8 - "oncometra.js"
Cohesion: 0.13
Nodes (40): action(), addUser(), api(), assignReader(), badge(), boot(), browseDataset(), browsePosition() (+32 more)

### Community 9 - "test_oncometra.py"
Cohesion: 0.14
Nodes (20): assigned(), clients(), complete(), fixture_case(), isolated_login_limits(), test_add_lesion_then_delete_it_keeps_the_connection(), test_adjudication_preserves_source_and_comparison(), test_configurable_features_require_current_approval() (+12 more)

### Community 10 - "platform_api.py"
Cohesion: 0.13
Nodes (15): CatalogImport, CohortImport, CohortRecord, DatasetFields, DatasetInput, DatasetUpdate, DiscoveryRequest, Evidence (+7 more)

### Community 11 - "build_router"
Cohesion: 0.11
Nodes (39): audit_log(), local_catalog(), local_import_status(), ProjectDataset, WorkspaceProject, overview(), _remember_seg_status(), require_admin() (+31 more)

### Community 13 - "test_platform.py"
Cohesion: 0.10
Nodes (28): loop(), run_once(), CatalogDataset, CatalogJob, CatalogPatientIndex, WorkspaceAssignment, WorkspaceAudit, _job() (+20 more)

### Community 14 - "imaging.py"
Cohesion: 0.15
Nodes (22): bulk_upload_dicom_folder(), create_study(), load_upload(), update_mask_slice(), preserve_series(), stage_dicom_inputs(), create_empty_mask(), decode_mask_png_b64() (+14 more)

### Community 15 - "ViewerFullscreen"
Cohesion: 0.12
Nodes (4): PLANE_AXES, UndoQueue, ViewerFullscreen, fixture()

### Community 16 - "os"
Cohesion: 0.17
Nodes (6): _database_url(), _default_database_url(), get_db(), main(), IntegrationService, _data_root()

### Community 17 - "get_slice"
Cohesion: 0.40
Nodes (4): get_slice(), _plane_size(), _plane_spacing_mm(), _slice_plane()

### Community 18 - "platformWorkspace"
Cohesion: 0.17
Nodes (17): platformWorkspace(), accessLabel(), bindDetailTabs(), datasetRows(), datasetSheet(), downloadJson(), editDataset(), fact() (+9 more)

### Community 20 - "AI-Native Cloud PACS/RIS Blueprint"
Cohesion: 0.17
Nodes (12): AI-Native Cloud PACS/RIS Blueprint, Clinical Artifact Strategy For AI Outputs, Core User Experience, Immediate Next Steps For This Repo, Measurements And Structured Findings, Product Thesis, Report Assistance, Security, Compliance, And Governance Requirements (+4 more)

### Community 21 - "main.py"
Cohesion: 0.09
Nodes (26): init_db(), stop_jobs(), AiTaskRunRequest, AppointmentRequest, BillingItemRequest, _bulk_accession(), create_billing_item(), create_measurement() (+18 more)

### Community 22 - "Oncometra Imaging Workspace"
Cohesion: 0.18
Nodes (11): API overview, CT Early Response Web App (Prototype), Data format, Dictation, Existing Annotation Demo, Important, Legacy Prototype Reference, Notes for production hardening (+3 more)

### Community 25 - "MVP Scaffold"
Cohesion: 0.22
Nodes (8): AI Task Types, Best Next Build Steps, Environment Variables, Imaging + Workflow APIs, Integration Scaffolding, MVP Scaffold, What Exists Now, What Is Still Scaffold-Level

### Community 26 - "Recommended Platform Decomposition"
Cohesion: 0.25
Nodes (8): 1. Imaging Archive Layer, 2. Worklist and Metadata Service, 3. Embedded Viewer Workspace, 4. Reporting Service, 5. AI Registry and Orchestrator, 6. Fine-Tuning and Evaluation Layer, 7. EHR / RIS Integration Gateway, Recommended Platform Decomposition

### Community 27 - "static/import-files.mjs"
Cohesion: 0.38
Nodes (6): classifyFiles(), collectDirectoryEntries(), visit(), hiddenPath(), MAX_BYTES, MAX_FILES

### Community 28 - "Oncometra Demonstration"
Cohesion: 0.29
Nodes (7): Annotation, Approved Feature Files, Demonstration Workflow, Oncometra Demonstration, Run Locally, Scope Boundaries, Verification

### Community 29 - "mask-editing.mjs"
Cohesion: 0.40
Nodes (3): DIAMETER_PRESETS, normalizeDiameter(), strokeSpec()

### Community 31 - "OncoRadar integration decisions"
Cohesion: 0.33
Nodes (6): Module boundaries, OncoRadar integration decisions, Production work still required, Source baselines, Take, adapt, replace, Unified clinical workflow

### Community 32 - "Running the unified workspace"
Cohesion: 0.33
Nodes (5): Bring in OncoRadar metadata, Cohort manifest contract, Local run, Running the unified workspace, Verification

### Community 33 - "demo_admin.py"
Cohesion: 0.21
Nodes (5): fetch_catalog(), main(), private_file(), replace_private_file(), test_discovery_keeps_unknown_fields_and_rejects_unexpected_payload()

### Community 34 - "nodule-controls.mjs"
Cohesion: 0.60
Nodes (3): jobNoduleLabel(), proposalIsCurrent(), selectedNodule()

### Community 35 - "MVP Build Sequence"
Cohesion: 0.40
Nodes (5): MVP Build Sequence, Phase 1: Reading Workspace, Phase 2: AI-Native Reporting, Phase 3: EHR Integration, Phase 4: Local Fine-Tuning

### Community 38 - "Local Hosting And Deployment Modes"
Cohesion: 0.50
Nodes (4): Cloud-Hosted, Fully Local, Hybrid, Local Hosting And Deployment Modes

### Community 42 - "json"
Cohesion: 0.19
Nodes (6): demo_case_keys(), import_demo_cases(), FeatureSettings, index_archive(), prepare(), read_range()

### Community 47 - "pathlib"
Cohesion: 0.19
Nodes (5): export_case_files(), sha256(), write_slicer_mask(), copy_upload_to_tmp(), summarize_nodules()

### Community 48 - "sync_oncoradar"
Cohesion: 0.16
Nodes (9): apply_imported_rights(), import_catalog(), sync_oncoradar(), normalize_oncoradar(), oncoradar_access(), oncoradar_commercial(), apply_imaging_index(), dataset_profile() (+1 more)

### Community 50 - "seed_demo"
Cohesion: 0.33
Nodes (5): lifespan(), password_hash(), seed_demo(), _storage_path(), test_bootstrap_account_survives_restart_without_resetting_existing_user()

### Community 51 - "platform_services.py"
Cohesion: 0.21
Nodes (7): import_images(), CaseSourceLink, CohortItem, import_cohort(), ensure_imaging_index_schema(), prepare_import_link(), validate_cohort_identity()

## Knowledge Gaps
- **73 isolated node(s):** `state`, `views`, `undoQueue`, `STATUS_LABELS`, `WINDOW_PRESETS` (+68 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 203 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Suggested Domain Model` connect `WorkflowService` to `lung_api.py`, `AI-Native Cloud PACS/RIS Blueprint`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `WorkflowService` (e.g. with `AiArtifact` and `AiTask`) actually correct?**
  _`WorkflowService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `state`, `views`, `undoQueue` to the rest of the system?**
  _73 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `simpleitk` be split into smaller, more focused modules?**
  _Cohesion score 0.0638148667601683 - nodes in this community are weakly interconnected._
- **Why does `AI-Native Cloud PACS/RIS Blueprint` connect `AI-Native Cloud PACS/RIS Blueprint` to `WorkflowService`, `MVP Build Sequence`, `Local Hosting And Deployment Modes`, `Recommended Platform Decomposition`, `README.md`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `build_router()` (e.g. with `CaseSourceLink` and `CatalogDataset`) actually correct?**
  _`build_router()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `lung_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08475247524752476 - nodes in this community are weakly interconnected._