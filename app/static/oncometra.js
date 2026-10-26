import {platformWorkspace} from '/assets/platform-workspace.mjs?v=cohorts-17';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roleName = value => ({admin:'Administrateur', reviewer:'Radiologue', junior_annotator:'Annotateur', senior_annotator:'Annotateur senior'}[value] || value);
const statusName = value => ({new:'À annoter', in_progress:'Annotation en cours', completed:'À valider', approved:'Validé', queued:'En attente', running:'En cours', succeeded:'Extrait', failed:'Échec'}[value] || value);
const badge = value => `<span class="status ${escape(value)}">${escape(statusName(value))}</span>`;
const state = {user:null, data:null, tab:'datasets', project:'', query:'', status:'', assignment:null, jobs:[], users:[], browse:null};
let toastTimer;
async function api(path, data, method) {
  const options = {method:method || (data ? 'POST':'GET'), credentials:'same-origin', headers:{}};
  if (data instanceof FormData) options.body = data;
  else if (data) {options.headers['Content-Type']='application/json'; options.body=JSON.stringify(data);}
  const response=await fetch(path,options);
  const result=await response.json();
  if(!response.ok){if(response.status===401 && !path.endsWith('/login')) showLogin();throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));}
  return result;
}
function toast(text,error=false){clearTimeout(toastTimer);$('toast').textContent=text;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:4500);}
function action(fn){return (...args)=>Promise.resolve().then(()=>fn(...args)).catch(error=>toast(error.message,true));}
function showLogin(){$('login-screen').hidden=false;$('workspace').hidden=true;state.user=null;}
function reviewAccess(){return ['reviewer','admin'].includes(state.user?.role);}
function heading(title,subtitle,buttons=''){return `<div class="page-heading"><div><h1>${escape(title)}</h1>${subtitle?`<p>${escape(subtitle)}</p>`:''}</div><div class="actions">${buttons}</div></div>`;}
function cohortProjects(){return (state.data?.projects||[]).filter(project=>project.dataset);}
function projectName(id){const project=state.data.projects.find(p=>p.id===id);return project?`${project.name} ${project.modality==='MR'?'IRM':'CT'}`:id;}
function projectOptions(all=true, selected=state.project){return `${all?'<option value="">Toutes les cohortes</option>':''}${cohortProjects().map(p=>`<option value="${p.id}" ${p.id===selected?'selected':''}>${escape(projectName(p.id))}</option>`).join('')}`;}
function showModal(title,html){$('modal-title').textContent=title;$('modal-body').innerHTML=html;$('modal').showModal();}
function pendingCount(){
  const ids=new Set(cohortProjects().map(project=>project.id));
  return state.data.cases.filter(item=>ids.has(item.project_id) && !state.data.assignments.some(row=>row.case_id===item.id && row.status==='approved')).length;
}
async function refresh(render=true){state.data=await api('/api/workspace');$('work-count').textContent=pendingCount();$('storage-status').textContent=state.data.storage==='ephemeral'?'Stockage temporaire':'Stockage local';if(render && state.tab!=='annotation') await showTab(state.tab);}
async function showTab(tab){state.tab=tab;const selected=tab==='annotation'?'review':tab;document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('selected',button.dataset.tab===selected));$('annotation-page').hidden=tab!=='annotation';$('content').hidden=tab==='annotation';if(tab==='annotation')return;const renders={datasets:platform.renderDatasets,cohorts:renderCohorts,review:renderReview,admin:renderAdmin};await renders[tab]();}

function cohortStatus(project){
  if(!project.cases) return {id:'failed', label:'Images non importées'};
  if(project.cases && project.approved===project.cases) return {id:'approved', label:'Validé'};
  if(project.completed) return {id:'completed', label:'À valider'};
  return {id:'new', label:'Images prêtes'};
}
function cohortGaps(project){
  const gaps=[];
  if(project.dataset.commercial_use!=='permitted') gaps.push('licence non tranchée');
  if(!project.cases) gaps.push('images non importées');
  if(project.dataset.segmentations!==true && !project.approved) gaps.push('pas de masque');
  return gaps;
}
function renderCohorts(){
  const cohorts=cohortProjects();
  const rows=cohorts.map(project=>{
    const status=cohortStatus(project);
    const gaps=cohortGaps(project);
    return `<tr><td><strong>${escape(project.name)}</strong><small>${escape(project.dataset.name)} · ${project.modality==='MR'?'IRM':'CT'}</small>${gaps.length?`<small>Encore : ${escape(gaps.join(', '))}</small>`:''}</td><td><span class="status ${status.id}">${escape(status.label)}</span></td><td>${project.cases}</td><td>${project.approved}</td><td><div class="row-actions"><button type="button" disabled title="Le calcul part avant la page À valider, un examen à la fois. Il ne se lance pas depuis cette liste.">Lancer la segmentation</button><button class="primary" data-browse-project="${project.id}">Choisir un patient</button><button data-import-project="${project.id}">Importer des fichiers</button>${project.cases?`<button data-project="${project.id}">Voir les examens</button>`:''}</div><small>Préparée avant la validation</small></td></tr>`;
  }).join('');
  $('content').innerHTML=heading('Cohortes','Les datasets que vous avez choisis.')+`<section class="table-panel">${cohorts.length?`<div class="table-scroll"><table><thead><tr><th>Cohorte</th><th>État</th><th>Images</th><th>Validés</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:'<div class="empty"><h2>Aucune cohorte</h2><p>'+(state.user.role==='admin'?'Choisissez un dataset exploitable.':'Aucune cohorte n’est encore ouverte.')+'</p></div>'}</section><p class="small-note">TotalSegmentator calcule les organes et toutes les HU avant la page À valider. S’il n’y a pas de fichier SEG, la tumeur est proposée selon le type de cancer. Un seul examen est préparé sur ce poste, sans GPU.</p>`;
}

function filters(){return `<div class="filters"><input id="filter-query" aria-label="Chercher un examen" placeholder="Chercher un examen" value="${escape(state.query)}"><select id="filter-project" aria-label="Cohorte">${projectOptions()}</select><select id="filter-status" aria-label="État"><option value="">Tous les états</option>${['new','in_progress','completed','approved'].map(s=>`<option value="${s}" ${state.status===s?'selected':''}>${statusName(s)}</option>`).join('')}</select></div>`;}
function queueRows(){
  const ids=new Set(cohortProjects().map(project=>project.id));
  return state.data.cases.filter(item=>ids.has(item.project_id)).map(item=>{
    const related=state.data.assignments.filter(row=>row.case_id===item.id);
    const mine=related.find(row=>row.user_id===state.user.id && row.kind==='reader');
    const status=mine?.status || (related.some(row=>row.status==='approved')?'approved':related.some(row=>row.status==='completed')?'completed':'new');
    return {case:item, mine, related, status};
  }).filter(row=>(!state.project||row.case.project_id===state.project)&&(!state.status||row.status===state.status)&&(row.case.patient_id.toLowerCase().includes(state.query.toLowerCase())));
}
function wireFilters(){for(const name of ['query','project','status'])$(`filter-${name}`)?.addEventListener(name==='query'?'input':'change',event=>{state[name]=event.target.value;renderQueue();});}
function renderQueue(){
  const visible=queueRows();
  $('queue-rows').innerHTML=visible.length?`<div class="table-scroll"><table><thead><tr><th>Examen</th><th>Cohorte</th><th>Proposition</th><th>État</th><th></th></tr></thead><tbody>${visible.map(row=>{
    const pending=row.related.find(item=>item.user_id!==state.user.id && item.status==='completed');
    const adjudicate=row.related.find(item=>item.user_id!==state.user.id && ['completed','approved'].includes(item.status));
    let actions='';
    if(!row.mine) actions+=`<button class="primary" data-begin="${row.case.id}">Annoter</button>`;
    else if(['new','in_progress'].includes(row.mine.status)) actions+=`<button class="primary" data-open="${row.mine.id}">Annoter</button>`;
    else actions+=`<button data-open="${row.mine.id}">Ouvrir</button>`;
    if(reviewAccess() && pending) actions+=`<button class="primary" data-approve="${pending.id}">Approuver</button><button data-return="${pending.id}">Renvoyer</button><button data-adjudicate="${pending.id}">Arbitrer</button>`;
    else if(reviewAccess() && adjudicate && adjudicate.status==='approved') actions+=`<button data-adjudicate="${adjudicate.id}">Arbitrer</button>`;
    return `<tr><td><strong>${escape(row.case.patient_id)}</strong><small>${escape(row.case.source?.sequence||row.case.modality||'')}</small></td><td>${escape(projectName(row.case.project_id))}</td><td>Aucune<small>Annotation manuelle</small></td><td>${badge(row.status)}</td><td><div class="row-actions">${actions}</div></td></tr>`;
  }).join('')}</tbody></table></div>`:`<div class="empty"><h2>${cohortProjects().length?'Aucun examen':'Aucune cohorte ouverte'}</h2><p>${cohortProjects().length?'Importez les images d’une cohorte pour les faire annoter.':'Les examens apparaissent ici une fois une cohorte ouverte et ses images importées.'}</p></div>`;
}
function renderReview(){
  if(!$('queue-rows')){
    $('content').innerHTML=heading('À valider','Chaque examen montre la proposition du modèle. Sans proposition, le radiologue annote le masque, puis valide.')+`<section class="table-panel">${filters()}<div id="queue-rows"></div></section><p class="small-note">Approuver, renvoyer et arbitrer sont les actions de cette file. Une lecture ne peut pas être approuvée par son auteur.</p>`;
    wireFilters();
  }
  renderQueue();
}
function browsePosition(patientId, timepointId){
  const patients=state.browse?.catalog?.patients||[];
  const patientIndex=patients.findIndex(item=>item.id===patientId);
  if(patientIndex<0) return null;
  const timepoints=patients[patientIndex].timepoints;
  const timeIndex=timepoints.findIndex(item=>item.id===timepointId);
  if(timeIndex<0) return null;
  const neighbor=step=>{
    const target=patientIndex+step;
    if(target<0||target>=patients.length) return null;
    const times=patients[target].timepoints;
    const chosen=Math.min(timeIndex, times.length-1);
    return {patient_id:patients[target].id, timepoint_id:times[chosen].id};
  };
  return {patient_id:patientId, timepoint_id:timepointId, label:timepoints[timeIndex].label,
    patient_index:patientIndex, patient_count:patients.length, timepoint_index:timeIndex, timepoint_count:timepoints.length,
    previous_timepoint:timeIndex>0?{patient_id:patientId, timepoint_id:timepoints[timeIndex-1].id}:null,
    next_timepoint:timeIndex+1<timepoints.length?{patient_id:patientId, timepoint_id:timepoints[timeIndex+1].id}:null,
    previous_patient:neighbor(-1), next_patient:neighbor(1)};
}
function renderBrowseNav(){
  const nav=$('browse-nav');
  const position=state.browse&&browsePosition(state.browse.patientId, state.browse.timepointId);
  if(!nav) return;
  if(!position){nav.hidden=true;return;}
  Object.assign(state.browse, position);
  nav.hidden=false;
  $('browse-position').innerHTML=`<strong>${escape(position.patient_id)}</strong><span>${escape(position.label)}</span><span>Patient ${position.patient_index + 1} / ${position.patient_count} · Temps ${position.timepoint_index + 1} / ${position.timepoint_count}</span>`;
  $('browse-prev-patient').disabled=!position.previous_patient;
  $('browse-next-patient').disabled=!position.next_patient;
  $('browse-prev-time').disabled=!position.previous_timepoint;
  $('browse-next-time').disabled=!position.next_timepoint;
}
function renderPatientPicker(){
  const host=$('local-status');
  const browse=state.browse;
  if(!host||!browse?.catalog) return;
  const patient=browse.catalog.patients.find(item=>item.id===browse.patientId)||browse.catalog.patients[0];
  browse.patientId=patient.id;
  if(!patient.timepoints.some(item=>item.id===browse.timepointId)) browse.timepointId=patient.timepoints[0].id;
  host.innerHTML=`<label class="form-label">Personne<select id="browse-patient">${browse.catalog.patients.map(item=>`<option value="${escape(item.id)}" ${item.id===browse.patientId?'selected':''}>${escape(item.id)} · ${item.timepoints.length} temps</option>`).join('')}</select></label><label class="form-label">Temps<select id="browse-time">${patient.timepoints.map(item=>`<option value="${escape(item.id)}" ${item.id===browse.timepointId?'selected':''}>${escape(item.label)}</option>`).join('')}</select></label><button type="button" id="browse-open" class="primary">Ouvrir cet examen</button>`;
  $('browse-patient').onchange=()=>{browse.patientId=$('browse-patient').value;browse.timepointId='';renderPatientPicker();};
  $('browse-time').onchange=()=>{browse.timepointId=$('browse-time').value;};
  $('browse-open').onclick=action(()=>openBrowsed());
}
async function loadPatientPicker(form){
  if(!form.deidentified.checked) throw new Error('Confirmez que les images sont dé-identifiées.');
  const projectId=new FormData(form).get('project_id');
  const path=$('local-path').value.trim();
  if(!path) throw new Error('Indiquez un dossier dans data.');
  $('local-status').textContent='Lecture des patients…';
  const catalog=await api(`/api/projects/${projectId}/local-catalog?path=${encodeURIComponent(path)}`);
  if(!catalog.patients.length) throw new Error('Aucun volume dans ce dossier.');
  state.browse={projectId, path, catalog, patientId:catalog.patients[0].id, timepointId:catalog.patients[0].timepoints[0].id};
  renderPatientPicker();
}
function browseDataset(projectId){
  showModal('Choisir un examen',`<form id="import-form"><p class="small-note">Un seul patient et un seul temps sont chargés. Vous pourrez passer au temps ou au patient suivant dans la visionneuse.</p><label class="form-label">Dossier déjà dans data<input id="local-path" value="TCIA_Data/hcc_tace_seg" spellcheck="false"></label><input type="hidden" name="project_id" value="${escape(projectId)}"><label class="form-label"><span><input name="deidentified" type="checkbox" required> Ces images sont dé-identifiées et autorisées pour cette cohorte.</span></label><div id="local-status" class="small-note"></div><button class="primary">Afficher les patients</button></form>`);
  $('import-form').onsubmit=action(async event=>{event.preventDefault();await loadPatientPicker(event.target);});
}
async function openBrowsed(target){
  const browse=state.browse;
  if(!browse) throw new Error('Choisissez d’abord un patient.');
  const patientId=target?.patient_id||$('browse-patient')?.value||browse.patientId;
  const timepointId=target?.timepoint_id||$('browse-time')?.value||browse.timepointId;
  if($('browse-position')) $('browse-position').textContent='Ouverture du volume…';
  if($('browse-open')){$('browse-open').disabled=true;$('browse-open').textContent='Ouverture…';}
  const result=await api(`/api/projects/${browse.projectId}/local-catalog/open`,{path:browse.path,patient_id:patientId,timepoint_id:timepointId});
  state.browse={...browse, ...result, patientId:result.patient_id, timepointId:result.timepoint_id};
  if($('modal')?.open) $('modal').close();
  await refresh(false);
  await openAssignment(result.study_id);
}
function renderSegState(source){
  const seg=$('seg-state');
  if(!seg) return;
  if(!source || source.seg_present==null){seg.hidden=true;return;}
  seg.hidden=false;
  seg.classList.remove('used','unused','absent');
  if(source.seg_used){seg.textContent='SEG présent · utilisé';seg.classList.add('used');}
  else if(source.seg_present){seg.textContent='SEG présent · non utilisé';seg.classList.add('unused');}
  else{seg.textContent='SEG absent';seg.classList.add('absent');}
}
async function openAssignment(id){
  let row=state.data.assignments.find(a=>a.id===id);if(!row){await refresh(false);row=state.data.assignments.find(a=>a.id===id);}
  if(!row)throw new Error('Lecture introuvable');state.assignment=row;
  $('assignment-context').textContent=`${projectName(row.project_id)} / ${row.reader}${row.user_id===state.user.id?'':' / lecture seule'}`;
  const exam=state.data.cases.find(item=>item.id===row.case_id);
  const source=exam?.source;
  renderSegState(source);
  if(source?.local_path&&source.local_patient&&source.local_timepoint){
    if(!state.browse||state.browse.path!==source.local_path||!state.browse.catalog){
      const catalog=await api(`/api/projects/${row.project_id}/local-catalog?path=${encodeURIComponent(source.local_path)}`);
      state.browse={projectId:row.project_id, path:source.local_path, catalog};
    }
    state.browse.patientId=source.local_patient;
    state.browse.timepointId=source.local_timepoint;
  }
  $('viewer').src=`/viewer?study_id=${id}&embedded=1`;await showTab('annotation');
  renderBrowseNav();
  watchDetection(id);
}
async function renderAdmin(){
  state.users=await api('/api/users');
  $('content').innerHTML=heading('Comptes','Création des radiologues.','<button class="primary" data-action="add-user">Créer un radiologue</button>')+`<section class="table-panel"><table><thead><tr><th>Nom</th><th>Identifiant</th><th>Rôle</th></tr></thead><tbody>${state.users.map(user=>`<tr><td>${escape(user.name)}</td><td>${escape(user.username)}</td><td>${escape(roleName(user.role))}</td></tr>`).join('')}</tbody></table></section>`;
}
async function assignReader(caseId){state.users=await api('/api/users');showModal('Assigner un lecteur',`<form id="assign-form"><label class="form-label">Lecteur<select name="reader">${state.users.map(u=>`<option value="${u.id}">${escape(u.name)} / ${escape(roleName(u.role))}</option>`).join('')}</select></label><button class="primary">Assigner</button></form>`);$('assign-form').onsubmit=action(async event=>{event.preventDefault();await api(`/api/cases/${caseId}/assign`,{user_id:new FormData(event.target).get('reader')});$('modal').close();await refresh();toast('Lecteur assigné.');});}
function addUser(){showModal('Créer un radiologue',`<form id="user-form"><label class="form-label">Nom<input name="name" required maxlength="120"></label><label class="form-label">Identifiant<input name="username" required pattern="[a-z0-9][a-z0-9._-]{2,79}" autocomplete="off"></label><label class="form-label">Mot de passe temporaire<input name="password" type="password" required minlength="12" autocomplete="new-password"></label><label class="form-label">Rôle<select name="role"><option value="reviewer" selected>Radiologue</option><option value="junior_annotator">Annotateur</option><option value="senior_annotator">Annotateur senior</option><option value="admin">Administrateur</option></select></label><p class="small-note">Le compte voit les cohortes ouvertes. Transmettez le mot de passe en privé.</p><button class="primary">Créer le compte</button></form>`);$('user-form').onsubmit=action(async event=>{event.preventDefault();await api('/api/users',Object.fromEntries(new FormData(event.target)));$('modal').close();await renderAdmin();toast('Compte créé.');});}
function importImages(cohortItem=null, projectId=''){
  const cohorts=cohortProjects();
  if(!cohorts.length) return toast('Ouvrez d’abord un dataset.', true);
  const selected=projectId||state.project||cohorts[0].id;
  showModal('Importer des images',`<form id="import-form"><label class="form-label">Cohorte<select name="project_id">${projectOptions(false, selected)}</select></label><label class="form-label">Identifiant d’examen<input name="patient_id" maxlength="120" value="${escape(cohortItem?.patient_id||'')}" ${cohortItem?'readonly':''} placeholder="ex. COHORTE-012"></label>${cohortItem?`<input type="hidden" name="cohort_item_id" value="${cohortItem.id}">`:''}<div id="drop-zone" class="drop-zone">Déposez des fichiers DICOM, un dossier, une archive ZIP ou un volume NIfTI<label>Choisir des fichiers<input id="upload-files" type="file" multiple></label><label>Choisir un dossier<input id="upload-folder" type="file" multiple webkitdirectory></label><p id="file-count">Aucun fichier</p></div><p class="small-note">Le dépôt depuis le navigateur est limité à 256 Mo.</p><label class="form-label">Dossier déjà dans data<input id="local-path" value="TCIA_Data/hcc_tace_seg" spellcheck="false"></label><div id="local-status" class="small-note">Un seul patient et un seul temps sont ouverts. Le reste du dossier reste sur le disque.</div><label class="form-label"><span><input name="deidentified" type="checkbox" required> Ces images sont dé-identifiées et autorisées pour cette cohorte.</span></label><button type="submit" id="import-local" class="primary">Choisir un patient</button><button type="submit" id="upload-submit">Importer la sélection</button></form>`);
  let files=[];function selectedFiles(list){files=[...list];$('file-count').textContent=`${files.length} fichier${files.length>1?'s':''}`;}
  for(const id of ['upload-files','upload-folder'])$(id).onchange=event=>selectedFiles(event.target.files);
  const zone=$('drop-zone');zone.ondragover=event=>event.preventDefault();zone.ondrop=action(async event=>{event.preventDefault();const {collectDirectoryEntries}=await import('/import-files.mjs');const entries=[...event.dataTransfer.items].map(item=>item.webkitGetAsEntry?.()).filter(Boolean);if(entries.length){const result=await collectDirectoryEntries(entries);selectedFiles(result.map(item=>item.file));}else selectedFiles(event.dataTransfer.files);});
  $('import-form').onsubmit=action(async event=>{
    event.preventDefault();
    const submitter=event.submitter;
    if(submitter&&submitter.id==='upload-submit'){
      if(!files.length) throw new Error('Sélectionnez des images, ou choisissez un patient.');
      const bytes=files.reduce((total,file)=>total+file.size,0);
      if(files.length>3000||bytes>256*1024*1024) throw new Error('Cette sélection est trop grande. Choisissez un patient et un temps.');
      const data=new FormData(event.target);
      if(!String(data.get('patient_id')||'').trim()) throw new Error('Indiquez un identifiant d’examen.');
      for(const file of files) data.append('files',file,file.webkitRelativePath||file.name);
      $('upload-submit').disabled=true;$('upload-submit').textContent='Import…';
      try{await api('/api/import',data);$('modal').close();await refresh();toast('Images importées.');}
      finally{if($('upload-submit')){$('upload-submit').disabled=false;$('upload-submit').textContent='Importer la sélection';}}
      return;
    }
    await loadPatientPicker(event.target);
  });
}

const platform=platformWorkspace({state,api,escape,showModal,action,toast,refresh,importImages});

$('content').addEventListener('click',action(async event=>{
  const button=event.target.closest('button');if(!button||button.dataset.platformAction)return;
  if(button.dataset.project){state.project=button.dataset.project;state.status='';state.query='';return showTab('review');}
  if(button.dataset.browseProject)return browseDataset(button.dataset.browseProject);
  if(button.dataset.importProject)return importImages(null, button.dataset.importProject);
  if(button.dataset.begin){const row=await api(`/api/cases/${button.dataset.begin}/assign`,{});await refresh(false);return openAssignment(row.id);}
  if(button.dataset.open)return openAssignment(button.dataset.open);
  if(button.dataset.assign)return assignReader(button.dataset.assign);
  if(button.dataset.adjudicate){const row=await api(`/api/assignments/${button.dataset.adjudicate}/adjudicate`,{});await refresh(false);return openAssignment(row.id);}
  if(button.dataset.approve){const row=state.data.assignments.find(a=>a.id===button.dataset.approve);showModal('Approuver cette lecture ?',`<form id="approve-form"><p>${escape(row.patient_id)} / ${escape(row.reader)}</p><label class="form-label"><span><input type="checkbox" required> J’ai revu le masque sur les coupes concernées.</span></label><button class="primary">Approuver</button></form>`);$('approve-form').onsubmit=action(async e=>{e.preventDefault();await api(`/api/lung/studies/${row.id}/approve`,{version:row.version,revision_id:row.revision_id,reviewed:true});$('modal').close();await refresh();toast('Lecture approuvée.');});return;}
  if(button.dataset.return){const row=state.data.assignments.find(a=>a.id===button.dataset.return);showModal('Renvoyer au radiologue',`<form id="return-form"><label class="form-label">Corrections demandées<input name="comment" required maxlength="1000"></label><button class="primary">Renvoyer</button></form>`);$('return-form').onsubmit=action(async e=>{e.preventDefault();await api(`/api/assignments/${row.id}/return`,{version:row.version,comment:new FormData(e.target).get('comment')});$('modal').close();await refresh();toast('Lecture renvoyée.');});return;}
  const actions={'add-user':addUser};if(actions[button.dataset.action])return actions[button.dataset.action]();
}));
$('navigation').addEventListener('click',action(async event=>{const button=event.target.closest('[data-tab]');if(button){if(button.dataset.tab!=='annotation')await refresh(false);await showTab(button.dataset.tab);}}));
$('modal-close').onclick=()=>$('modal').close();
$('back-worklist').onclick=action(async()=>{await refresh(false);await showTab('review');});
for(const [id,key] of [['browse-prev-patient','previous_patient'],['browse-next-patient','next_patient'],['browse-prev-time','previous_timepoint'],['browse-next-time','next_timepoint']]){
  $(id).onclick=action(async()=>{const target=state.browse?.[key];if(target) await openBrowsed(target);});
}
$('refresh-assignment').onclick=action(async()=>{await refresh(false);await openAssignment(state.assignment.id);});
function huText(value){return Number(value).toLocaleString('fr-FR',{maximumFractionDigits:1});}
let detectionTimer=0;
let detectionSeen='';
function showDetection(status){
  const button=$('assignment-detect');
  button.disabled=status.state==='running';
  button.textContent=status.state==='running'?'Détection…':'Détecter';
  button.title=status.error||status.detail||button.dataset.title||'';
}
async function watchDetection(id){
  window.clearTimeout(detectionTimer);
  if(!state.assignment||state.assignment.id!==id) return;
  try{
    const status=await api(`/api/studies/${id}/autoseg`);
    if(state.assignment?.id!==id) return;
    showDetection(status);
    if(status.state==='running') detectionTimer=window.setTimeout(()=>watchDetection(id),4000);
    if(status.state==='done'){
      $('viewer').contentWindow?.postMessage({type:'oncometra:load-organs',seeded:!!status.seeded},location.origin);
      if(detectionSeen==='running') toast(status.detail||'Organes affichés. Maintenez 3 secondes sur un organe pour ne garder que lui.');
    }
    if(status.state==='error'&&detectionSeen==='running'&&status.error) toast(status.error,true);
    detectionSeen=status.state;
  }catch(error){
    if(state.assignment?.id===id) $('assignment-detect').title=error.message;
  }
}
$('assignment-detect').onclick=action(async()=>{
  if(!state.assignment) return;
  const status=await api(`/api/studies/${state.assignment.id}/autoseg`,{});
  showDetection(status);
  toast(status.state==='running'?'Détection lancée pour cet examen seulement. Comptez plusieurs minutes.':'Détection déjà en cours.');
  watchDetection(state.assignment.id);
});
$('assignment-organs').onclick=action(async()=>{
  if(!state.assignment) return;
  const result=await api(`/api/studies/${state.assignment.id}/organs`);
  const rows=(result.organs||[]).map(item=>`<tr><td>${escape(item.label)}</td><td>${item.volume_mm3>=1000?`${(item.volume_mm3/1000).toLocaleString('fr-FR',{maximumFractionDigits:1})} cm³`:`${Math.round(item.volume_mm3).toLocaleString('fr-FR')} mm³`}</td><td>${huText(item.hu_mean)}</td><td>${huText(item.hu_median)}</td><td>${huText(item.hu_std)}</td><td>${huText(item.hu_min)}</td><td>${huText(item.hu_max)}</td><td>${huText(item.hu_p05)}</td><td>${huText(item.hu_p95)}</td></tr>`).join('');
  showModal('Organes et HU',`<p class="small-note">${escape(result.cancer||'')} · ${escape(result.tumor_note||'Les valeurs sont en unités Hounsfield, calculées dans chaque organe.')}</p><div class="table-scroll organs-table"><table><thead><tr><th>Organe</th><th>Volume</th><th>Moyenne</th><th>Médiane</th><th>Écart-type</th><th>Min</th><th>Max</th><th>P5</th><th>P95</th></tr></thead><tbody>${rows||'<tr><td colspan="9">Aucun organe mesuré.</td></tr>'}</tbody></table></div>`);
});
$('assignment-guidelines').onclick=()=>showModal(`Protocole / version ${state.assignment.project_version||'—'}`,`<div class="guideline-copy">${escape(state.assignment.guidelines||'Aucun protocole enregistré pour cette lecture.')}</div>`);
window.addEventListener('message',action(async event=>{if(event.origin!==location.origin||event.source!==$('viewer').contentWindow||event.data?.type!=='oncometra:annotation-updated')return;await refresh(false);const row=state.data.assignments.find(a=>a.id===event.data.studyId);if(row&&row.id===state.assignment?.id)state.assignment=row;}));
$('logout').onclick=action(async()=>{await api('/api/auth/logout',{});$('viewer').src='about:blank';showLogin();});
$('login-form').onsubmit=async event=>{event.preventDefault();$('login-error').textContent='';try{state.user=await api('/api/auth/login',Object.fromEntries(new FormData(event.target)));event.target.reset();await boot();}catch(error){$('login-error').textContent=error.message;}};
async function boot(){
  state.user=await api('/api/auth/me');
  $('login-screen').hidden=true;$('workspace').hidden=false;
  $('user-name').textContent=state.user.name;
  $('user-role').textContent=roleName(state.user.role);
  $('user-avatar').textContent=state.user.name.split(/\s+/).filter(Boolean).map(part=>part[0]).join('').slice(0,2).toUpperCase()||'U';
  document.querySelectorAll('[data-admin]').forEach(el=>el.hidden=state.user.role!=='admin');
  if(state.user.role==='admin'){if(!['datasets','cohorts','review','admin','annotation'].includes(state.tab))state.tab='datasets';}
  else if(!['cohorts','review','annotation'].includes(state.tab))state.tab='cohorts';
  await refresh();
}
boot().catch(error=>{showLogin();if(error.message!=='Sign in to continue')$('login-error').textContent=error.message;});
