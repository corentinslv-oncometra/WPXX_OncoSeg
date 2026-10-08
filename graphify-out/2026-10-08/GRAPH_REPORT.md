# Graph Report - WPXX_OncoSeg  (2026-10-08)

## Corpus Check
- 67 files · ~56,856 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 20 file(s) not represented in the graph (top: .gz 10, .css 4, (none) 3)

## Summary
- 982 nodes · 3123 edges · 42 communities (33 shown, 9 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 200 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3a0e71f1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_platform.py
- lung_api.py
- WorkflowService
- numpy
- app.js
- annotate.js
- totalseg_stats.py
- oncometra.py
- oncometra.js
- get
- simpleitk
- build_router
- main.py
- platform_services.py
- platform_api.py
- ViewerFullscreen
- pathlib
- manifest.json
- platformWorkspace
- StudyStore
- AI-Native Cloud PACS/RIS Blueprint
- get_slice
- Oncometra Imaging Workspace
- Login
- speech_to_text.py
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

## God Nodes (most connected - your core abstractions)
1. `WorkflowService` - 47 edges
2. `build_router()` - 45 edges
3. `get()` - 39 edges
4. `start_job()` - 25 edges
5. `audit()` - 25 edges
6. `updateControls()` - 25 edges
7. `study_head()` - 23 edges
8. `retire_seeded_demo_cases()` - 23 edges
9. `require_admin()` - 22 edges
10. `openCase()` - 21 edges

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

## Communities (42 total, 9 thin omitted)

### Community 0 - "test_platform.py"
Cohesion: 0.05
Nodes (53): fetch_catalog(), loop(), run_once(), image_directory(), import_demo_cases(), main(), CatalogJob, password_hash() (+45 more)

### Community 1 - "lung_api.py"
Cohesion: 0.10
Nodes (66): accept_job(), _acquire_worker_lock(), add_nodule(), annotation_state(), approve_case(), cancel_job(), check_editable(), check_version() (+58 more)

### Community 2 - "WorkflowService"
Cohesion: 0.10
Nodes (24): _database_url(), _default_database_url(), get_db(), init_db(), AiArtifact, AiTask, AnnotationHead, AnnotationReviewEvent (+16 more)

### Community 3 - "numpy"
Cohesion: 0.07
Nodes (32): execute_job(), export_case_files(), sha256(), write_slicer_mask(), FeatureSettings, crop_for_prompt(), image_for_plane(), mask_from_plane() (+24 more)

### Community 4 - "app.js"
Cohesion: 0.07
Nodes (65): api(), applyViewerLayout(), applyZoom(), bootstrap(), canvasPointToImage(), comparisonAvailable(), displayCtx, drawBrushStroke() (+57 more)

### Community 5 - "annotate.js"
Cohesion: 0.11
Nodes (60): activeNodule(), addNodule(), api(), axes(), base(), cancelPendingPoint(), changeEditSetting(), changeReview() (+52 more)

### Community 6 - "totalseg_stats.py"
Cohesion: 0.10
Nodes (34): CatalogDataset, CatalogPatientIndex, _totalseg_payload(), totalseg_start(), _job(), _binary(), compact_organs(), _compact_stats() (+26 more)

### Community 7 - "oncometra.py"
Cohesion: 0.14
Nodes (34): add_user(), adjudicate(), Assign, assignment_payload(), BootstrapUser, can_review(), change_user_role(), compare() (+26 more)

### Community 8 - "oncometra.js"
Cohesion: 0.17
Nodes (32): action(), addUser(), api(), assignReader(), badge(), boot(), compareReadings(), escape() (+24 more)

### Community 9 - "get"
Cohesion: 0.15
Nodes (31): auto_segment(), AutoSegmentRequest, create_measurement(), create_schedule_item(), create_training_run(), get_report(), get_study(), get_workspace() (+23 more)

### Community 10 - "simpleitk"
Cohesion: 0.18
Nodes (19): bulk_upload_dicom_folder(), create_study(), load_upload(), update_mask_slice(), preserve_series(), stage_dicom_inputs(), copy_upload_to_tmp(), create_empty_mask() (+11 more)

### Community 11 - "build_router"
Cohesion: 0.15
Nodes (31): audit(), audit_log(), ProjectDataset, require_admin(), require_project(), build_router(), catalog(), cohort() (+23 more)

### Community 12 - "main.py"
Cohesion: 0.11
Nodes (20): AiTaskRunRequest, AppointmentRequest, BillingItemRequest, _bulk_accession(), create_billing_item(), download_original_dicom(), lung_workspace(), MaskSliceUpdateRequest (+12 more)

### Community 13 - "platform_services.py"
Cohesion: 0.14
Nodes (12): import_images(), CaseSourceLink, CohortItem, WorkspaceAudit, WorkspaceProject, WorkspaceUser, import_cohort(), dataset_profile() (+4 more)

### Community 14 - "platform_api.py"
Cohesion: 0.15
Nodes (15): CatalogImport, CohortImport, CohortRecord, DatasetFields, DatasetInput, DatasetUpdate, DiscoveryRequest, Evidence (+7 more)

### Community 15 - "ViewerFullscreen"
Cohesion: 0.12
Nodes (4): PLANE_AXES, UndoQueue, ViewerFullscreen, fixture()

### Community 16 - "pathlib"
Cohesion: 0.13
Nodes (4): RadiomicsExample, RadiomicsModel, SeedPoint, Segmenter

### Community 17 - "manifest.json"
Cohesion: 0.10
Nodes (19): checkpoint_sha256, checkpoint_source, clinical_validation, conversion_max_absolute_error, decoder, encoder, files, decoder.onnx (+11 more)

### Community 18 - "platformWorkspace"
Cohesion: 0.19
Nodes (14): platformWorkspace(), accessLabel(), bindDetailTabs(), datasetSheet(), downloadJson(), editDataset(), fact(), importJson() (+6 more)

### Community 20 - "AI-Native Cloud PACS/RIS Blueprint"
Cohesion: 0.17
Nodes (12): AI-Native Cloud PACS/RIS Blueprint, Clinical Artifact Strategy For AI Outputs, Core User Experience, Immediate Next Steps For This Repo, Measurements And Structured Findings, Product Thesis, Report Assistance, Security, Compliance, And Governance Requirements (+4 more)

### Community 21 - "get_slice"
Cohesion: 0.24
Nodes (8): get_slice(), _plane_size(), _plane_spacing_mm(), _slice_plane(), decode_mask_png_b64(), make_png_base64(), normalize_ct_slice(), normalize_image_slice()

### Community 22 - "Oncometra Imaging Workspace"
Cohesion: 0.18
Nodes (11): API overview, CT Early Response Web App (Prototype), Data format, Dictation, Existing Annotation Demo, Important, Legacy Prototype Reference, Notes for production hardening (+3 more)

### Community 23 - "Login"
Cohesion: 0.31
Nodes (6): boundaries(), current_user(), digest(), Login, logout(), WorkspaceSession

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
Nodes (7): Approved Feature Files, Demonstration Workflow, MedSAM, Oncometra Demonstration, Run Locally, Scope Boundaries, Verification

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
- **91 isolated node(s):** `state`, `views`, `undoQueue`, `STATUS_LABELS`, `WINDOW_PRESETS` (+86 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 206 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AI-Native Cloud PACS/RIS Blueprint` connect `AI-Native Cloud PACS/RIS Blueprint` to `WorkflowService`, `MVP Build Sequence`, `Local Hosting And Deployment Modes`, `Recommended Platform Decomposition`, `README.md`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `WorkflowService` (e.g. with `AiArtifact` and `AiTask`) actually correct?**
  _`WorkflowService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `state`, `views`, `undoQueue` to the rest of the system?**
  _91 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_platform.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05444978265843056 - nodes in this community are weakly interconnected._
- **Why does `Suggested Domain Model` connect `WorkflowService` to `AI-Native Cloud PACS/RIS Blueprint`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `build_router()` (e.g. with `CaseSourceLink` and `CatalogDataset`) actually correct?**
  _`build_router()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `lung_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1002710027100271 - nodes in this community are weakly interconnected._