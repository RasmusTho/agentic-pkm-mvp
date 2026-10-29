"""Companion aggregate operations view; all effects use operationsClient.

Reuse: shared overlay frame, receipts modal geometry and disclosures, standing
question review list/actions, and the shell's labelled native form controls.
No application/domain imports, durable effect state or per-item effect loop.
"""
from companion_ui.workspace.overlay_frame import overlay_frame_header, overlay_frame_root_attrs


def operations_launcher_markup() -> str:
    return """<button type="button" class="btn btn--secondary" data-testid="operations-open"
      onclick="overlayHost.mount('operations')">Operations</button>
      <noscript><p>Operations requires JavaScript. No operation has been submitted.</p></noscript>"""


def operations_workspace_markup() -> str:
    frame = overlay_frame_root_attrs(overlay_id="operations", position="center")
    header = overlay_frame_header(overlay_id="operations", title="Operations")
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
  <div class="operations-panel">__HEADER__
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
</div>""".replace("__FRAME__", frame).replace("__HEADER__", header)


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
  function message(value) { if(el('state').textContent!==value) el('state').textContent=value; }
  function id() { return 'companion-' + crypto.randomUUID(); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  var context=null, capabilities=[], resources=[], selection=new Map(), frozen=null, reference=null;
  var cancelBusy=false, busy=false, submitted=false, timer=null, generation=0, lastResult=null, readbackUnknown=false, readEpoch=0, pendingRead=null, effectEpoch=0, announcedItems=new Map(), aggregateAnnouncement='';
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
    if (busy || submitted) return;
    frozen=null; el('preview-region').hidden=true; el('confirm').disabled=true;
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
    if(!admitted('artifact.list')) throw new Error('artifact.list unavailable');
    var result=await api.invoke(command('artifact.list',null,{query:el('filter').value,limit:250}));
    if (!['succeeded','degraded_read'].includes(result.status)) throw new Error(json(result));
    resources=result.items||[]; renderResources();
    message('Resources: '+result.status+'. '+(result.warnings||[]).join(' '));
  }
  async function discover() {
    if(busy||submitted)return; busy=true; message('Loading capabilities and resources…');
    try {
      var result=await api.capabilities();
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
      invalidate();renderArguments();await listResources();
    } catch(error) {context=null;el('intent').disabled=true; message('Unavailable: '+error.message);}
    finally {busy=false;}
  }
  function remember(ref) {
    if(!reference || reference.id!==ref.id || reference.digest!==ref.digest) {
      ++readEpoch;announcedItems.clear();aggregateAnnouncement='';lastResult=null;readbackUnknown=false;
      stopObserving();el('progress').textContent='';el('cancel').hidden=true;el('resume').hidden=true;
      el('results').hidden=false;message('Loading durable state for '+ref.id+'…');
      if(!root.hidden)el('results').focus();
    }
    reference=clone(ref);el('reference').value=ref.id;el('digest').value=ref.digest||'';
    var url=new URL(window.location.href);url.searchParams.set('operation_request',ref.id);
    if(ref.digest)url.searchParams.set('operation_digest',ref.digest);else url.searchParams.delete('operation_digest');
    // Only non-authority references. Effect state is always rehydrated from the server.
    window.history.replaceState(window.history.state,'',url);
  }
  function scopeLine(label,value) { el('scope').append(node('p',label+': '+value)); }
  async function preview() {
    if(busy||submitted||!admitted(el('kind').value))return;
    busy=true;lock(true);message('Loading owner preconditions and frozen scope…');el('confirm').disabled=true;
    var epoch=++generation;
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
        if(!batch.digest || batch.current_admission!=='original' || batch.operation_id!==kind || batch.cardinality!==commands.length)throw new Error(json(batch));
      }
      if(epoch!==generation)throw new Error('Selection changed during preview');
      frozen=clone({commands:commands,batch:batch});el('scope').textContent='';
      scopeLine('Operation / effect',kind);scopeLine('Context',commands[0].active_context_ref+' · generation '+commands[0].vault_generation);
      scopeLine('Vault binding',commands[0].target_binding_id);scopeLine('Cardinality',batch?batch.cardinality:1);
      scopeLine('Maximum count',batch?batch.limit:1);scopeLine('Partial success policy',batch?batch.partial_success_policy:'single operation');
      scopeLine('Reversibility / uncertainty','Only owner-declared receipt and recovery evidence establishes reversibility. Preflight reserves no effect.');
      detail(el('scope'),'Exact targets, versions and intended changes',commands);
      if(batch){detail(el('scope'),'Runtime policy ceiling, expiry and revocation',batch.policy_ceiling);scopeLine('Confirmation digest',batch.digest);}
      else scopeLine('Policy ceiling','Existing runtime authority only; revalidated at execution. No new delegation is granted.');
      el('preview-region').hidden=false;el('confirm').disabled=false;el('preview-region').focus();message('Frozen scope ready. Nothing has executed.');
    } catch(error) {frozen=null;lock(false);message('Preview refused: '+error.message);}
    finally {busy=false;}
  }
  function stopObserving() {clearInterval(timer);timer=null;}
  function observePending() {
    if(!root.hidden && reference && reference.digest && lastResult && lastResult.counts && lastResult.counts.pending>0) {
      if(timer===null)timer=setInterval(function(){inspect(true);},1000);
    } else stopObserving();
  }
  function renderResult(result) {
    if(lastResult && json(lastResult)===json(result) && !readbackUnknown) {observePending();return;}
    var restoredRead=readbackUnknown;readbackUnknown=false;
    var parent=el('progress'),active=document.activeElement;
    var focused=parent.contains(active),disclosure=focused && active.closest('details[data-disclosure]');
    var focusedKey=disclosure && disclosure.dataset.disclosure;
    var openKeys=new Set([...parent.querySelectorAll('details[data-disclosure]')].filter(function(d){return d.open;}).map(function(d){return d.dataset.disclosure;}));
    var focusAction=active===el('cancel') || active===el('resume');
    var changes=[];
    lastResult=clone(result);el('results').hidden=false;parent.textContent='';
    parent.append(node('p','Runtime status: '+(result.status||'unknown')));
    if(result.counts)detail(parent,'Runtime counts',result.counts);
    if(result.current_admission)parent.append(node('p','Current admission: '+result.current_admission));
    if(result.cancel_requested!==undefined)parent.append(node('p','Cancellation requested: '+result.cancel_requested+'; completed effects retain their receipts.'));
    var items=reference&&reference.digest?result.items||[]:[{request_id:result.request_id,outcome:result}];
    items.forEach(function(item){
      var row=node('section'),outcome=item.outcome;
      var key=item.request_id||item.artifact_id||result.request_id;
      row.dataset.resultKey=key;
      var itemState=json([item.state,outcome&&outcome.status,outcome&&outcome.convergence,outcome&&outcome.receipt,outcome&&outcome.recovery]);
      if(announcedItems.get(key)!==itemState) {
        changes.push((item.artifact_id||item.request_id||'Operation')+': '+(item.state||'')+' '+(outcome?outcome.status:''));
        announcedItems.set(key,itemState);
      }
      row.setAttribute('aria-label','Result '+(item.artifact_id||item.request_id));
      row.append(node('h4',(item.artifact_id||item.request_id||'Operation')+' · '+(outcome?outcome.status:item.state||'unknown')));
      if(outcome){
        var c=outcome.convergence||{};row.append(node('p','Source effect: '+(c.source_effect||'not declared')+' · Receipt: '+(outcome.receipt?outcome.receipt.receipt_id||'recorded':'not declared')));
        row.append(node('p','Convergence: store '+(c.store||'not declared')+' · index '+(c.index||'not declared')+' · links '+(c.link||'not declared')));
        if(outcome.conflict)detail(row,'Conflict evidence',outcome.conflict);
        if(outcome.warnings&&outcome.warnings.length)row.append(node('p','Warnings: '+outcome.warnings.join(' · ')));
        if(outcome.recovery)detail(row,'Runtime recovery',outcome.recovery);
        detail(row,'Receipt, provenance and complete typed outcome',outcome);
      } else row.append(node('p','No outcome declared yet.'));
      parent.append(row);
    });
    detail(parent,'Complete runtime response',result);
    var isBatch=!!(reference&&reference.digest),counts=result.counts||{};
    el('cancel').hidden=!(isBatch && counts.pending>0 && !result.cancel_requested);
    el('resume').hidden=!(isBatch && result.current_admission==='original' && !result.cancel_requested && (counts.pending>0 || counts.recoverable>0));
    el('resume').disabled=busy||cancelBusy;el('cancel').disabled=cancelBusy;
    var disclosures=[...parent.querySelectorAll('details[data-disclosure]')];
    disclosures.forEach(function(d){if(openKeys.has(d.dataset.disclosure))d.open=true;});
    if(!root.hidden && focused) {
      var restored=disclosures.find(function(d){return d.dataset.disclosure===focusedKey;});
      if(restored)restored.querySelector('summary').focus();else el('results').focus();
    } else if(!root.hidden && focusAction && active.hidden)el('results').focus();
    var aggregate='Operation '+(result.status||'unknown')+(result.counts?' · '+Object.entries(result.counts).map(function(p){return p.join(': ');}).join(', '):'');
    if(changes.length || aggregate!==aggregateAnnouncement || restoredRead)message(aggregate+(changes.length?' · '+changes.join('; '):'')+(restoredRead?' · Durable readback restored.':''));
    aggregateAnnouncement=aggregate;observePending();
  }
  async function inspect(quiet, force) {
    if(!reference || (quiet&&!force&&pendingRead===readEpoch))return;
    var epoch=++readEpoch;pendingRead=epoch;
    try {var result=reference.digest?await api.inspectBatch(reference.id,reference.digest):await api.receipt(reference.id);if(epoch!==readEpoch)return;renderResult(result);if(!quiet&&!root.hidden)el('results').focus();return result;}
    catch(error){if(epoch!==readEpoch)return;stopObserving();readbackUnknown=true;el('cancel').hidden=true;el('resume').hidden=true;
      el('results').hidden=false;
      if(!lastResult){el('progress').textContent='';el('progress').append(node('p','No durable state was returned by this read. Nothing has been retried.'));}
      message('Current readback unavailable; latest progress unknown. Retained reference '+reference.id+'. '+error.message);
      if(!quiet&&!root.hidden)el('results').focus();}
    finally {if(pendingRead===epoch)pendingRead=null;}
  }
  async function execute(resume) {
    if(busy || cancelBusy || (!resume && (!frozen||submitted)))return;
    if(resume && (!lastResult || el('resume').hidden))return;
    var effect=++effectEpoch;++readEpoch;
    busy=true;submitted=true;lock(true);el('confirm').disabled=true;el('resume').disabled=true;
    el('preview-region').hidden=true;el('results').hidden=false;el('results').focus();message('Execution requested. Awaiting owner receipt…');
    if(!resume)remember(frozen.batch?{id:frozen.batch.batch_id,digest:frozen.batch.digest}:{id:frozen.commands[0].request_id});
    message('Execution requested. Awaiting owner receipt…');
    clearInterval(timer);timer=setInterval(function(){inspect(true);},1000);
    var observed=readEpoch;
    try {var result=reference.digest?await api.executeBatch(reference.id,reference.digest):await api.invoke(frozen.commands[0]);
      if(effect===effectEpoch){if(observed===readEpoch){++readEpoch;renderResult(result);}else await inspect(true,true);}}
    catch(error){if(effect===effectEpoch){message('Execution response unavailable; inspecting durable state. '+error.message);await inspect(true);}}
    finally {busy=false;el('resume').disabled=cancelBusy;}
  }
  async function cancel() {
    if(cancelBusy || !reference || !reference.digest || el('cancel').hidden)return;
    ++effectEpoch;++readEpoch;var observed=readEpoch;cancelBusy=true;el('new').disabled=true;
    el('cancel').disabled=true;el('results').focus();
    try {var result=await api.cancelBatch(reference.id,reference.digest);if(observed===readEpoch){++readEpoch;renderResult(result);}else await inspect(true,true);if(!root.hidden)el('results').focus();}
    catch(error){message('Cancellation outcome unknown. '+error.message);await inspect(true);}
    finally {cancelBusy=false;el('new').disabled=false;el('cancel').disabled=false;el('resume').disabled=busy;}
  }
  function safe(action){return function(){Promise.resolve().then(action).catch(function(error){message(error.message);});};}
  el('discover').onclick=safe(discover);el('list').onclick=safe(listResources);
  el('kind').onchange=function(){invalidate();renderArguments();};el('binding').onchange=invalidate;
  el('arguments').addEventListener('input',invalidate);el('preview').onclick=safe(preview);
  el('confirm').onclick=safe(function(){return execute(false);});el('resume').onclick=safe(function(){return execute(true);});
  el('cancel').onclick=safe(cancel);el('inspect').onclick=safe(function(){return inspect(false);});
  el('back').onclick=function(){frozen=null;el('preview-region').hidden=true;lock(false);el('preview').focus();};
  el('new').onclick=safe(function(){
    if(busy||cancelBusy)return;stopObserving(); ++readEpoch;submitted=false;frozen=null;reference=null;lastResult=null;readbackUnknown=false;
    var url=new URL(window.location.href);url.searchParams.delete('operation_request');url.searchParams.delete('operation_digest');
    window.history.replaceState(window.history.state,'',url);el('results').hidden=true;lock(false);renderResources();el('discover').focus();return discover();
  });
  el('reopen').onclick=safe(function(){
    if(busy||cancelBusy)return;submitted=true;frozen=null;lock(true);
    remember({id:el('reference').value.trim(),digest:el('digest').value.trim()||undefined});return inspect(false);
  });
  overlayHost.register('operations',{
    open:function(){root.hidden=false;el('discover').focus();
      var params=new URL(window.location.href).searchParams;
      if(!reference&&params.get('operation_request')){submitted=true;lock(true);remember({id:params.get('operation_request'),digest:params.get('operation_digest')||undefined});inspect(false);}
      else if(reference)inspect(true);else if(frozen)el('preview-region').focus();else discover();
    },
    close:function(){root.hidden=true;stopObserving();}
  });
})();
</script>"""
