import * as ext from "../dist/ipython-extension.mjs";
import {verifyCompactionLock, guardCompactionImports} from "../../../../tools/build_asterion_prime_compaction_lock.mjs";
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {join, resolve, dirname} from 'node:path';
const root=resolve(dirname(fileURLToPath(import.meta.url)), '../../../../3th-party/prime-agent');
const opts=JSON.parse(process.argv[2]);
const sha=value=>createHash('sha256').update(value).digest('hex');
const verified=verifyCompactionLock(root);
const guard=guardCompactionImports(verified);
const load=name=>import(pathToFileURL(join(root,'packages/coding-agent/dist/core',name)).href);
const compaction=await load('compaction/compaction.js');
const sessionModule=await load('session-manager.js');
const messages=await load('messages.js');
const utils=await load('compaction/utils.js');
const agent=await load('agent-session.js');
const ai=await import(pathToFileURL(join(root,'packages/ai/dist/index.js')).href);
const text=readFileSync(join(root,'packages/coding-agent/dist/core/compaction/compaction.js'),'utf8');
const prompt=[...text.matchAll(/const TURN_PREFIX_SUMMARIZATION_PROMPT = `([^`]+)`;/gu)][0][1];
const deps=Object.freeze({buildSessionContext:sessionModule.buildSessionContext,prepareCompaction:compaction.prepareCompaction,
  convertToLlm:messages.convertToLlm,serializeConversation:utils.serializeConversation,
  buildSummarizationPrompt:compaction.buildSummarizationPrompt,summarizationSystemPrompt:utils.SUMMARIZATION_SYSTEM_PROMPT,turnPrefixPrompt:prompt});
const hooks=new Map();
let calls=0, appends=0;
const captures=[];
const order=[];
const manager=sessionModule.SessionManager.inMemory(root);
const assistant=text=>({role:'assistant',content:[{type:'text',text}],timestamp:0,api:'private-test',model:'test',provider:'private-test',stopReason:'stop'});
manager.appendMessage({role:'user',content:opts.short?'tiny':"private-sentinel-prompt-and-summary".repeat(30),timestamp:0});
if(!opts.short){manager.appendMessage(assistant('prior stage'));manager.appendMessage({role:'user',content:'split prefix',timestamp:0});manager.appendMessage(assistant('R'.repeat(opts.backpressure?160000:1024)));}
const append=manager.appendCompaction.bind(manager);
manager.appendCompaction=(...args)=>{appends++;order.push('append');return append(...args)};
const witness=ext.registerContextWitness({on:(event,hook)=>hooks.set(event,hook)},deps,
  {descriptor:opts.closed?999999:(opts.descriptor??3),launchNonce:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",timeoutMs:opts.timeoutMs??1000,maxFrameBytes:opts.maxFrameBytes??1048576});
const api='private-test';
ai.clearApiProviders();
ai.registerApiProvider({api,stream:complete,streamSimple:complete},api);
function complete(model,context,settings){calls++;order.push('summary');const request=ext.canonicalJson(ext.projectPrimeContext(context.messages,context.systemPrompt));captures.push({request,maxTokens:settings.maxTokens});const stream=ai.createAssistantMessageEventStream();stream.push({type:'done',reason:'stop',message:assistant('checkpoint')});return stream;}
const session=Object.create(agent.AgentSession.prototype);
session.sessionManager=manager;
session.settingsManager={getCompactionSettings:()=>({enabled:false,reserveTokens:4096,keepRecentTokens:256})};
session.agent={state:{messages:manager.buildSessionContext().messages,thinkingLevel:'off'}};
session._extensionRunner={hasHandlers:event=>hooks.has(event),emit:async event=>{order.push(event.type);return hooks.get(event.type)?.(event,{sessionManager:manager,getSystemPrompt:()=>''});}};
session._mergeUnpersistedCompactionOutcomes=()=>{};session._restoreLateIpythonSentAgentMessages=()=>{};
session._notifyKernelStateAfterCompaction=async()=>{};session._reapDeletedRlmSubagentRuntimesAfterCompaction=async()=>{};
let error=null;
try {await session._performCompaction({model:{id:'test',api,provider:api,reasoning:false},apiKey:'synthetic',signal:new AbortController().signal});}
catch(e){error=e.message;}
const fenced=witness.closed;
witness.close();ai.clearApiProviders();guard.deregister();
process.stdout.write(JSON.stringify({calls,appends,order,error,fenced,captures:captures.map(capture=>({sha256:sha(capture.request),units:Buffer.byteLength(capture.request),max_tokens:capture.maxTokens}))}));
