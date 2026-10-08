# Graph Report - WPXX_OncoSeg  (2026-10-08)

## Corpus Check
- 58 files · ~52,472 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 17 file(s) not represented in the graph (top: .gz 10, .css 4, (none) 2)

## Summary
- 922 nodes · 2904 edges · 47 communities (31 shown, 16 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 197 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3a0e71f1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_platform.py
- lung_api.py
- WorkflowService
- simpleitk
- app.js
- annotate.js
- totalseg_stats.py
- oncometra.py
- oncometra.js
- get
- imaging.py
- build_router
- main.py
- platform_services.py
- platform_api.py
- ViewerFullscreen
- radiomics.py
- bulk_upload_dicom_folder
- platformWorkspace
- StudyStore
- AI-Native Cloud PACS/RIS Blueprint
- feature_protocol.py
- Oncometra Imaging Workspace
- seed_demo
- SpeechToTextNotConfigured
- MVP Scaffold
- Recommended Platform Decomposition
- static/import-files.mjs
- Oncometra Demonstration
- mask-editing.mjs
- README.md
- OncoRadar integration decisions
- Running the unified workspace
- integrations.py
- nodule-controls.mjs
- MVP Build Sequence
- not_found_handler
- annotation-workflow.mjs
- Local Hosting And Deployment Modes
- Segmenter

## God Nodes (most connected - your core abstractions)
1. `WorkflowService` - 47 edges
2. `build_router()` - 45 edges
3. `get()` - 39 edges
4. `audit()` - 25 edges
5. `study_head()` - 23 edges
6. `retire_seeded_demo_cases()` - 23 edges
7. `start_job()` - 22 edges
8. `require_admin()` - 22 edges
9. `image_for()` - 20 edges
10. `annotation_state()` - 20 edges

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

## Communities (47 total, 16 thin omitted)

### Community 0 - "test_platform.py"
Cohesion: 0.08
Nodes (39): fetch_catalog(), loop(), run_once(), _uuid(), CatalogJob, normalize_oncoradar(), upsert_discovery(), assigned() (+31 more)

### Community 1 - "lung_api.py"
Cohesion: 0.13
Nodes (60): accept_job(), _acquire_worker_lock(), add_nodule(), annotation_state(), approve_case(), cancel_job(), check_editable(), check_version() (+52 more)

### Community 2 - "WorkflowService"
Cohesion: 0.10
Nodes (21): get_db(), init_db(), AiArtifact, AiTask, AnnotationHead, AnnotationReviewEvent, AnnotationTaskEvent, Appointment (+13 more)

### Community 3 - "simpleitk"
Cohesion: 0.07
Nodes (28): _database_url(), _default_database_url(), execute_job(), _extract_features(), main(), _decode(), read_oncoradar(), export_case_files() (+20 more)

### Community 4 - "app.js"
Cohesion: 0.07
Nodes (65): api(), applyViewerLayout(), applyZoom(), bootstrap(), canvasPointToImage(), comparisonAvailable(), displayCtx, drawBrushStroke() (+57 more)

### Community 5 - "annotate.js"
Cohesion: 0.11
Nodes (56): activeNodule(), addNodule(), api(), axes(), base(), cancelPendingPoint(), changeEditSetting(), changeReview() (+48 more)

### Community 6 - "totalseg_stats.py"
Cohesion: 0.11
Nodes (29): CatalogDataset, CatalogPatientIndex, _job(), _binary(), compact_organs(), _compact_stats(), _detail(), _device() (+21 more)

### Community 7 - "oncometra.py"
Cohesion: 0.16
Nodes (31): adjudicate(), Assign, assignment_payload(), can_review(), compare(), Comparison, create_assignment(), extract_features() (+23 more)

### Community 8 - "oncometra.js"
Cohesion: 0.17
Nodes (31): action(), addUser(), api(), assignReader(), badge(), boot(), compareReadings(), escape() (+23 more)

### Community 9 - "get"
Cohesion: 0.18
Nodes (23): get_report(), get_study(), get_workspace(), healthz(), list_ai_tasks(), list_billing(), list_integrations(), list_measurements() (+15 more)

### Community 10 - "imaging.py"
Cohesion: 0.16
Nodes (20): get_slice(), MaskSliceUpdateRequest, _plane_size(), _plane_spacing_mm(), _slice_plane(), update_mask_slice(), decode_mask_png_b64(), discover_dicom_series() (+12 more)

### Community 11 - "build_router"
Cohesion: 0.14
Nodes (34): audit(), audit_log(), ProjectDataset, require_admin(), require_project(), build_router(), catalog(), cohort() (+26 more)

### Community 12 - "main.py"
Cohesion: 0.11
Nodes (25): stop_jobs(), AiTaskRunRequest, AppointmentRequest, auto_segment(), AutoSegmentRequest, BillingItemRequest, create_billing_item(), create_measurement() (+17 more)

### Community 13 - "platform_services.py"
Cohesion: 0.15
Nodes (12): import_images(), CaseSourceLink, CohortItem, WorkspaceAudit, WorkspaceProject, WorkspaceSession, import_cohort(), dataset_profile() (+4 more)

### Community 14 - "platform_api.py"
Cohesion: 0.14
Nodes (15): CatalogImport, CohortImport, CohortRecord, DatasetFields, DatasetInput, DatasetUpdate, DiscoveryRequest, Evidence (+7 more)

### Community 15 - "ViewerFullscreen"
Cohesion: 0.12
Nodes (4): PLANE_AXES, UndoQueue, ViewerFullscreen, fixture()

### Community 17 - "bulk_upload_dicom_folder"
Cohesion: 0.15
Nodes (11): _bulk_accession(), bulk_upload_dicom_folder(), create_study(), load_upload(), _parse_form_datetime(), _safe_upload_filename(), transcribe_audio(), preserve_series() (+3 more)

### Community 18 - "platformWorkspace"
Cohesion: 0.19
Nodes (14): platformWorkspace(), accessLabel(), bindDetailTabs(), datasetSheet(), downloadJson(), editDataset(), fact(), importJson() (+6 more)

### Community 20 - "AI-Native Cloud PACS/RIS Blueprint"
Cohesion: 0.17
Nodes (12): AI-Native Cloud PACS/RIS Blueprint, Clinical Artifact Strategy For AI Outputs, Core User Experience, Immediate Next Steps For This Repo, Measurements And Structured Findings, Product Thesis, Report Assistance, Security, Compliance, And Governance Requirements (+4 more)

### Community 22 - "Oncometra Imaging Workspace"
Cohesion: 0.18
Nodes (11): API overview, CT Early Response Web App (Prototype), Data format, Dictation, Existing Annotation Demo, Important, Legacy Prototype Reference, Notes for production hardening (+3 more)

### Community 23 - "seed_demo"
Cohesion: 0.12
Nodes (15): add_user(), BootstrapUser, boundaries(), change_user_role(), current_user(), digest(), Login, logout() (+7 more)

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

### Community 34 - "nodule-controls.mjs"
Cohesion: 0.60
Nodes (3): jobNoduleLabel(), proposalIsCurrent(), selectedNodule()

### Community 35 - "MVP Build Sequence"
Cohesion: 0.40
Nodes (5): MVP Build Sequence, Phase 1: Reading Workspace, Phase 2: AI-Native Reporting, Phase 3: EHR Integration, Phase 4: Local Fine-Tuning

### Community 38 - "Local Hosting And Deployment Modes"
Cohesion: 0.50
Nodes (4): Cloud-Hosted, Fully Local, Hybrid, Local Hosting And Deployment Modes

## Knowledge Gaps
- **74 isolated node(s):** `state`, `views`, `undoQueue`, `STATUS_LABELS`, `WINDOW_PRESETS` (+69 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 183 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AI-Native Cloud PACS/RIS Blueprint` connect `AI-Native Cloud PACS/RIS Blueprint` to `WorkflowService`, `MVP Build Sequence`, `Local Hosting And Deployment Modes`, `Recommended Platform Decomposition`, `README.md`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `WorkflowService` (e.g. with `AiArtifact` and `AiTask`) actually correct?**
  _`WorkflowService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `state`, `views`, `undoQueue` to the rest of the system?**
  _74 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_platform.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0777323202805377 - nodes in this community are weakly interconnected._
- **Why does `Suggested Domain Model` connect `WorkflowService` to `AI-Native Cloud PACS/RIS Blueprint`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `build_router()` (e.g. with `CaseSourceLink` and `CatalogDataset`) actually correct?**
  _`build_router()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `lung_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12712215320910972 - nodes in this community are weakly interconnected._