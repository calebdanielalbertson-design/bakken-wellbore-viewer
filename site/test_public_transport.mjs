// Run from this publishing checkout: node test_public_transport.mjs
// Uses the actual gzip fetch transport and prepared static files; no network.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {gzipSync} from 'node:zlib';

const root=path.resolve('dist');
const {createSplitAssetFetch}=await import(pathToFileURL(path.join(root,'viewer/public-assets.js')));
const index=JSON.parse(await fs.readFile(path.join(root,'viewer/public-assets-index.json')));
const digest=async value=>Buffer.from(await crypto.subtle.digest('SHA-256',value)).toString('hex');
let requests=[];
const native=async input=>{
  const url=new URL(String(input),'https://bakkensubsurface.com/viewer/');requests.push(url.pathname);
  try{return new Response(await fs.readFile(path.join(root,decodeURIComponent(url.pathname).replace(/^\//,''))));}
  catch{return new Response('missing',{status:404});}
};
const wrapped=createSplitAssetFetch(native,index,'https://bakkensubsurface.com/');
const oilPath='full-dataset/oil.bin',oilAsset=index.assets[oilPath];
const parallel=await Promise.all([wrapped('../'+oilPath),wrapped('https://bakkensubsurface.com/'+oilPath)]);
assert.equal(requests.length,oilAsset.parts.length,'concurrent calls share the same compressed transfer');
for(const response of parallel){
  const bytes=await response.arrayBuffer();assert.equal(bytes.byteLength,oilAsset.bytes);assert.equal(await digest(bytes),oilAsset.sha256);
  assert.equal(response.headers.get('content-length'),String(oilAsset.bytes));
}
const requested=await wrapped(new Request('https://bakkensubsurface.com/'+oilPath));
assert.equal(await digest(await requested.arrayBuffer()),oilAsset.sha256,'Request objects retain exact logical bytes');
const dsus=await (await wrapped('https://bakkensubsurface.com/viewer/data/dsu/drilling-spacing-units.geojson')).json();
assert.equal(dsus.features.length,10573);
const manifestBytes=await (await wrapped('../full-dataset/manifest.json')).arrayBuffer();
assert.equal(await digest(manifestBytes),'328deaf1f1d2bf9c9d7d5e961cd25be653f082a51fb6966f13be9e495ef4599c');
assert.ok((await (await wrapped('https://bakkensubsurface.com/viewer/style.css')).text()).includes('box-sizing'));

const corruptPart=async input=>{const response=await native(input),bytes=new Uint8Array(await response.arrayBuffer());bytes[0]^=1;return new Response(bytes);};
await assert.rejects(createSplitAssetFetch(corruptPart,index,'https://bakkensubsurface.com/')('../'+oilPath),/integrity/);
await assert.rejects(createSplitAssetFetch(async()=>new Response('',{status:404}),index,'https://bakkensubsurface.com/')('../'+oilPath),/unavailable/);
for(const field of ['storedSHA256','sha256']){
  const invalid=structuredClone(index);invalid.assets[oilPath][field]='0'.repeat(64);
  await assert.rejects(createSplitAssetFetch(native,invalid,'https://bakkensubsurface.com/')('../'+oilPath),/integrity/);
}
const invalidLength=structuredClone(index);invalidLength.assets[oilPath].bytes++;
await assert.rejects(createSplitAssetFetch(native,invalidLength,'https://bakkensubsurface.com/')('../'+oilPath),/length/);
const invalidPath=structuredClone(index);invalidPath.assets[oilPath].parts[0].path='../private';
assert.throws(()=>createSplitAssetFetch(native,invalidPath,'https://bakkensubsurface.com/'),/Invalid/);
const abort=new AbortController();abort.abort();await assert.rejects(wrapped('../'+oilPath,{signal:abort.signal}));

// Actual browser API, not a substituted decompressor. Unsupported environments
// must get a useful failure before the application tries to read binary arrays.
const decompression=Object.getOwnPropertyDescriptor(globalThis,'DecompressionStream');
try{Object.defineProperty(globalThis,'DecompressionStream',{value:undefined,configurable:true});await assert.rejects(wrapped('../'+oilPath),/current browser.*DecompressionStream/);}
finally{Object.defineProperty(globalThis,'DecompressionStream',decompression);}
const cryptography=Object.getOwnPropertyDescriptor(globalThis,'crypto');
try{Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});await assert.rejects(wrapped('../'+oilPath),/Web Crypto.*HTTPS/);}
finally{Object.defineProperty(globalThis,'crypto',cryptography);}

// A genuine multipart gzip stream covers the split/join path even when today's
// compressed objects individually fit in one static-host object.
const original=new TextEncoder().encode('Exact original JSON/binary bytes survive multipart gzip transport.');
const compressed=new Uint8Array(gzipSync(original)),partBuffers=[],parts=[];
for(let offset=0;offset<compressed.length;offset+=11){
  const bytes=compressed.slice(offset,offset+11),name='chunks/'+parts.length+'.gz.bin';partBuffers.push(bytes);parts.push({path:name,bytes:bytes.length,sha256:await digest(bytes)});
}
const fixture={version:2,maxPartBytes:20971520,assets:{'sample.bin':{bytes:original.length,sha256:await digest(original),encoding:'gzip',storedBytes:compressed.length,storedSHA256:await digest(compressed),contentType:'application/octet-stream',parts}}};
const multiNative=async input=>new Response(partBuffers[Number(new URL(input).pathname.match(/\/(\d+)\.gz\.bin$/)[1])]);
assert.deepEqual(new Uint8Array(await (await createSplitAssetFetch(multiNative,fixture,'https://bakkensubsurface.com/')('https://bakkensubsurface.com/sample.bin')).arrayBuffer()),original);
const malformed=new Uint8Array(compressed);malformed[0]=0;
const broken={version:2,maxPartBytes:20971520,assets:{'broken.bin':{bytes:original.length,sha256:await digest(original),encoding:'gzip',storedBytes:malformed.length,storedSHA256:await digest(malformed),contentType:'application/octet-stream',parts:[{path:'broken.gz.bin',bytes:malformed.length,sha256:await digest(malformed)}]}}};
await assert.rejects(createSplitAssetFetch(async()=>new Response(malformed),broken,'https://bakkensubsurface.com/')('https://bakkensubsurface.com/broken.bin'),/could not be decompressed/);
console.log('PASS gzip transport: original oil/DSU/manifest bytes, JSON/Request compatibility, concurrent sharing, multipart gzip, part/stored/original integrity, length/404/path/abort errors, malformed gzip, unsupported DecompressionStream/WebCrypto, normal fetch delegation.');
