/** Selected-session evidence. No domain rules, filesystem discovery or execution. */
import {projectPrimeContext} from './context-projection.js';
const ID = /^[A-Za-z0-9][A-Za-z0-9._:|+-]{0,255}$(?![\s\S])/;
const REVISION = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
export const CONTEXT_CHECKPOINT_VERSION = 'asterion.prime-context-checkpoint/v1';
type RecordValue = Record<string,unknown>;
const record = (value:unknown): RecordValue | undefined => typeof value==='object' && value!==null && !Array.isArray(value) ? value as RecordValue : undefined;
export interface NativeContextArchive {sessionId:string; entries:RecordValue[];}
export interface ContextCheckpointReceipt {
  version:typeof CONTEXT_CHECKPOINT_VERSION; session_id:string; source_tool_call_id:string;
  coverage_through_entry_id:string|null; notes_revision:string;
}
export function nativeContextArchive(context:unknown): NativeContextArchive | undefined {
  try {
    const manager=record(record(context)?.sessionManager);
    if (!manager || typeof manager.getBranch!=='function' || typeof manager.getSessionId!=='function') return undefined;
    const sessionId=manager.getSessionId(), entries=manager.getBranch();
    if(typeof sessionId!=='string' || !ID.test(sessionId) || !Array.isArray(entries)) return undefined;
    const seen=new Set<string>(); let previous:string|null=null;
    for(const raw of entries) {
      const entry=record(raw);
      if(!entry || typeof entry.id!=='string' || !ID.test(entry.id) || seen.has(entry.id)
        || entry.parentId!==previous) return undefined;
      seen.add(entry.id);previous=entry.id;
    }
    return {sessionId,entries};
  } catch {return undefined;}
}
function publicContent(value:unknown):unknown {
  if(typeof value==='string') return value;
  if(!Array.isArray(value)) throw new Error('archive content unavailable');
  return value.flatMap<RecordValue>(raw=>{
    const block=record(raw);
    if(!block) throw new Error('archive block unavailable');
    if(block.type==='thinking') return []; // Hidden reasoning/signatures are never a read surface.
    if(block.type==='text' && typeof block.text==='string') return [{type:'text',text:block.text}];
    if(block.type==='toolCall' && typeof block.id==='string' && typeof block.name==='string')
      return [{type:'toolCall',id:block.id,name:block.name,arguments:block.arguments}];
    if(block.type==='image' && typeof block.data==='string' && typeof block.mimeType==='string')
      return [{type:'image',data:block.data,mimeType:block.mimeType}];
    throw new Error('archive block unavailable');
  });
}
/** Preserve native ordered system patches and loadouts without private metadata. */
export function archiveSystemMessage(raw:unknown):RecordValue {
  const message=record(raw);
  if(message?.role!=='system') throw new Error('archive system unavailable');
  projectPrimeContext([message]);
  const value:RecordValue={role:'system',content:publicContent(message.content)};
  for(const key of ['sections','toolsAdded','toolsRemoved']) {
    if(message[key]!==undefined) value[key]=JSON.parse(JSON.stringify(message[key]));
  }
  return value;
}
export function archiveMessage(raw:unknown):RecordValue {
  const message=record(raw);
  if(!message || !['user','assistant','toolResult','custom','system'].includes(String(message.role))) throw new Error('archive message unavailable');
  if(message.role==='system') return archiveSystemMessage(message);
  const value:RecordValue={role:message.role,content:publicContent(message.content)};
  if(message.role==='toolResult') {
    if(typeof message.toolCallId!=='string' || typeof message.toolName!=='string' || typeof message.isError!=='boolean') throw new Error('archive result unavailable');
    Object.assign(value,{toolCallId:message.toolCallId,toolName:message.toolName,isError:message.isError});
  }
  if(message.role==='assistant' && typeof message.stopReason==='string') value.stopReason=message.stopReason;
  if(message.role==='custom' && typeof message.customType==='string') value.customType=message.customType;
  return value;
}
function archivedRows(archive:NativeContextArchive) {
  return archive.entries.filter(entry=>entry.type==='message').map(entry=>({entry,message:archiveMessage(entry.message)}));
}
export function contextArchiveOperation(archive:NativeContextArchive|undefined,request:unknown):RecordValue {
  try {
    const value=record(request);if(!value || !archive) throw new Error();
    const start=value.start??0, limit=value.limit??(value.op==='context_archive_read'?4096:16);
    if(!Number.isSafeInteger(start) || (start as number)<0 || !Number.isSafeInteger(limit) || (limit as number)<1) throw new Error();
    if(value.op==='context_archive_list') {
      if(Object.keys(value).some(key=>!['op','start','limit'].includes(key)) || (limit as number)>32) throw new Error();
      const rows=archivedRows(archive), items=rows.slice(start as number,(start as number)+(limit as number)).map(({entry,message},offset)=>({
        ref:{session_id:archive.sessionId,entry_id:entry.id},role:message.role,ordinal:(start as number)+offset,
        content_bytes:Buffer.byteLength(JSON.stringify(message),'utf8')}));
      return {status:'ok',session_id:archive.sessionId,items,total:rows.length,next_start:(start as number)+items.length<rows.length?(start as number)+items.length:null};
    }
    if(value.op!=='context_archive_read' || Object.keys(value).some(key=>!['op','ref','start','limit'].includes(key)) || (limit as number)>16384) throw new Error();
    const ref=record(value.ref);
    if(!ref || Object.keys(ref).sort().join(',')!=='entry_id,session_id' || ref.session_id!==archive.sessionId) throw new Error();
    const entry=archive.entries.find(entry=>entry.id===ref.entry_id && entry.type==='message');if(!entry) throw new Error();
    const full=JSON.stringify(archiveMessage(entry.message)), text=full.slice(start as number,(start as number)+(limit as number));
    return {status:'ok',ref,format:'model-message-json/v1',text,start,total_characters:full.length,next_start:(start as number)+text.length<full.length?(start as number)+text.length:null};
  } catch {return {status:'rejected',reason:'context-archive-unavailable'};}
}
interface Group {start:number;end:number;entries:RecordValue[];calls:string[];complete:boolean;negative:boolean;unknown:boolean;}
function marker(message:RecordValue) {
  const details=record(message.details), value=record(details?.context_interaction);
  return value?.version==='asterion.prime-context-interaction/v1' ? value : undefined;
}
function groups(archive:NativeContextArchive):Group[]|undefined {
  const messages=archive.entries.map((entry,index)=>({entry,index,message:entry.type==='message'?record(entry.message):undefined})).filter(row=>row.message);
  const callCounts=new Map<string,number>(),resultCounts=new Map<string,number>();
  for(const {message} of messages) {
    if(message!.role==='assistant' && Array.isArray(message!.content)) for(const raw of message!.content) {
      const block=record(raw);if(block?.type==='toolCall' && typeof block.id==='string') callCounts.set(block.id,(callCounts.get(block.id)??0)+1);
    }
    if(message!.role==='toolResult' && typeof message!.toolCallId==='string') resultCounts.set(message!.toolCallId,(resultCounts.get(message!.toolCallId)??0)+1);
  }
  if([...callCounts.values(),...resultCounts.values()].some(count=>count!==1)) return undefined;
  const result:Group[]=[];const coveredResults=new Set<string>();
  for(let position=0;position<messages.length;position++) {
    const row=messages[position]!, message=row.message!;
    if(message.role!=='assistant' || !Array.isArray(message.content)) continue;
    const expected=new Map<string,string>();
    for(const raw of message.content) {
      const call=record(raw);if(call?.type!=='toolCall') continue;
      if(typeof call.id!=='string' || !ID.test(call.id) || typeof call.name!=='string' || expected.has(call.id)) return undefined;
      expected.set(call.id,call.name);
    }
    if(!expected.size) {
      result.push({start:row.index,end:row.index,entries:[row.entry],calls:[],complete:true,negative:false,unknown:false});
      continue;
    }
    const group:Group={start:row.index,end:row.index,entries:[row.entry],calls:[...expected.keys()],complete:false,negative:false,unknown:false};
    const settled=new Set<string>();
    for(let next=position+1;next<messages.length;next++) {
      const candidate=messages[next]!, feedback=candidate.message!;
      if(feedback.role==='system') continue;
      if(feedback.role!=='toolResult' || typeof feedback.toolCallId!=='string' || expected.get(feedback.toolCallId)!==feedback.toolName || settled.has(feedback.toolCallId)) break;
      group.entries.push(candidate.entry);group.end=candidate.index;settled.add(feedback.toolCallId);coveredResults.add(feedback.toolCallId);
      const status=marker(feedback);group.negative ||= feedback.isError===true || status?.feedback==='negative';group.unknown ||= status?.effect==='unknown';
      if(settled.size===expected.size) {group.complete=!['error','aborted'].includes(String(message.stopReason));position=next;break;}
    }
    result.push(group);
  }
  if(messages.some(({message})=>message!.role==='toolResult' && !coveredResults.has(String(message!.toolCallId)))) return undefined;
  return result;
}
export function parseContextCheckpoint(value:unknown):ContextCheckpointReceipt|undefined {
  const item=record(value);
  if(!item || Object.keys(item).sort().join(',')!=='coverage_through_entry_id,notes_revision,session_id,source_tool_call_id,version'
    || item.version!==CONTEXT_CHECKPOINT_VERSION || ![item.session_id,item.source_tool_call_id].every(v=>typeof v==='string' && ID.test(v))
    || !(item.coverage_through_entry_id===null || typeof item.coverage_through_entry_id==='string' && ID.test(item.coverage_through_entry_id))
    || typeof item.notes_revision!=='string' || !REVISION.test(item.notes_revision)) return undefined;
  return {version:CONTEXT_CHECKPOINT_VERSION,session_id:item.session_id as string,source_tool_call_id:item.source_tool_call_id as string,
    coverage_through_entry_id:item.coverage_through_entry_id as string|null,notes_revision:item.notes_revision};
}
export function createContextCheckpoint(archive:NativeContextArchive|undefined,toolCallId:string,revision:string):ContextCheckpointReceipt|undefined {
  if(!archive || !ID.test(toolCallId) || !REVISION.test(revision)) return undefined;
  const all=groups(archive),source=all?.find(group=>group.calls.includes(toolCallId));if(!all || !source) return undefined;
  const before=all.filter(group=>group.end<source.start);
  if(before.some(group=>!group.complete)) return undefined;
  return {version:CONTEXT_CHECKPOINT_VERSION,session_id:archive.sessionId,source_tool_call_id:toolCallId,
    coverage_through_entry_id:before.at(-1)?.entries.at(-1)?.id as string??null,notes_revision:revision};
}
export function primaryContextHistory(messages:readonly unknown[],archive:NativeContextArchive|undefined,receipt:ContextCheckpointReceipt) {
  if(!archive || archive.sessionId!==receipt.session_id || archive.entries.some(entry=>entry.type==='context_edit')) return undefined;
  const all=groups(archive),source=all?.find(group=>group.calls.includes(receipt.source_tool_call_id));
  const actual=createContextCheckpoint(archive,receipt.source_tool_call_id,receipt.notes_revision);
  if(!all || !source?.complete || source.unknown || JSON.stringify(actual)!==JSON.stringify(receipt)) return undefined;
  const sourceResult=source.entries.map(entry=>record(entry.message)).find(message=>message?.toolCallId===receipt.source_tool_call_id);
  const details=record(sourceResult?.details), envelope=record(details?.context_memory);
  if(sourceResult?.isError!==false || envelope?.version!=='asterion.prime-context-memory/v3' || envelope.commit!==true
    || envelope.revision!==receipt.notes_revision || JSON.stringify(parseContextCheckpoint(details?.context_checkpoint))!==JSON.stringify(receipt)) return undefined;
  try {
    // Every message retired or reconstructed has a readable, role-safe original.
    const rows=archivedRows(archive);
    const signatures=new Set(rows.map(({message})=>JSON.stringify(message)));
    for(const raw of messages) {
      const message=record(raw);if(message?.role==='custom' && message.customType==='asterion_context_memory') continue;
      if(['compactionSummary','branchSummary'].includes(String(message?.role))) {
        if(!archive.entries.some(entry=>['compaction','branch_summary'].includes(String(entry.type)) && entry.summary===message?.summary)) return undefined;
      } else if(!signatures.has(JSON.stringify(archiveMessage(raw)))) return undefined;
    }
    const prior=all.filter(group=>group.end<source.start),protectedGroups=new Set(prior.filter(group=>group.calls.length>0).slice(-2));
    const negative=[...prior].reverse().find(group=>group.negative);if(negative) protectedGroups.add(negative);
    for(const group of all) if(group.unknown || !group.complete) protectedGroups.add(group);
    const retired=prior.filter(group=>!protectedGroups.has(group));
    const retiredIds=new Set(retired.flatMap(group=>group.entries.map(entry=>entry.id)));
    // A compacted note-only acknowledgement need not be resurrected. Siblings stay whole.
    const sourceVisible=messages.some(raw=>record(raw)?.toolCallId===receipt.source_tool_call_id);
    if(!sourceVisible && source.calls.length===1) for(const entry of source.entries) retiredIds.add(entry.id);
    // Pi's context hook hides/restores system state itself. Direct projections
    // preserve visible system records verbatim, without reviving hidden old loadouts.
    const visibleSystems=new Set(messages.filter(raw=>record(raw)?.role==='system').map(raw=>JSON.stringify(archiveMessage(raw))));
    const retained=rows.filter(({entry,message})=>!retiredIds.has(entry.id) && (message.role!=='system' || visibleSystems.has(JSON.stringify(message))));
    let insertion=0;retained.forEach(({entry},index)=>{if(archive.entries.indexOf(entry)<=source.end) insertion=index+1;});
    const catalog=JSON.stringify({context_archive:{session_id:archive.sessionId,through_ref:receipt.coverage_through_entry_id===null?null:{session_id:archive.sessionId,entry_id:receipt.coverage_through_entry_id},
      retired_complete_groups:retired.length,list_op:'context_archive_list',read_op:'context_archive_read'}});
    return {messages:retained.map(({entry})=>entry.message),insertion,catalog,retired:retired.length,protectedGroups:protectedGroups.size};
  } catch {return undefined;}
}
