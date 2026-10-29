"""Companion aggregate operations view; all effects use operationsClient.

Reuse: shared overlay frame, receipts modal geometry and disclosures, standing
question review list/actions, and the shell's labelled native form controls.
No application/domain imports, durable effect state or per-item effect loop.
"""
from companion_ui.workspace.guidance_layer import guidance_callout_markup
from companion_ui.workspace.overlay_frame import overlay_frame_header, overlay_frame_root_attrs


def operations_launcher_markup() -> str:
    return """<button type="button" class="btn btn--secondary" data-testid="operations-open" data-intent="operations.open" aria-haspopup="dialog"
      onclick="overlayHost.mount('operations')">Operations</button>
      <noscript><p>Operations requires JavaScript. No operation has been submitted.</p></noscript>"""


def operations_workspace_markup() -> str:
    frame = overlay_frame_root_attrs(overlay_id="operations", position="center")
    header = overlay_frame_header(overlay_id="operations", title="Operations", guidance_surface="operations")
    return """
<style>
/* Receipts modal frame + standing-question review content; single ordered column. */
.operations-modal {align-items:flex-start;display:flex;inset:0;justify-content:center;
  padding:56px 16px 0;pointer-events:none;position:fixed;z-index:1010;}
.operations-modal[hidden] {display:none;}
.operations-panel {background:var(--bg-surface);border:1px solid var(--border-strong);
  border-radius:var(--radius-lg,10px);box-shadow:0 18px 48px rgba(0,0,0,.5);
  display:flex;flex-direction:column;gap:10px;max-height:72vh;max-width:640px;
  overflow:hidden;padding:18px 20px;pointer-events:auto;width:100%;}
.operations-body {overflow-y:auto;min-width:0;}
.operations-body fieldset {border:1px solid var(--border);border-radius:var(--radius-sm);
  margin:8px 0;padding:12px;min-width:0;}
.operations-body legend,.operations-body h3 {color:var(--fg-1);font-size:var(--text-md);}
.operations-body p,.operations-body label,.operations-body summary {font-size:var(--text-sm);}
.operations-body label {display:block;color:var(--fg-1);margin:6px 0;overflow-wrap:anywhere;}
.operations-body input:not([type=checkbox]),.operations-body textarea,.operations-body select {
  background:var(--bg-raised);border:1px solid var(--border-strong);border-radius:var(--radius-sm);
  color:var(--fg-1);font:inherit;padding:7px 10px;width:100%;max-width:100%;}
.operations-body textarea {min-height:96px;resize:vertical;}
.operations-actions {display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;}
.operations-actions button {background:var(--bg-raised);border:1px solid var(--border-strong);
  border-radius:var(--radius-sm);color:var(--fg-1);cursor:pointer;font:inherit;
  font-size:var(--text-sm);padding:7px 11px;}
.operations-actions button[data-primary=true] {border-color:var(--accent-dim);}
.operations-actions button:disabled {cursor:default;opacity:.45;}
.operations-body :focus-visible {outline:1px solid var(--border-focus);outline-offset:2px;}
.operations-body pre,.operations-body code {white-space:pre-wrap;overflow-wrap:anywhere;
  font-family:var(--font-mono);font-size:var(--text-xs);}
.operations-body ul {list-style:none;padding:0;}
.operations-body li {border-top:1px solid var(--border);padding:9px 10px;overflow-wrap:anywhere;}
.operations-state {color:var(--fg-2);font-size:var(--text-sm);overflow-wrap:anywhere;}
@media print {.operations-modal {position:static;padding:0;} .operations-panel {max-height:none;overflow:visible;}}
</style>
<div class="operations-modal" id="operations-workspace" data-testid="operations-workspace"
  role="dialog" aria-modal="true" aria-label="Operations" hidden __FRAME__>
  <div class="operations-panel">__HEADER____GUIDANCE__
    <div class="operations-body">
      <noscript><p>Operations requires JavaScript. No operation has been submitted.</p></noscript>
      <p class="operations-state" id="operations-state" role="status" aria-live="polite" aria-atomic="true">Open to discover available operations.</p>
      <div class="operations-actions"><button type="button" id="operations-discover">Refresh capabilities and resources</button></div>
      <details><summary>Capability availability</summary><ul id="operations-capabilities"></ul></details>
      <fieldset id="operations-selection"><legend>1. Select resources</legend>
        <label for="operations-filter">Title or path filter</label><input id="operations-filter" type="search">
        <div class="operations-actions"><button type="button" id="operations-list">Find resources</button></div>
        <ul id="operations-resources"></ul>
      </fieldset>
      <fieldset id="operations-intent" disabled><legend>2. Choose an outcome</legend>
        <label for="operations-kind">Operation</label><select id="operations-kind"></select>
        <label for="operations-binding">Destination context / vault binding</label><select id="operations-binding"></select>
        <p class="operations-state">A destination is intent. The runtime validates context, policy, identity and versions.</p>
        <div id="operations-arguments"></div>
        <div class="operations-actions"><button type="button" id="operations-preview">Inspect frozen scope</button></div>
      </fieldset>
      <section id="operations-preview-region" aria-label="Frozen operation scope" tabindex="-1" hidden>
        <h3>3. Frozen operation scope</h3><div id="operations-scope"></div>
        <p>Nothing has executed. Confirm this exact scope once. Cancellation does not roll back completed effects.</p>
        <div class="operations-actions"><button type="button" id="operations-confirm" data-primary="true">Confirm this scope once</button>
          <button type="button" id="operations-back">Return to selection</button></div>
      </section>
      <section id="operations-results" aria-label="Operation progress, receipts and recovery" tabindex="-1" hidden>
        <h3>4. Progress, receipts and recovery</h3><div id="operations-progress"></div>
        <div class="operations-actions"><button type="button" id="operations-new">Start a new scope</button><button type="button" id="operations-inspect">Inspect durable state</button>
          <button type="button" id="operations-cancel" hidden>Request cancellation</button>
          <button type="button" id="operations-resume" hidden>Verify / resume through runtime</button></div>
      </section>
      <details><summary>Reopen an operation after interruption</summary>
        <label for="operations-reference">Request or batch identity</label><input id="operations-reference" autocomplete="off">
        <label for="operations-digest">Frozen batch digest (leave empty for a single operation)</label><input id="operations-digest" autocomplete="off">
        <div class="operations-actions"><button type="button" id="operations-reopen">Inspect retained operation</button></div>
        <p>These references grant no authority. Readback must still pass runtime authentication and context checks.</p>
      </details>
    </div>
  </div>
</div>""".replace("__FRAME__", frame).replace("__HEADER__", header).replace("__GUIDANCE__", guidance_callout_markup("operations"))


def operations_workspace_script() -> str:
    return r"""<script>
(function() {
  'use strict';
  var root = document.getElementById('operations-workspace');
  if (!root || !window.overlayHost || !window.operationsClient) return;
  var api = window.operationsClient;
  function el(id) { return document.getElementById('operations-' + id); }
  function node(tag, text) { var n=document.createElement(tag); n.textContent=text==null?'':String(text); return n; }
  function json(value) { return JSON.stringify(value, null, 2); }
  function detail(parent, label, value) {
    var d=node('details'),s=node('summary',label);
    d.dataset.disclosure=(parent.dataset.resultKey||'aggregate')+':'+label;
    d.append(s,node('pre',json(value))); parent.append(d);
  }
  var statusFromObservation=false;
  function message(value) {statusFromObservation=false;if(el('state').textContent!==value)el('state').textContent=value;}
  function observedMessage(value) {message(value);statusFromObservation=true;}
  function id() {
    // Same nonauthority identity fallback as the shipped shell's idempotencyKey.
    if(window.crypto && window.crypto.randomUUID)return 'companion-'+window.crypto.randomUUID();
    return 'companion-'+Date.now()+'-'+Math.random().toString(16).slice(2);
  }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  var context=null, capabilities=[], resources=[], selection=new Map(), frozen=null, reference=null;
  // HTTP guards end at response settlement; read tokens and scope generations own presentation.
  var preparation=null, executeRequest=null, cancelRequest=null, submitted=false, timer=null;
  var generation=0, scopeEpoch=0, listEpoch=0, lastResult=null, readbackUnknown=false, freshRequired=false;
  var readEpoch=0, pendingRead=null, effectEpoch=0, bootstrapped=false, announcedItems=new Map(), aggregateAnnouncement='';
  function foreground() {return !root.hidden && overlayHost.topmost()==='operations';}
  function focusResults() {if(foreground())el('results').focus();}
  function effectPending() {return !!(executeRequest||cancelRequest);}
  function sameReference(ref) {return !!reference && reference.id===ref.id && (reference.digest||'')===(ref.digest||'');}
  function currentScope(scope,ref) {return scope===scopeEpoch && sameReference(ref);}
  function reconcileControls() {
    var active=document.activeElement,counts=lastResult&&lastResult.counts||{};
    var eligible=reference&&reference.digest&&lastResult&&!readbackUnknown&&!freshRequired;
    el('cancel').hidden=!(eligible && counts.pending>0 && !lastResult.cancel_requested);
    el('resume').hidden=!(eligible && lastResult.current_admission==='original' && !lastResult.cancel_requested && (counts.pending>0 || counts.recoverable>0));
    el('resume').disabled=!!(preparation||effectPending());el('cancel').disabled=!!cancelRequest;
    el('new').disabled=effectPending();el('reopen').disabled=effectPending();
    if((active===el('cancel')||active===el('resume')) && (active.hidden||active.disabled))focusResults();
  }
  function syncReferenceURL() {
    var url=new URL(window.location.href);
    if(reference){url.searchParams.set('operation_request',reference.id);if(reference.digest)url.searchParams.set('operation_digest',reference.digest);else url.searchParams.delete('operation_digest');}
    else {url.searchParams.delete('operation_request');url.searchParams.delete('operation_digest');}
    // Keep the shared host's current history marker; references never grant authority.
    window.history.replaceState(window.history.state,'',url);
  }
  var labels={'artifact.create':'Create','artifact.capture':'Capture','artifact.update':'Edit body',
    'artifact.move':'Move','artifact.rename':'Rename','artifact.classify':'Classify',
    'artifact.tags.add':'Add tags','artifact.tags.remove':'Remove tags','collection.reorder':'Order',
    'artifact.archive':'Archive','artifact.restore':'Restore'};
  function support(kind) { return capabilities.find(function(c){return c.resource_id===kind;}); }
  function admitted(kind) { var c=support(kind); return !!c && c.payload && c.payload.support==='supported'; }
  function operationContext() {
    if (!context || !context.active_context_ref || !context.vault_generation) throw new Error('Explicit context unavailable. Choose a vault again.');
    return {active_context_ref:context.active_context_ref,vault_generation:context.vault_generation};
  }
  function command(kind,target,args) {
    return Object.assign(operationContext(), {operation_id:kind,request_id:id(),
      target_binding_id:el('binding').value,targets:target?[{artifact_id:target.resource_id}]:[],arguments:args||{}});
  }
  function invalidate() {
    if (preparation || effectPending() || submitted) return;
    ++generation;frozen=null; el('preview-region').hidden=true; el('confirm').disabled=true;
  }
  function lock(value) { el('intent').disabled=value; el('selection').disabled=value; el('discover').disabled=value; }
  function renderResources() {
    var list=el('resources'); list.textContent='';
    if (!resources.length) list.append(node('p','No resources match this filter.'));
    resources.forEach(function(item) {
      var p=item.payload||{}, row=node('li'), label=node('label'), check=node('input');
      check.type='checkbox'; check.checked=selection.has(item.resource_id);
      check.disabled=!item.resource_id || p.identity_state!=='stable' || submitted;
      check.setAttribute('data-resource-id',item.resource_id||'');
      label.append(check,document.createTextNode(' '+(p.title||p.current_locator||'Untitled')+' · '+(p.current_locator||'locator unavailable')));
      row.append(label,node('p','Identity: '+(item.resource_id||'unavailable')));
      detail(row,'Context and provenance',p);
      check.addEventListener('change',function(){
        invalidate(); if(check.checked) selection.set(item.resource_id,clone(item)); else selection.delete(item.resource_id); renderArguments();
      });
      list.append(row);
    });
    // Filtered-out selections are retained and named; a new query cannot silently broaden/narrow scope.
    var hidden=[...selection.values()].filter(function(item){return !resources.some(function(r){return r.resource_id===item.resource_id;});});
    hidden.forEach(function(item){var row=node('li','Selected outside current filter: '+item.resource_id),button=node('button','Remove from selection');
      button.type='button';button.disabled=submitted;button.addEventListener('click',function(){selection.delete(item.resource_id);invalidate();renderResources();renderArguments();});row.append(button);list.append(row);});
  }
  function renderArguments() {
    var parent=el('arguments'); parent.textContent=''; var kind=el('kind').value;
    if (['artifact.archive','artifact.restore'].includes(kind)) {
      var label=node('label','Source identity');label.htmlFor='operations-source';var input=node('input');input.id='operations-source';parent.append(label,input);return;
    }
    var entries=kind==='artifact.capture'?[null]:[...selection.values()];
    entries.forEach(function(item,index){
      var label=node('label'), input=node(kind==='artifact.update'||kind==='artifact.capture'?'textarea':'input');
      var key=kind==='artifact.update'?'body':kind==='artifact.capture'?'text':kind==='artifact.move'?'destination':'name';
      input.id='operations-argument-'+index;input.dataset.argument=key;input.dataset.resource=item?item.resource_id:'';
      label.htmlFor=input.id; label.textContent=(item?item.resource_id+' · ':'')+({body:'New body',text:'Capture text',destination:'Destination relative to selected vault',name:'New filename'}[key]);
      parent.append(label,input);
    });
    if (!entries.length) parent.append(node('p','Select at least one resource.'));
  }
  async function listResources() {
    if(submitted)return;
    if(!admitted('artifact.list')) throw new Error('artifact.list unavailable');
    var scope=scopeEpoch, query=++listEpoch;
    try {
      var result=await api.invoke(command('artifact.list',null,{query:el('filter').value,limit:250}));
      if(scope!==scopeEpoch || query!==listEpoch || submitted)return;
      if (!['succeeded','degraded_read'].includes(result.status)) throw new Error(json(result));
      resources=result.items||[]; renderResources();
      message('Resources: '+result.status+'. '+(result.warnings||[]).join(' '));
    } catch(error) {if(scope===scopeEpoch && query===listEpoch && !submitted)throw error;}
  }
  async function discover() {
    if(preparation||submitted)return;
    var owner={},scope=scopeEpoch;preparation=owner;message('Loading capabilities and resources…');
    try {
      var result=await api.capabilities();
      if(preparation!==owner || scope!==scopeEpoch)return;
      if(result.status!=='succeeded' || !result.context || !Array.isArray(result.items)) throw new Error(json(result));
      context=clone(result.context); capabilities=result.items; el('capabilities').textContent='';el('kind').textContent='';
      var previous=el('binding').value;el('binding').textContent='';
      ((context.extensions||{}).vault_binding_ids||[]).forEach(function(binding){var opt=node('option',binding);opt.value=binding;el('binding').append(opt);});
      if([...el('binding').options].some(function(o){return o.value===previous;}))el('binding').value=previous;
      capabilities.forEach(function(c){var p=c.payload||{};el('capabilities').append(node('li',c.resource_id+': '+p.support+(p.reason?' · '+p.reason:'')));});
      Object.entries(labels).forEach(function(pair){
        var c=support(pair[0]), p=c&&c.payload||{},option=node('option',pair[1]+' · '+(p.support||'unavailable'));
        option.value=pair[0];option.disabled=p.support!=='supported';el('kind').append(option);
      });
      var first=[...el('kind').options].find(function(o){return !o.disabled;});if(first)el('kind').value=first.value;
      el('intent').disabled=!first || !el('binding').value;
      frozen=null;el('preview-region').hidden=true;el('confirm').disabled=true;renderArguments();await listResources();
    } catch(error) {if(preparation===owner && scope===scopeEpoch){context=null;el('intent').disabled=true;message('Unavailable: '+error.message);}}
    finally {if(preparation===owner)preparation=null;}
  }
  function remember(ref) {
    ref={id:ref.id,digest:ref.digest||undefined};
    if(!sameReference(ref)) {
      ++scopeEpoch;++generation;++listEpoch;preparation=null;++readEpoch;pendingRead=null;
      announcedItems.clear();aggregateAnnouncement='';lastResult=null;readbackUnknown=false;freshRequired=true;
      stopObserving();el('progress').textContent='';el('preview-region').hidden=true;el('confirm').disabled=true;
      el('results').hidden=false;message('Loading durable state for '+ref.id+'…');focusResults();
    }
    reference=clone(ref);el('reference').value=ref.id;el('digest').value=ref.digest||'';
    syncReferenceURL();reconcileControls();
  }
  function scopeLine(label,value) { el('scope').append(node('p',label+': '+value)); }
  async function preview() {
    if(preparation||effectPending()||submitted||!admitted(el('kind').value))return;
    var owner={},scope=scopeEpoch;preparation=owner;lock(true);message('Loading owner preconditions and frozen scope…');el('confirm').disabled=true;
    var epoch=++generation;
    function current() {return preparation===owner && scope===scopeEpoch && epoch===generation && !submitted;}
    try {
      var kind=el('kind').value,targets=[...selection.values()],commands=[];
      if(['artifact.archive','artifact.restore'].includes(kind))targets=[{resource_id:el('source').value,payload:{artifact_class:'source'}}];
      if(kind==='artifact.capture')targets=[null];
      if(!targets.length)throw new Error('Select exact resources first');
      // Read-only preconditions, never a client effect loop.
      for(var target of targets) {
        var args={};
        root.querySelectorAll('[data-argument]').forEach(function(input){if(input.dataset.resource===(target?target.resource_id:''))args[input.dataset.argument]=input.value;});
        if(target && target.payload && target.payload.vault_context && target.payload.vault_context.vault_binding_id!==el('binding').value)throw new Error('Selection spans a different binding; narrow the selection.');
        var intent=command(kind,target,args);if(target&&target.payload&&target.payload.artifact_class==='source')intent.targets[0].artifact_class='source';
        var observed=await api.preconditions(intent);
        if(!current())return;
        if(observed.status!=='observed')throw new Error(json(observed));
        if(observed.operation_id!==kind || !observed.context || observed.context.active_context_ref!==intent.active_context_ref || String(observed.context.vault_generation)!==String(intent.vault_generation))throw new Error('Preconditions changed context. Refresh explicitly.');
        intent.expected_version=observed.expected_version;intent.arguments=clone(observed.arguments);commands.push(intent);
      }
      var batch=null;
      if(commands.length>1) {
        var cap=support('operation.batch'),ce=cap&&cap.payload||{};
        if(!admitted('operation.batch') || !(ce.supported_kinds||[]).includes(kind) || commands.length>ce.max_targets)throw new Error('This selection is outside the advertised finite batch boundary.');
        var batchIntent=Object.assign(operationContext(),{batch_id:id(),operation_id:kind,target_binding_id:el('binding').value,
          limit:commands.length,partial_success_policy:ce.partial_success_policy,
          items:commands.map(function(c){return {request_id:c.request_id,artifact_id:c.targets[0].artifact_id,expected_version:c.expected_version,arguments:c.arguments};})});
        batch=await api.previewBatch(batchIntent);
        if(!current())return;
        if(!batch.digest || batch.current_admission!=='original' || batch.operation_id!==kind || batch.cardinality!==commands.length)throw new Error(json(batch));
      }
      if(!current())return;
      frozen=clone({commands:commands,batch:batch});el('scope').textContent='';
      scopeLine('Operation / effect',kind);scopeLine('Context',commands[0].active_context_ref+' · generation '+commands[0].vault_generation);
      scopeLine('Vault binding',commands[0].target_binding_id);scopeLine('Cardinality',batch?batch.cardinality:1);
      scopeLine('Maximum count',batch?batch.limit:1);scopeLine('Partial success policy',batch?batch.partial_success_policy:'single operation');
      scopeLine('Reversibility / uncertainty','Only owner-declared receipt and recovery evidence establishes reversibility. Preflight reserves no effect.');
      detail(el('scope'),'Exact targets, versions and intended changes',commands);
      if(batch){detail(el('scope'),'Runtime policy ceiling, expiry and revocation',batch.policy_ceiling);scopeLine('Confirmation digest',batch.digest);}
      else scopeLine('Policy ceiling','Existing runtime authority only; revalidated at execution. No new delegation is granted.');
      el('preview-region').hidden=false;el('confirm').disabled=false;if(foreground())el('preview-region').focus();message('Frozen scope ready. Nothing has executed.');
    } catch(error) {if(current()){frozen=null;lock(false);message('Preview refused: '+error.message);}}
    finally {if(preparation===owner)preparation=null;}
  }
  function stopObserving() {clearInterval(timer);timer=null;}
  function observePending() {
    if(!root.hidden && reference && !readbackUnknown && (executeRequest || (reference.digest && lastResult && lastResult.counts && lastResult.counts.pending>0))) {
      if(timer===null)timer=setInterval(function(){inspect(true);},1000);
    } else stopObserving();
  }
  function itemFacts(item,outcome) {
    var c=outcome&&outcome.convergence||{},r=outcome&&outcome.receipt||{},recovery=outcome&&outcome.recovery||{};
    return {state:item.state||'not declared',outcome:outcome&&outcome.status||'not declared',
      'source effect':c.source_effect||'not declared',store:c.store||'not declared',index:c.index||'not declared',links:c.link||'not declared',
      'receipt identity':r.receipt_id||'not declared','receipt status':r.status||'not declared',
      'recovery action':recovery.action||'not declared','recovery instructions':recovery.instructions||'not declared'};
  }
  function renderResult(result) {
    var restoredRead=readbackUnknown;readbackUnknown=false;freshRequired=false;
    if(lastResult && json(lastResult)===json(result) && !restoredRead) {
      if(!statusFromObservation)observedMessage(aggregateAnnouncement);
      reconcileControls();observePending();return;
    }
    var parent=el('progress'),active=document.activeElement;
    var focused=parent.contains(active),disclosure=focused && active.closest('details[data-disclosure]');
    var focusedKey=disclosure && disclosure.dataset.disclosure;
    var openKeys=new Set([...parent.querySelectorAll('details[data-disclosure]')].filter(function(d){return d.open;}).map(function(d){return d.dataset.disclosure;}));
    var changes=[];
    lastResult=clone(result);el('results').hidden=false;parent.textContent='';
    parent.append(node('p','Runtime status: '+(result.status||'unknown')));
    if(result.counts)detail(parent,'Runtime counts',result.counts);
    if(result.current_admission)parent.append(node('p','Current admission: '+result.current_admission));
    if(result.cancel_requested!==undefined)parent.append(node('p','Cancellation requested: '+result.cancel_requested+'; completed effects retain their receipts.'));
    var items=reference&&reference.digest?result.items||[]:[{request_id:result.request_id,outcome:result}];
    items.forEach(function(item){
      var row=node('section'),outcome=item.outcome,key=item.request_id||item.artifact_id||result.request_id;
      row.dataset.resultKey=key;
      var facts=itemFacts(item,outcome),previous=announcedItems.get(key);
      var deltas=Object.keys(facts).filter(function(name){return !previous || previous[name]!==facts[name];});
      if(deltas.length) {
        changes.push((item.artifact_id||item.request_id||'Operation')+': '+(item.state||outcome&&outcome.status||'unknown')+' · '+deltas.map(function(name){return name+' '+(previous?previous[name]+' → ':'')+facts[name];}).join(', '));
        announcedItems.set(key,facts);
      }
      row.setAttribute('aria-label','Result '+(item.artifact_id||item.request_id));
      row.append(node('h4',(item.artifact_id||item.request_id||'Operation')+' · '+(outcome?outcome.status:item.state||'unknown')));
      if(outcome){
        var c=outcome.convergence||{},receipt=outcome.receipt||{};
        row.append(node('p','Source effect: '+(c.source_effect||'not declared')+' · Receipt: '+(receipt.receipt_id||'not declared')+' · Receipt status: '+(receipt.status||'not declared')));
        row.append(node('p','Convergence: store '+(c.store||'not declared')+' · index '+(c.index||'not declared')+' · links '+(c.link||'not declared')));
        if(outcome.conflict)detail(row,'Conflict evidence',outcome.conflict);
        if(outcome.warnings&&outcome.warnings.length)row.append(node('p','Warnings: '+outcome.warnings.join(' · ')));
        if(outcome.recovery)detail(row,'Runtime recovery',outcome.recovery);
        detail(row,'Receipt, provenance and complete typed outcome',outcome);
      } else row.append(node('p','No outcome declared yet.'));
      parent.append(row);
    });
    detail(parent,'Complete runtime response',result);reconcileControls();
    var disclosures=[...parent.querySelectorAll('details[data-disclosure]')];
    disclosures.forEach(function(d){if(openKeys.has(d.dataset.disclosure))d.open=true;});
    if(foreground() && focused) {
      var restored=disclosures.find(function(d){return d.dataset.disclosure===focusedKey;});
      if(restored)restored.querySelector('summary').focus();else focusResults();
    }
    var aggregate='Operation '+(result.status||'unknown')+(result.counts?' · '+Object.entries(result.counts).map(function(p){return p.join(': ');}).join(', '):'')+
      (result.cancel_requested!==undefined?' · cancellation requested: '+result.cancel_requested:'')+(result.current_admission?' · admission: '+result.current_admission:'');
    if(changes.length || aggregate!==aggregateAnnouncement || restoredRead || !statusFromObservation)observedMessage(aggregate+(changes.length?' · '+changes.join('; '):'')+(restoredRead?' · Durable readback restored.':''));
    aggregateAnnouncement=aggregate;observePending();
  }
  async function inspect(quiet, force) {
    if(root.hidden || !reference || (quiet&&!force&&pendingRead===readEpoch))return;
    var epoch=++readEpoch,scope=scopeEpoch,ref=clone(reference);pendingRead=epoch;
    function current() {return epoch===readEpoch && currentScope(scope,ref) && !root.hidden;}
    try {
      var result=ref.digest?await api.inspectBatch(ref.id,ref.digest):await api.receipt(ref.id);
      if(!current())return;renderResult(result);if(!quiet)focusResults();return result;
    } catch(error) {
      if(!current())return;stopObserving();readbackUnknown=true;freshRequired=true;el('results').hidden=false;reconcileControls();
      if(!lastResult){el('progress').textContent='';el('progress').append(node('p','No durable state was returned by this read. Nothing has been retried.'));}
      message('Current readback unavailable; latest progress unknown. Retained reference '+ref.id+'. '+error.message);
      if(!quiet)focusResults();
    } finally {if(pendingRead===epoch)pendingRead=null;}
  }
  function settleMutation(scope,ref,effect,observed,result,error,label) {
    if(!currentScope(scope,ref) || effect!==effectEpoch)return;
    if(!error && observed===readEpoch && !root.hidden) {++readEpoch;renderResult(result);return;}
    freshRequired=true;reconcileControls();
    if(error)message(label+' response unavailable; inspecting durable state. '+error.message);
    // This read has its own ownership; no settled HTTP guard awaits its transport.
    if(!root.hidden)inspect(true,true);
  }
  async function execute(resume) {
    reconcileControls();
    if(preparation || effectPending() || (!resume && (!frozen||submitted)))return;
    if(resume && (!lastResult || el('resume').hidden))return;
    submitted=true;lock(true);el('confirm').disabled=true;el('preview-region').hidden=true;el('results').hidden=false;focusResults();
    if(!resume)remember(frozen.batch?{id:frozen.batch.batch_id,digest:frozen.batch.digest}:{id:frozen.commands[0].request_id});
    var owner={},scope=scopeEpoch,ref=clone(reference),effect=++effectEpoch,observed=++readEpoch,result,error;
    executeRequest=owner;reconcileControls();message('Execution requested. Awaiting owner receipt…');observePending();
    try {result=ref.digest?await api.executeBatch(ref.id,ref.digest):await api.invoke(frozen.commands[0]);}
    catch(failure) {error=failure;}
    finally {if(executeRequest===owner)executeRequest=null;reconcileControls();}
    settleMutation(scope,ref,effect,observed,result,error,'Execution');observePending();
  }
  async function cancel() {
    reconcileControls();
    if(cancelRequest || !reference || !reference.digest || el('cancel').hidden)return;
    var owner={},scope=scopeEpoch,ref=clone(reference),effect=++effectEpoch,observed=++readEpoch,result,error;
    cancelRequest=owner;reconcileControls();focusResults();
    try {result=await api.cancelBatch(ref.id,ref.digest);}
    catch(failure) {error=failure;}
    finally {if(cancelRequest===owner)cancelRequest=null;reconcileControls();}
    settleMutation(scope,ref,effect,observed,result,error,'Cancellation');observePending();
  }
  function safe(action){return function(){Promise.resolve().then(action).catch(function(error){message(error.message);});};}
  el('discover').onclick=safe(discover);el('list').onclick=safe(listResources);
  el('kind').onchange=function(){invalidate();renderArguments();};el('binding').onchange=invalidate;
  el('arguments').addEventListener('input',invalidate);el('preview').onclick=safe(preview);
  el('confirm').onclick=safe(function(){return execute(false);});el('resume').onclick=safe(function(){return execute(true);});
  el('cancel').onclick=safe(cancel);el('inspect').onclick=safe(function(){return inspect(false);});
  el('back').onclick=function(){if(submitted)return;frozen=null;el('preview-region').hidden=true;lock(false);if(foreground())el('preview').focus();};
  el('new').onclick=safe(function(){
    if(effectPending())return;stopObserving();++scopeEpoch;++generation;++listEpoch;++effectEpoch;++readEpoch;pendingRead=null;preparation=null;
    submitted=false;frozen=null;reference=null;lastResult=null;readbackUnknown=false;freshRequired=false;announcedItems.clear();aggregateAnnouncement='';
    syncReferenceURL();el('preview-region').hidden=true;el('confirm').disabled=true;el('results').hidden=true;lock(false);reconcileControls();renderResources();
    if(foreground())el('discover').focus();return discover();
  });
  el('reopen').onclick=safe(function(){
    if(effectPending())return;submitted=true;frozen=null;preparation=null;++generation;lock(true);
    el('preview-region').hidden=true;el('confirm').disabled=true;
    remember({id:el('reference').value.trim(),digest:el('digest').value.trim()||undefined});focusResults();return inspect(false,true);
  });
  window.overlayHost.register('operations',{
    open:function(){
      root.hidden=false;
      if(!bootstrapped){
        bootstrapped=true;var params=new URL(window.location.href).searchParams;
        if(params.get('operation_request')){submitted=true;lock(true);remember({id:params.get('operation_request'),digest:params.get('operation_digest')||undefined});}
      }
      syncReferenceURL();
      if(reference){freshRequired=true;reconcileControls();el('results').hidden=false;focusResults();inspect(true,true);}
      else if(frozen){if(foreground())el('preview-region').focus();}
      else {if(foreground())el('discover').focus();discover();}
    },
    close:function(){root.hidden=true;++readEpoch;pendingRead=null;freshRequired=!!reference;stopObserving();}
  });
})();
</script>"""
