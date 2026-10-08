export function platformWorkspace({state, api, escape, showModal, action, toast, refresh, importImages}) {
  const $ = id => document.getElementById(id);
  const catalog = {page: 1, query: '', modality: '', scope: 'eligible', items: []};
  const useLabel = {unknown: 'licence inconnue', permitted: 'usage commercial permis', noncommercial: 'non commercial', permission_required: 'permission requise'};
  const accessText = {unknown: 'accès inconnu', direct: 'accès ouvert', login: 'connexion requise', account: 'compte requis', request: 'permission requise'};
  let poll;
  function scheduleRefresh() {
    poll = setTimeout(() => {
      if (state.tab !== 'datasets') return;
      if ($('modal').open || document.activeElement?.closest('#catalog-search')) return scheduleRefresh();
      action(renderDatasets)();
    }, 4000);
  }
  const options = (values, selected = '') => values.map(([value, label]) => `<option value="${escape(value)}" ${value === selected ? 'selected' : ''}>${escape(label)}</option>`).join('');
  const yesNo = value => options([['', 'Unknown'], ['true', 'Yes'], ['false', 'No']], value == null ? '' : String(value));
  const split = value => value.split(',').map(s => s.trim()).filter(Boolean);
  const field = (label, name, value = '', extra = '') => `<label class="form-label">${label}<input name="${name}" value="${escape(value)}" ${extra}></label>`;
  const tri = value => value == null ? 'Unknown' : value ? 'Yes' : 'No';
  const projectOptions = () => state.data.projects.map(p => `<option value="${p.id}">${escape(p.name)} / ${p.modality}</option>`).join('');

  async function renderDatasets() {
    clearTimeout(poll);
    const result = await api(`/api/catalog?page=${catalog.page}&q=${encodeURIComponent(catalog.query)}&modality=${catalog.modality}&scope=${catalog.scope}`);
    catalog.items = result.items;
    if (state.tab !== 'datasets') return;
    const empty = catalog.scope === 'eligible'
      ? '<div class="empty"><h2>Aucune fiche ouverte avec usage commercial permis</h2><p>Passez le filtre sur toutes les fiches pour voir le reste : licence inconnue, non commerciale, ou permission requise.</p></div>'
      : '<div class="empty"><h2>Aucune fiche</h2><p>Aucune fiche du catalogue ne correspond à cette recherche.</p></div>';
    $('content').innerHTML = `<div class="page-heading"><div><h1>Datasets exploitables</h1><p>Fiches OncoRadar ouvertes, avec un usage commercial permis. Le reste du catalogue est derrière le filtre.</p></div></div>
      <section class="table-panel"><form id="catalog-search" class="filters"><input name="q" aria-label="Chercher une fiche" placeholder="Chercher une fiche" value="${escape(catalog.query)}"><select name="modality" aria-label="Modalité">${options([['', 'Toutes les modalités'], ['CT', 'CT'], ['MR', 'IRM']], catalog.modality)}</select><select name="scope" aria-label="Filtre de licence">${options([['eligible', 'Usage commercial permis, accès ouvert'], ['all', 'Toutes les fiches']], catalog.scope)}</select><button>Filtrer</button><span class="small-note">${result.total} fiches</span></form>
      <div class="table-scroll"><table><thead><tr><th>Dataset</th><th>Cancer / imagerie</th><th>Accès / licence</th><th></th></tr></thead><tbody>${result.items.map(row => `<tr><td><strong><a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">${escape(row.name)}</a></strong><small>${escape(row.registry)}</small></td><td>${escape(row.tumor_types.join(', ') || 'Non précisé')}<small>${escape(row.modalities.join(', ') || 'Modalité non vérifiée')}</small></td><td>${escape(accessText[row.access] || row.access)}<small>${escape(row.license_name)} / ${escape(useLabel[row.commercial_use] || row.commercial_use)}</small></td><td><div class="row-actions"><button class="primary" data-platform-action="use-dataset" data-id="${row.id}">Utiliser ce dataset</button></div></td></tr>`).join('')}</tbody></table></div>
      ${result.items.length ? '' : empty}
      <div class="catalog-pagination"><button data-platform-action="previous" ${catalog.page === 1 ? 'disabled' : ''}>Précédent</button><span>Page ${catalog.page} / ${Math.max(1, Math.ceil(result.total / 50))}</span><button data-platform-action="next" ${catalog.page * 50 >= result.total ? 'disabled' : ''}>Suivant</button></div></section>
      <p class="small-note">La première page ne montre que les fiches en accès ouvert dont l’usage commercial est permis. Unknown, non commercial et permission requise restent accessibles via le filtre.</p>`;
    $('catalog-search').onsubmit = action(async event => {
      event.preventDefault(); const data = new FormData(event.target);
      catalog.query = data.get('q'); catalog.modality = data.get('modality'); catalog.scope = data.get('scope') || 'eligible'; catalog.page = 1;
      await renderDatasets();
    });
  }

  const ACCESS_LABELS = ['Direct download', 'Login required', 'Account required', 'Request access'];
  const REGISTRY_OPEN = {
    IDC: 'Direct download', TCIA: 'Account required', OpenNeuro: 'Account required', 'ISIC Archive': 'Account required',
    Zenodo: 'Direct download', MSD: 'Direct download', 'Hugging Face': 'Direct download', 'Grand Challenge': 'Account required',
    GDC: 'Request access', HTAN: 'Request access',
  };
  const REGISTRY_MIXED = {
    TCIA: 'Request access', GDC: 'Request access', HTAN: 'Request access', 'Hugging Face': 'Request access',
    IDC: 'Request access', 'ISIC Archive': 'Account required', OpenNeuro: 'Account required', Zenodo: 'Direct download',
  };
  const CURATED_ACCESS = {direct: 'Direct download', login: 'Login required', account: 'Account required', request: 'Request access'};
  const declared = value => value === true || value === 1 || value === '1';
  const sourceHost = url => { try { return new URL(url).host; } catch { return url; } };
  const countLabel = value => {
    if (value == null || value === '') return '';
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('en-US') : String(value);
  };
  function accessLabel(value, registry) {
    const text = String(value || '').trim();
    if (!text || text === 'unknown') return '';
    if (ACCESS_LABELS.includes(text)) return text;
    if (CURATED_ACCESS[text]) return CURATED_ACCESS[text];
    const lowered = text.toLowerCase();
    const wording = [
      [['direct download', 'download directly', 'downloadable', 'publicly available', 'open access', 'freely available'], 'Direct download'],
      [['login', 'log in', 'sign in', 'credentials', 'authentication'], 'Login required'],
      [['account', 'register', 'create an account', 'signup', 'sign up'], 'Account required'],
      [['request access', 'access request', 'apply', 'approval', 'email', 'contact', 'by request'], 'Request access'],
    ].find(([tokens]) => tokens.some(token => lowered.includes(token)));
    if (wording) return wording[1];
    const code = text.replace(/\u00a0/g, ' ').replace(/[–—]/g, '-').replace(/[·.]/g, ' ').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
    if (code.includes('gated') || code.includes('restricted')) return 'Request access';
    if (code.includes('mixed')) return REGISTRY_MIXED[registry] || 'Request access';
    if (code === 'open' || code === 'mostly open' || code.startsWith('open ')) return REGISTRY_OPEN[registry] || '';
    return '';
  }
  function fact(label, value, empty = 'Not provided') {
    const missing = value == null || value === '' || (Array.isArray(value) && !value.length);
    const text = missing ? empty : Array.isArray(value) ? value.join(', ') : String(value);
    return `<div><dt>${escape(label)}</dt><dd>${missing ? `<span class="ds-unknown">${escape(empty)}</span>` : escape(text)}</dd></div>`;
  }
  function pageNotes(row) {
    const notes = row.profile?.notes;
    if (Array.isArray(notes)) return notes.map(item => String(item).trim()).filter(Boolean);
    if (typeof notes === 'string' && notes.trim()) return [notes.trim()];
    return String(row.notes || '').split('\n').map(item => item.trim()).filter(Boolean);
  }
  function datasetSheet(row) {
    const profile = row.profile || {};
    const domain = profile.domain || '';
    const access = accessLabel(profile.access || row.access, row.registry);
    const downloaded = declared(profile.dl_on != null ? profile.dl_on : row.dicom_ready);
    const integrated = declared(profile.integ_on);
    const longitudinal = declared(profile.longitudinal != null ? profile.longitudinal : row.longitudinal);
    const modalities = profile.modalities?.length ? profile.modalities : row.modalities;
    const tumor = row.tumor_detail || row.tumor_types.join(', ');
    const notes = pageNotes(row);
    const chip = name => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const declaration = (label, on, date) => `<article class="ds-declaration-card"><p class="ds-declaration-readout"><strong>${label}</strong><span class="ds-declaration-answer ${on ? 'is-yes' : 'is-no'}">${on ? 'Yes' : 'No'}</span></p><p>${date ? `Declared on <time datetime="${escape(date)}">${escape(date)}</time>.` : 'No declaration date.'}</p>${label === 'Downloaded' && row.dicom_path ? `<p>Local folder: ${escape(row.dicom_path)}</p>` : ''}</article>`;
    return `<div class="ds-detail">
      <p class="ds-kicker">${escape(row.registry)}${profile.trial ? ` · ${escape(profile.trial)}` : ''}</p>
      <div class="ds-drawer-tags">
        <span class="ds-chip${domain ? ` ds-chip-${chip(domain)}` : ''}">${escape(domain || 'Domain not provided')}</span>
        ${profile.sub ? `<span class="ds-chip">${escape(profile.sub)}</span>` : ''}
        ${access ? `<span class="ds-chip ds-chip-on">Access: ${escape(access)}</span>` : ''}
        ${domain === 'Oncology' && declared(profile.survival) && longitudinal ? '<span class="ds-chip ds-chip-on">Valuable</span>' : ''}
      </div>
      ${row.url ? `<p class="ds-toolbar"><a class="ds-open" href="${escape(row.url)}" target="_blank" rel="noreferrer">Open source <span aria-hidden="true">↗</span></a></p>` : ''}
      <nav class="ds-detail-tabs" aria-label="Dataset details" role="tablist">
        <button type="button" class="ds-detail-tab is-active" role="tab" aria-selected="true" data-detail-tab="identity">Identity and source</button>
        <button type="button" class="ds-detail-tab" role="tab" aria-selected="false" tabindex="-1" data-detail-tab="content">Described scientific content</button>
        <button type="button" class="ds-detail-tab" role="tab" aria-selected="false" tabindex="-1" data-detail-tab="page">From the page</button>
      </nav>
      <div class="ds-detail-panel is-active" data-detail-panel="identity">
        <section class="ds-detail-section"><h3>Identity and source</h3><dl class="ds-facts">
          ${fact('Stable dataset ID', row.external_id)}
          ${fact('Source', row.registry)}
          <div><dt>Source page</dt><dd>${row.url ? `<a href="${escape(row.url)}" target="_blank" rel="noreferrer">${escape(sourceHost(row.url))}</a>` : '<span class="ds-unknown">Not provided</span>'}</dd></div>
          ${fact('Trial or study identifier', profile.trial)}
          ${fact('Domain', domain)}
          ${fact('Sub-category', profile.sub)}
        </dl></section>
      </div>
      <div class="ds-detail-panel" data-detail-panel="content" hidden>
        <section class="ds-detail-section"><h3>Described scientific content</h3><dl class="ds-facts">
          ${fact('Tumor or disease', tumor)}
          ${fact('Histology or molecular subtype', profile.hist)}
          ${fact('Treatment context', profile.treatment)}
          ${fact('Modalities', modalities)}
          ${fact('Acquisition timepoints', profile.timepoints)}
          ${fact('Source-reported outcomes', profile.outcomes)}
        </dl></section>
        <section class="ds-detail-section"><h3>Counts and reported states</h3><dl class="ds-facts">
          ${fact('Source-reported patients', countLabel(profile.patient_count), 'Not reported')}
          ${fact('Source-reported segmented patients', countLabel(profile.seg), 'Not reported')}
          ${fact('Segmentation format', profile.seg_format)}
          ${fact('Survival on page', declared(profile.survival) ? 'Reported' : 'Not reported', 'Not reported')}
          ${fact('Survival in patients table', declared(profile.survival_clinical) ? 'Yes' : 'No', 'No')}
          ${fact('Longitudinal imaging', longitudinal ? 'Reported' : 'Not reported', 'Not reported')}
        </dl></section>
        <section class="ds-detail-section"><h3>Access and local declarations</h3><dl class="ds-facts">
          ${fact('Access statement', profile.access && profile.access !== 'unknown' ? profile.access : access)}
          ${fact('Usage license', profile.license || (row.license_name !== 'Unverified' ? row.license_name : ''))}
          ${fact('Commercial use', profile.commercial || (row.commercial_use !== 'unknown' ? row.commercial_use : ''))}
          ${fact('Source-reported update', profile.last_update, 'Not reported')}
          ${fact('Storage reference', row.dicom_path)}
        </dl>
        <div class="ds-declaration-grid">
          ${declaration('Downloaded', downloaded, profile.dl_date)}
          ${declaration('Integrated', integrated, profile.integ_date)}
        </div></section>
      </div>
      <div class="ds-detail-panel" data-detail-panel="page" hidden>
        ${notes.length ? `<section class="ds-notes"><h3>From the page</h3><p>Useful excerpts that do not fit the catalog fields. Copied verbatim.</p>${notes.map(note => `<blockquote>${escape(note)}</blockquote>`).join('')}</section>` : '<p class="ds-tab-empty">No page excerpts were copied.</p>'}
      </div>
    </div>`;
  }
  function bindDetailTabs(root) {
    root.querySelectorAll('[data-detail-tab]').forEach(button => {
      button.onclick = () => {
        const name = button.dataset.detailTab;
        root.querySelectorAll('[data-detail-tab]').forEach(item => {
          const selected = item.dataset.detailTab === name;
          item.classList.toggle('is-active', selected);
          item.setAttribute('aria-selected', selected ? 'true' : 'false');
          item.tabIndex = selected ? 0 : -1;
        });
        root.querySelectorAll('[data-detail-panel]').forEach(panel => { panel.hidden = panel.dataset.detailPanel !== name; });
      };
    });
  }

  function editDataset(row = null) {
    const value = row || {name: '', url: '', registry: 'Manual', tumor_types: [], modalities: [], access: 'unknown', commercial_use: 'unknown', license_name: 'Unverified', evidence: []};
    const form = `<form id="dataset-form"><div class="form-grid">${field('Dataset name', 'name', value.name, 'required maxlength="255"')}${field('Source / registry', 'registry', value.registry, row ? 'disabled' : 'required maxlength="80"')}</div>${field('Source URL', 'url', value.url, 'required type="url"')}
      <div class="form-grid">${field('Cancer of origin (comma-separated)', 'tumor_types', value.tumor_types.join(', '))}<label class="form-label">Imaging<select name="modalities">${options([['', 'Unverified'], ['CT', 'CT'], ['MR', 'MRI'], ['CT,MR', 'CT and MRI']], value.modalities.join(','))}</select></label></div>
      <div class="form-grid"><label class="form-label">Access<select name="access">${options([['unknown', 'Unverified'], ['direct', 'Direct download'], ['login', 'Login required'], ['account', 'Account required'], ['request', 'Request access']], value.access)}</select></label><label class="form-label">Commercial use<select name="commercial_use">${options([['unknown', 'Unverified'], ['permitted', 'Permitted (verified by curator)'], ['noncommercial', 'Non-commercial only'], ['permission_required', 'Permission required']], value.commercial_use)}</select></label></div>
      ${field('License / terms', 'license_name', value.license_name)}${field('License URL', 'license_url', value.license_url, 'type="url"')}
      <div class="form-grid"><label class="form-label">Longitudinal imaging<select name="longitudinal">${yesNo(value.longitudinal)}</select></label><label class="form-label">Segmentation labels<select name="segmentations">${yesNo(value.segmentations)}</select></label></div>
      ${row ? `<label class="form-label">Acquisition status<select name="status">${options([['identified', 'Identified'], ['contacted', 'Owners contacted'], ['access_requested', 'Access requested'], ['downloaded', 'Downloaded (declared)']], value.status)}</select></label>` : ''}
      <label class="form-label">Notes<textarea name="notes" rows="3" maxlength="10000">${escape(value.notes || '')}</textarea></label>
      <details><summary>Source evidence</summary><pre class="protocol">${escape(JSON.stringify(value.evidence, null, 2))}</pre>${field('Field supported by this evidence', 'evidence_field', '')}${field('Evidence URL', 'evidence_url', '', 'type="url"')}<label class="form-label">Quoted source text<textarea name="evidence_quote" rows="2" maxlength="2000"></textarea></label></details><p class="small-note">Curator edits are audited and protected against stale saves. Discovery refreshes never overwrite them.</p><button class="primary">Save dataset</button></form>`;
    showModal(row ? row.name : 'Add dataset', row ? `${datasetSheet(row)}<details class="ds-curator"><summary>Curator edits</summary>${form}</details>` : form);
    if (row) bindDetailTabs($('modal-body'));
    $('dataset-form').onsubmit = action(async event => {
      event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
      const evidence = [...value.evidence];
      if (data.evidence_quote) evidence.push({field: data.evidence_field, url: data.evidence_url, quote: data.evidence_quote});
      delete data.evidence_field; delete data.evidence_url; delete data.evidence_quote;
      data.evidence = evidence; data.tumor_types = split(data.tumor_types); data.modalities = split(data.modalities);
      for (const key of ['longitudinal', 'segmentations']) data[key] = data[key] === '' ? null : data[key] === 'true';
      if (row) data.version = row.version;
      await api(row ? `/api/catalog/${row.id}` : '/api/catalog', data, row ? 'PUT' : 'POST');
      $('modal').close(); await renderDatasets(); toast('Dataset saved.');
    });
  }

  let totalsegTimer;
  async function showTotalseg(row, page = 1) {
    clearTimeout(totalsegTimer);
    const result = await api(`/api/catalog/${row.id}/totalseg?page=${page}`);
    const visits = result.items.flatMap(item => item.visits.length ? item.visits.map(visit => ({patient: item.source_id, ...visit})) : [{patient: item.source_id, date: '', organs: '', lesion: '', quote: ''}]);
    showModal(`${row.name} / TotalSegmentator`, `<p class="small-note">Same pass as OncoRadar: task total for organs in the CT field of view, then lung nodules, liver lesions, or kidney cysts when those organs are present. The local DICOM folder is read in place.</p>
      <p class="small-note">${escape(result.dicom_path || 'No DICOM folder')}</p>
      <div class="row-actions"><button id="totalseg-run" class="primary" ${result.ready && result.installed && result.status !== 'running' ? '' : 'disabled'}>${result.status === 'running' ? 'Running…' : 'TotalSegmentator stats'}</button><button id="totalseg-stop" ${result.status === 'running' ? '' : 'disabled'}>Stop</button></div>
      <p class="small-note" id="totalseg-status">${escape(result.error || result.detail || (!result.ready ? 'The DICOM folder is missing on this machine.' : result.installed ? 'Not started.' : 'TotalSegmentator is not installed or not on PATH.'))}</p>
      <div class="table-scroll"><table><thead><tr><th>Patient</th><th>Visit</th><th>Organs</th><th>Lesion</th></tr></thead><tbody>${visits.map(visit => `<tr><td>${escape(visit.patient)}</td><td>${escape(visit.date || '—')}</td><td title="${escape(visit.quote || '')}">${escape(visit.organs || '—')}</td><td>${escape(visit.lesion || '—')}</td></tr>`).join('') || '<tr><td colspan="4">No indexed patients on this page.</td></tr>'}</tbody></table></div>
      <div class="catalog-pagination"><button id="totalseg-previous" ${page <= 1 ? 'disabled' : ''}>Previous</button><span>${result.total} patients / page ${page}</span><button id="totalseg-next" ${page * 20 >= result.total ? 'disabled' : ''}>Next</button></div>`);
    $('totalseg-run').onclick = action(async () => { await api(`/api/catalog/${row.id}/totalseg`, {}); await showTotalseg(row, page); });
    $('totalseg-stop').onclick = action(async () => { await api(`/api/catalog/${row.id}/totalseg/stop`, {}); await showTotalseg(row, page); });
    $('totalseg-previous').onclick = action(async () => showTotalseg(row, page - 1));
    $('totalseg-next').onclick = action(async () => showTotalseg(row, page + 1));
    if (result.status === 'running') totalsegTimer = setTimeout(() => { if ($('modal').open) action(showTotalseg)(row, page); }, 2000);
  }

  function syncOncoRadar() {
    showModal('Sync OncoRadar index', `<form id="oncoradar-sync"><label class="form-label">WP05 SQLite file<input name="database" required value="C:\\Users\\coren\\MonDrive\\WP05_OncoRadar\\data\\oncoradar.sqlite"></label><p class="small-note">Reads the WP05 database in place. Copies each dataset record, including trial, site, histology, access, license, download path, and clinical-file summaries. The patient list stays in WP05. Curated notes in this workspace are kept.</p><button class="primary">Sync index</button></form>`);
    $('oncoradar-sync').onsubmit = action(async event => {
      event.preventDefault();
      const result = await api('/api/oncoradar-sync', {database: new FormData(event.target).get('database')});
      $('modal').close();
      await renderDatasets();
      toast(`${result.created} datasets added, ${result.refreshed} refreshed. Patient lists were not copied.`);
    });
  }

  function importJson(title, endpoint, cohort = false, onComplete = renderDatasets) {
    showModal(title, `<form id="json-import"><label class="form-label">JSON file<input id="manifest-file" type="file" accept=".json,application/json" required></label>${cohort ? '<label class="form-label"><span><input type="checkbox" required> The manifest uses de-identified patient IDs and contains no patient names.</span></label>' : ''}<p class="small-note">${cohort ? 'One record per imaging series. Required: external_id, patient_id, modality. Optional: study_uid, series_uid, visit, metadata. Refreshing an existing identity preserves its images and masks.' : 'Accepts an array of OncoRadar dataset records, or an object with a records array. Source snapshots are refreshed without replacing curated fields. No images are transferred.'}</p><button class="primary">Import metadata</button></form>`);
    $('json-import').onsubmit = action(async event => {
      event.preventDefault(); const file = $('manifest-file').files[0];
      if (file.size > 4_000_000) throw new Error('Maximum JSON size is 4 MB.');
      const value = JSON.parse(await file.text());
      const data = {records: Array.isArray(value) ? value : value.records};
      if (cohort) data.deidentified = true;
      const result = await api(endpoint, data); $('modal').close(); await onComplete();
      toast(`${result.created} records added, ${result.refreshed} refreshed. Images and annotations were not changed.`);
    });
  }

  async function showCohort(row, projectId = '', page = 1) {
    const result = await api(`/api/catalog/${row.id}/cohort?page=${page}&project_id=${encodeURIComponent(projectId)}`);
    showModal(`${row.name} / cohort`, `<div class="cohort-flow"><label class="form-label">Target project<select id="cohort-project"><option value="">Choose a project</option>${projectOptions()}</select></label><button id="cohort-link" class="primary">Link dataset to project</button></div><p class="small-note">Linking records source provenance. It does not grant data-use permission or download scans. Import one series per cohort record.</p><div class="row-actions"><button id="cohort-import">Import series manifest</button><button id="cohort-template">Download example manifest</button></div>
      <div class="table-scroll"><table><thead><tr><th>Patient / series</th><th>Visit / modality</th><th>Images</th></tr></thead><tbody>${result.items.map(item => `<tr><td><strong>${escape(item.patient_id)}</strong><small>${escape(item.external_id)}</small></td><td>${escape(item.visit || 'Unspecified')} / ${item.modality}</td><td>${item.case_id ? '<span class="status approved">Imported</span>' : `<button data-cohort-upload="${item.id}" ${projectId ? '' : 'disabled'}>Import images</button>`}</td></tr>`).join('')}</tbody></table></div>${result.total ? '' : '<p class="small-note">No series indexed yet. Import a de-identified manifest to prepare the cohort.</p>'}<div class="catalog-pagination"><button id="cohort-previous" ${page <= 1 ? 'disabled' : ''}>Previous</button><span>${result.total} series / page ${page}</span><button id="cohort-next" ${page * 50 >= result.total ? 'disabled' : ''}>Next</button></div>`);
    $('cohort-project').value = projectId;
    $('cohort-project').onchange = action(async event => {const selected = event.target.value; $('modal').close(); await showCohort(row, selected);});
    $('cohort-link').onclick = action(async () => {
      if (!projectId) throw new Error('Choose a target project.');
      await api(`/api/projects/${projectId}/datasets`, {dataset_id: row.id}); toast('Dataset linked to project.');
    });
    $('cohort-import').onclick = () => { $('modal').close(); importJson('Import cohort manifest', `/api/catalog/${row.id}/cohort`, true, () => showCohort(row, projectId)); };
    $('cohort-template').onclick = () => downloadJson('cohort-example.json', {records: [{external_id: 'DEMO-001-baseline-ct', patient_id: 'DEMO-001', modality: 'CT', study_uid: '', series_uid: '', visit: 'baseline', metadata: {description: 'Replace this example with your de-identified series identities'}}]});
    for (const [id, target] of [['cohort-previous', page - 1], ['cohort-next', page + 1]]) $(id).onclick = action(async () => { $('modal').close(); await showCohort(row, projectId, target); });
    document.querySelectorAll('[data-cohort-upload]').forEach(button => button.onclick = action(async () => {
      const item = result.items.find(record => record.id === button.dataset.cohortUpload);
      if (state.data.projects.find(p => p.id === projectId)?.modality !== item.modality) throw new Error('Select a project with the same imaging modality.');
      await api(`/api/projects/${projectId}/datasets`, {dataset_id: row.id});
      state.project = projectId; $('modal').close(); importImages(item);
    }));
  }

  function editProject(project = null) {
    showModal(project ? 'Project guidelines' : 'Create project', `<form id="project-form">${field('Project name', 'name', project?.name, 'required maxlength="120"')}
      <div class="form-grid">${field('Cancer of origin', 'cancer_origin', project?.cancer_origin, 'required maxlength="120" list="cancer-origins"')}<datalist id="cancer-origins">${['Lung', 'Breast', 'Pancreas', 'Liver', 'Colorectal', 'Rectum', 'Brain', 'Melanoma', 'Sarcoma', 'Hodgkin lymphoma', 'Non-Hodgkin lymphoma', 'Renal', 'Prostate', 'Ovarian', 'Head and neck', 'Bladder', 'Gastric'].map(name => `<option value="${name}">`).join('')}</datalist><label class="form-label">Imaging<select name="modality">${options([['CT', 'CT'], ['MR', 'MRI']], project?.modality || 'CT')}</select></label></div>
      ${field('Annotation targets', 'target', project?.target || 'Primary tumor and metastases', 'required maxlength="300"')}${field('Allowed lesion sites (comma-separated)', 'lesion_sites', project?.lesion_sites?.join(', ') || '')}
      <label class="form-label">Annotation guidelines<textarea name="guidelines" rows="8" required minlength="10" maxlength="20000" placeholder="Define inclusion criteria, target lesions and organs, contour boundaries, and completion criteria.">${escape(project?.guidelines || '')}</textarea></label>
      <p class="small-note">Organize projects by cancer of origin. Lesion sites and organ targets belong in the protocol. Each new reading stores its guideline version; existing readings are not silently changed.</p><button class="primary">${project ? 'Save new guideline version' : 'Create project'}</button></form>`);
    $('project-form').onsubmit = action(async event => {
      event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.lesion_sites = split(data.lesion_sites);
      if (project) {data.version = project.version; data.color = project.color;}
      await api(project ? `/api/projects/${project.id}` : '/api/projects', data, project ? 'PUT' : 'POST');
      $('modal').close(); await refresh(); toast(project ? 'Project updated. Existing readings retain their instructions.' : 'Project created. Assign members to grant access.');
    });
  }

  async function manageMembers(project) {
    const members = await api(`/api/projects/${project.id}/members`);
    showModal(`${project.name} / access`, `<p class="small-note">Accounts outside this project cannot open its cases. Administrators have workspace-wide access.</p><div class="membership-list">${members.map(user => `<label><input type="checkbox" data-member="${user.id}" ${user.enabled ? 'checked' : ''} ${user.role === 'admin' ? 'disabled' : ''}><span>${escape(user.name)}<small>${escape(user.role.replaceAll('_', ' '))}</small></span></label>`).join('')}</div>`);
    document.querySelectorAll('[data-member]').forEach(input => input.onchange = action(async () => {
      input.disabled = true;
      try {await api(`/api/projects/${project.id}/members/${input.dataset.member}`, {enabled: input.checked}, 'PUT'); toast('Project access updated.');}
      catch (error) {input.checked = !input.checked; throw error;}
      finally {input.disabled = false;}
    }));
  }

  function downloadJson(name, data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  $('content').addEventListener('click', action(async event => {
    const button = event.target.closest('[data-platform-action]'); if (!button) return;
    const command = button.dataset.platformAction;
    const row = catalog.items.find(item => item.id === button.dataset.id);
    const project = state.data.projects.find(item => item.id === button.dataset.id);
    if (command === 'use-dataset') {
      const result = await api(`/api/catalog/${button.dataset.id}/use`, {});
      const missing = result.gaps.length ? result.gaps.join(', ') : 'rien à signaler';
      state.tab = 'cohorts';
      await refresh();
      toast(result.created ? `Cohorte créée. Encore : ${missing}.` : `Cohorte déjà ouverte. Encore : ${missing}.`);
      return;
    }
    if (command === 'dataset-new') return editDataset();
    if (command === 'dataset-edit') return editDataset(row);
    if (command === 'cohort') return showCohort(row);
    if (command === 'catalog-import') return importJson('Import OncoRadar catalog', '/api/catalog-import');
    if (command === 'oncoradar-sync') return syncOncoRadar();
    if (command === 'totalseg') return showTotalseg(row);
    if (command === 'project-new') return editProject();
    if (command === 'project-edit') return editProject(project);
    if (command === 'project-members') return manageMembers(project);
    if (command === 'project-manifest') return downloadJson(`project-${project.id}.json`, await api(`/api/projects/${project.id}/manifest`));
    if (command === 'discover') {await api('/api/catalog-jobs', {registry: button.dataset.registry}); toast('Discovery queued. Only public catalog metadata will be fetched.');}
    if (command === 'previous') catalog.page--;
    if (command === 'next') catalog.page++;
    return renderDatasets();
  }));
  return {renderDatasets};
}
