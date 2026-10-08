# Graph Report - WPXX_OncoSeg  (2026-10-08)

## Corpus Check
- 58 files · ~53,632 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 17 file(s) not represented in the graph (top: .gz 10, .css 4, (none) 2)

## Summary
- 935 nodes · 2934 edges · 37 communities (24 shown, 13 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 199 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dcc4ae3a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_platform.py
- lung_api.py
- WorkflowService
- app.js
- annotate.js
- totalseg_stats.py
- oncometra.py
- oncometra.js
- platform_api.py
- main.py
- ViewerFullscreen
- RadiomicsModel
- platformWorkspace
- StudyStore
- AI-Native Cloud PACS/RIS Blueprint
- Oncometra Imaging Workspace
- os
- MVP Scaffold
- Recommended Platform Decomposition
- static/import-files.mjs
- Oncometra Demonstration
- mask-editing.mjs
- README.md
- OncoRadar integration decisions
- Running the unified workspace
- nodule-controls.mjs
- MVP Build Sequence
- not_found_handler
- annotation-workflow.mjs
- Local Hosting And Deployment Modes

## God Nodes (most connected - your core abstractions)
1. `WorkflowService` - 47 edges
2. `build_router()` - 46 edges
3. `get()` - 39 edges
4. `audit()` - 26 edges
5. `study_head()` - 23 edges
6. `require_admin()` - 23 edges
7. `retire_seeded_demo_cases()` - 23 edges
8. `start_job()` - 22 edges
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

## Communities (37 total, 13 thin omitted)

### Community 0 - "test_platform.py"
Cohesion: 0.07
Nodes (48): fetch_catalog(), run_once(), feature_export(), image_directory(), import_demo_cases(), CatalogJob, CatalogPatientIndex, password_hash() (+40 more)

### Community 1 - "lung_api.py"
Cohesion: 0.10
Nodes (68): accept_job(), _acquire_worker_lock(), add_nodule(), annotation_state(), approve_case(), cancel_job(), check_editable(), check_version() (+60 more)

### Community 4 - "app.js"
Cohesion: 0.07
Nodes (65): api(), applyViewerLayout(), applyZoom(), bootstrap(), canvasPointToImage(), comparisonAvailable(), displayCtx, drawBrushStroke() (+57 more)

### Community 5 - "annotate.js"
Cohesion: 0.11
Nodes (56): activeNodule(), addNodule(), api(), axes(), base(), cancelPendingPoint(), changeEditSetting(), changeReview() (+48 more)

### Community 6 - "totalseg_stats.py"
Cohesion: 0.13
Nodes (26): _job(), _binary(), compact_organs(), _compact_stats(), _detail(), _device(), _dicom_files(), execute() (+18 more)

### Community 7 - "oncometra.py"
Cohesion: 0.06
Nodes (72): loop(), get_db(), AiArtifact, AiTask, AnnotationHead, AnnotationReviewEvent, AnnotationTaskEvent, Appointment (+64 more)

### Community 8 - "oncometra.js"
Cohesion: 0.15
Nodes (33): action(), addUser(), api(), assignReader(), badge(), boot(), cohortGaps(), cohortProjects() (+25 more)

### Community 11 - "platform_api.py"
Cohesion: 0.07
Nodes (55): audit(), require_admin(), require_project(), apply_imported_rights(), build_router(), catalog(), cohort(), create_dataset() (+47 more)

### Community 12 - "main.py"
Cohesion: 0.05
Nodes (86): init_db(), AiTaskRunRequest, AppointmentRequest, auto_segment(), AutoSegmentRequest, BillingItemRequest, _bulk_accession(), bulk_upload_dicom_folder() (+78 more)

### Community 15 - "ViewerFullscreen"
Cohesion: 0.12
Nodes (4): PLANE_AXES, UndoQueue, ViewerFullscreen, fixture()

### Community 18 - "platformWorkspace"
Cohesion: 0.17
Nodes (17): platformWorkspace(), accessLabel(), bindDetailTabs(), datasetRows(), datasetSheet(), downloadJson(), editDataset(), fact() (+9 more)

### Community 20 - "AI-Native Cloud PACS/RIS Blueprint"
Cohesion: 0.17
Nodes (12): AI-Native Cloud PACS/RIS Blueprint, Clinical Artifact Strategy For AI Outputs, Core User Experience, Immediate Next Steps For This Repo, Measurements And Structured Findings, Product Thesis, Report Assistance, Security, Compliance, And Governance Requirements (+4 more)

### Community 22 - "Oncometra Imaging Workspace"
Cohesion: 0.18
Nodes (11): API overview, CT Early Response Web App (Prototype), Data format, Dictation, Existing Annotation Demo, Important, Legacy Prototype Reference, Notes for production hardening (+3 more)

### Community 24 - "os"
Cohesion: 0.06
Nodes (21): _database_url(), _default_database_url(), main(), _decode(), read_oncoradar(), IntegrationService, crop_for_prompt(), image_for_plane() (+13 more)

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
- **73 isolated node(s):** `state`, `views`, `undoQueue`, `STATUS_LABELS`, `WINDOW_PRESETS` (+68 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 185 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AI-Native Cloud PACS/RIS Blueprint` connect `AI-Native Cloud PACS/RIS Blueprint` to `MVP Build Sequence`, `Local Hosting And Deployment Modes`, `oncometra.py`, `Recommended Platform Decomposition`, `README.md`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `WorkflowService` (e.g. with `AiArtifact` and `AiTask`) actually correct?**
  _`WorkflowService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `state`, `views`, `undoQueue` to the rest of the system?**
  _73 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_platform.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06582952815829528 - nodes in this community are weakly interconnected._
- **Why does `Suggested Domain Model` connect `oncometra.py` to `AI-Native Cloud PACS/RIS Blueprint`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `build_router()` (e.g. with `CaseSourceLink` and `CatalogDataset`) actually correct?**
  _`build_router()` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Should `lung_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1004995592124596 - nodes in this community are weakly interconnected._