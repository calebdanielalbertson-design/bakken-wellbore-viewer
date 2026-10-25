// Public snapshot transport. Reconstructed bytes retain original snapshot hashes.
const hex=bytes=>Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
const hash=async bytes=>{if(!globalThis.crypto?.subtle)throw Error('This viewer requires Web Crypto in a secure HTTPS browser context.');return hex(await crypto.subtle.digest('SHA-256',bytes));};
export function createSplitAssetFetch(nativeFetch,index,baseURL){
  if(index?.version!==2||!index.assets||index.maxPartBytes!==20971520)throw Error('Invalid public asset index.');
  const base=new URL(baseURL),pending=new Map();
  const safePath=value=>typeof value==='string'&&!value.startsWith('/')&&!value.includes('..')&&!value.includes('\\')&&!/[?#]/.test(value);
  for(const [name,asset]of Object.entries(index.assets)){
    if(!safePath(name)||!Number.isSafeInteger(asset.bytes)||asset.bytes<=0||asset.encoding!=='gzip'||!Number.isSafeInteger(asset.storedBytes)||asset.storedBytes<=0||!Array.isArray(asset.parts)||!asset.parts.length||!/^[a-f0-9]{64}$/.test(asset.sha256)||!/^[a-f0-9]{64}$/.test(asset.storedSHA256))throw Error('Invalid split asset metadata.');
    let bytes=0;for(const part of asset.parts){if(!safePath(part.path)||!Number.isSafeInteger(part.bytes)||part.bytes<=0||part.bytes>index.maxPartBytes||!/^[a-f0-9]{64}$/.test(part.sha256))throw Error('Invalid public asset part.');bytes+=part.bytes;}
    if(bytes!==asset.storedBytes)throw Error('Split stored asset lengths do not reconcile.');
  }
  async function assemble(asset,signal){
    if(typeof DecompressionStream!=='function')throw Error('This viewer requires a current browser with gzip DecompressionStream support. Please update your browser.');
    const parts=await Promise.all(asset.parts.map(async part=>{
      const response=await nativeFetch(new URL(part.path,base),{signal,credentials:'same-origin'});
      if(!response.ok)throw Error('Public snapshot part is unavailable. Please reload the viewer.');
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.byteLength!==part.bytes||await hash(bytes)!==part.sha256)throw Error('Public snapshot part failed its integrity check. Please reload.');
      return bytes;
    }));
    const stored=new Uint8Array(asset.storedBytes);let offset=0;for(const part of parts){stored.set(part,offset);offset+=part.length;}
    if(await hash(stored)!==asset.storedSHA256)throw Error('Compressed public snapshot failed its integrity check.');
    let result;try{result=new Uint8Array(await new Response(new Blob([stored]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());}catch{throw Error('Public snapshot could not be decompressed. Please reload in a current browser.');}
    if(result.byteLength!==asset.bytes)throw Error('Decompressed public snapshot length is incorrect.');
    if(await hash(result)!==asset.sha256)throw Error('Reconstructed public snapshot failed its integrity check.');
    return result;
  }
  return async function publicFetch(input,init){
    const request=input instanceof Request?input:null,url=new URL(request?request.url:String(input),globalThis.location?.href??new URL('viewer/',base));
    const method=String(init?.method??request?.method??'GET').toUpperCase();
    const relative=url.origin===base.origin&&url.pathname.startsWith(base.pathname)?url.pathname.slice(base.pathname.length):null;
    const asset=relative===null?null:index.assets[relative];
    if(method!=='GET'||!asset)return nativeFetch(input,init);
    const signal=init?.signal??request?.signal;if(signal?.aborted)throw signal.reason??new DOMException('Aborted','AbortError');
    // Share only an in-flight reconstruction, not an unbounded permanent cache.
    // Requests with an explicit signal keep independent cancellation semantics.
    let promise=signal?null:pending.get(relative);
    if(!promise){promise=assemble(asset,signal);if(!signal){pending.set(relative,promise);promise.finally(()=>{if(pending.get(relative)===promise)pending.delete(relative)}).catch(()=>{});}}
    return new Response(await promise,{status:200,headers:{'Content-Type':asset.contentType,'Content-Length':String(asset.bytes),'X-Public-Asset-SHA256':asset.sha256}});
  };
}
export async function installPublicAssetFetch(){
  const nativeFetch=globalThis.fetch.bind(globalThis),base=new URL('../',import.meta.url);
  const response=await nativeFetch(new URL('./public-assets-index.json',import.meta.url),{cache:'no-store'});
  if(!response.ok)throw Error('Public snapshot index is unavailable. Please reload.');
  globalThis.fetch=createSplitAssetFetch(nativeFetch,await response.json(),base);
}
