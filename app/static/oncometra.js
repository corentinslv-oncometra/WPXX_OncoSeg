import {platformWorkspace} from '/assets/platform-workspace.mjs?v=cohorts-9';
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roleName = value => ({admin:'Administrateur', reviewer:'Radiologue', junior_annotator:'Annotateur', senior_annotator:'Annotateur senior'}[value] || value);
const statusName = value => ({new:'À annoter', in_progress:'Annotation en cours', completed:'À valider', approved:'Validé', queued:'En attente', running:'En cours', succeeded:'Extrait', failed:'Échec'}[value] || value);
const badge = value => `<span class="status ${escape(value)}">${escape(statusName(value))}</span>`;
const state = {user:null, data:null, tab:'datasets', project:'', query:'', status:'', assignment:null, jobs:[], users:[]};
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
    return `<tr><td><strong>${escape(project.name)}</strong><small>${escape(project.dataset.name)} · ${project.modality==='MR'?'IRM':'CT'}</small>${gaps.length?`<small>Encore : ${escape(gaps.join(', '))}</small>`:''}</td><td><span class="status ${status.id}">${escape(status.label)}</span></td><td>${project.cases}</td><td>${project.approved}</td><td><div class="row-actions"><button type="button" disabled title="Aucun modèle de segmentation automatique n’est installé. Les radiologues annotent le masque à la main.">Lancer la segmentation</button><button data-import-project="${project.id}">Importer les images</button>${project.cases?`<button data-project="${project.id}">Voir les examens</button>`:''}</div><small>Segmentation automatique indisponible</small></td></tr>`;
  }).join('');
  $('content').innerHTML=heading('Cohortes','Les datasets que vous avez choisis.')+`<section class="table-panel">${cohorts.length?`<div class="table-scroll"><table><thead><tr><th>Cohorte</th><th>État</th><th>Images</th><th>Validés</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:'<div class="empty"><h2>Aucune cohorte</h2><p>'+(state.user.role==='admin'?'Choisissez un dataset exploitable.':'Aucune cohorte n’est encore ouverte.')+'</p></div>'}</section><p class="small-note">La segmentation automatique n’est pas installée. Le bouton reste sur la ligne et ne lance rien. Les radiologues annotent le masque à la main.</p>`;
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
async function openAssignment(id){
  let row=state.data.assignments.find(a=>a.id===id);if(!row){await refresh(false);row=state.data.assignments.find(a=>a.id===id);}
  if(!row)throw new Error('Lecture introuvable');state.assignment=row;
  $('assignment-context').textContent=`${projectName(row.project_id)} / ${row.reader}${row.user_id===state.user.id?'':' / lecture seule'}`;
  $('viewer').src=`/viewer?study_id=${id}&embedded=1`;await showTab('annotation');
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
  showModal('Importer des images',`<form id="import-form"><label class="form-label">Cohorte<select name="project_id">${projectOptions(false, selected)}</select></label><label class="form-label">Identifiant d’examen<input name="patient_id" required maxlength="120" value="${escape(cohortItem?.patient_id||'')}" ${cohortItem?'readonly':''} placeholder="ex. COHORTE-012"></label>${cohortItem?`<input type="hidden" name="cohort_item_id" value="${cohortItem.id}">`:''}<div id="drop-zone" class="drop-zone">Déposez des fichiers DICOM, un dossier, une archive ZIP ou un volume NIfTI<label>Choisir des fichiers<input id="upload-files" type="file" multiple></label><label>Choisir un dossier<input id="upload-folder" type="file" multiple webkitdirectory></label><p id="file-count">Aucun fichier</p></div><label class="form-label"><span><input name="deidentified" type="checkbox" required> Ces images sont dé-identifiées et autorisées pour cette cohorte.</span></label><p class="small-note">Limite 256 Mo. Les volumes trop grands ou obliques sont refusés. Les identifiants patient ne sont pas retirés automatiquement.</p><button id="upload-submit" class="primary">Importer</button></form>`);
  let files=[];function selectedFiles(list){files=[...list];$('file-count').textContent=`${files.length} fichier${files.length>1?'s':''}`;}
  for(const id of ['upload-files','upload-folder'])$(id).onchange=event=>selectedFiles(event.target.files);
  const zone=$('drop-zone');zone.ondragover=event=>event.preventDefault();zone.ondrop=action(async event=>{event.preventDefault();const {collectDirectoryEntries}=await import('/import-files.mjs');const entries=[...event.dataTransfer.items].map(item=>item.webkitGetAsEntry?.()).filter(Boolean);if(entries.length){const result=await collectDirectoryEntries(entries);selectedFiles(result.map(item=>item.file));}else selectedFiles(event.dataTransfer.files);});
  $('import-form').onsubmit=action(async event=>{event.preventDefault();if(!files.length)throw new Error('Sélectionnez des images.');const data=new FormData(event.target);for(const file of files)data.append('files',file,file.webkitRelativePath||file.name);$('upload-submit').disabled=true;$('upload-submit').textContent='Import…';try{await api('/api/import',data);$('modal').close();await refresh();toast('Images importées.');}finally{if($('upload-submit')){$('upload-submit').disabled=false;$('upload-submit').textContent='Importer';}}});
}

const platform=platformWorkspace({state,api,escape,showModal,action,toast,refresh,importImages});

$('content').addEventListener('click',action(async event=>{
  const button=event.target.closest('button');if(!button||button.dataset.platformAction)return;
  if(button.dataset.project){state.project=button.dataset.project;state.status='';state.query='';return showTab('review');}
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
$('refresh-assignment').onclick=action(async()=>{await refresh(false);await openAssignment(state.assignment.id);});
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
